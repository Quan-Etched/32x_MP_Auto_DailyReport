"""Flatten the suite/case nesting down to **test items** — the numeric layer.

THE PROBLEM
-----------
Today's resolution stops at the test case, which is a boolean::

    run -> test case: PASSED | FAILED

That cannot answer "why", "by how much", or "is this unit marginal". One bit per
test case is not enough to act on.

THE DATA THAT IS ALREADY THERE
------------------------------
The ``event_stream`` artifact (OCP ``log.jsonl``) — which the collector already
downloads for run timing and then throws away — carries one ``measurement``
event per test item::

    {"testStepArtifact": {"testStepId": "7", "measurement": {
        "name": "ber_0_0_1", "value": 2.0269150366843607e-10,
        "validators": [], "metadata": {"device_index":0,"phy_idx":0,"lane_idx":1}}}}

Measured on real runs: **~7,500 measurements per L10 SFT run, 74% of them
int/float**, with units (Hz, uC, degrees C, GB, RPM, IOPS, MiB/s) and
``metadata`` carrying the dimensions (device / phy / lane). Extracting them costs
**zero extra API calls**.

THE THREE-LEVEL FLATTENING
--------------------------
``run -> case`` becomes::

    run -> step (case) -> item (name template) -> instance (dims) -> value

The name template is what makes this usable. A single SFT run emits 7,472
*distinct* measurement names, but only **1,195 distinct templated items**:
``ber_0_0_1``, ``ber_0_0_2`` … ``ber_2_7_127`` are one item, ``ber``, measured on
3,072 lanes. Without templating you get 7,472 one-sample "items" and no
distribution; with it you get one item with 3,072 samples per unit.

THE LIMIT PROBLEM — READ THIS BEFORE TRUSTING A "WHY"
-----------------------------------------------------
The OCP ``validators`` field is the place limits belong, and it is **empty on
every one of the ~30,000 measurements sampled**. ``suite_config.yaml`` holds test
configuration (2 limit-ish keys in 17 KB), and ``bom_config.yaml`` holds expected
part numbers and firmware versions — not analog limits. So EOS publishes the
*values* but not the *thresholds*: the pass/fail decision is made inside the
harness and only the boolean escapes.

Consequences, and they are the whole design:

1. A definitive "it failed because it exceeded limit X" is **not derivable
   today**. The fix is upstream and cheap — populate ``validators``, a field the
   harness already emits empty.
2. Until then, limits are **empirical**: the distribution of the *passing*
   population for the same item, station and release. "This unit's worst lane
   BER was 4e-6 against a passing median of 1e-11" is actionable even without a
   published spec, and is how capability analysis works anyway.
3. Anything scraped out of a failure message is labelled as extracted prose and
   never treated as ground truth.

STORAGE
-------
~7,500 rows per SFT run and ~119 SFT runs per 30 days is ~850k rows — two orders
of magnitude past what belongs in a browser bundle. So the fact table lives in
**SQLite** (stdlib ``sqlite3``, no new dependency), and only per-item summaries
and histograms are ever published.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from . import config, stations

log = logging.getLogger(__name__)

DB_PATH = config.PROCESSED_DIR / "items.sqlite"

#: Value kinds. ``bool`` is stored numerically (0/1) so a pass-rate per item is
#: a plain average, but kept distinct from a real measurement so it is never
#: plotted as a distribution.
NUM, BOOL, STR = "num", "bool", "str"


# ----------------------------------------------------------------- templating

_INT_RUN = re.compile(r"(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])|(?<=[a-z_])\d+")
_WS = re.compile(r"\s+")

#: PCI bus addresses (``0000:1a:00.0``) must collapse as a WHOLE, before the
#: generic integer rule sees them. Their segments are hex, so that rule mangles
#: them into ``<i>:1a:<i>.<i>`` — which makes every distinct address its own
#: item, inflates the catalog, and manufactures phantom added/removed churn in a
#: release diff, because different systems enumerate devices at different
#: addresses. Observed live: it was a large share of the 189->190 add/remove.
# \b cannot be used here: these tokens sit next to "_", which is a word
# character, so there is no boundary. Exclude only hex continuation.
_BDF = re.compile(r"(?<![0-9a-f])[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f](?![0-9a-f])", re.I)

#: Same reasoning for MACs and UUIDs: they identify a unit, not a measurement.
_MAC = re.compile(r"(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])", re.I)
_UUID = re.compile(
    r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?![0-9a-f])", re.I)


def template_name(name: Any) -> str:
    """Collapse an instance name to its item template.

    ``ber_0_0_1`` -> ``ber_<i>_<i>_<i>``; ``chip3_pd_north_east_chain_12`` ->
    ``chip<i>_pd_north_east_chain_<i>``. Index runs become ``<i>`` so the same
    physical measurement on different lanes/chips groups into one item.

    Address-shaped tokens collapse first and as a whole, because they say *where
    a device sits*, not what is measured.
    """
    text = _WS.sub(" ", str(name or "")).strip()
    if not text:
        return "(unnamed)"
    text = _UUID.sub("<uuid>", text)
    text = _BDF.sub("<bdf>", text)
    text = _MAC.sub("<mac>", text)
    return _INT_RUN.sub("<i>", text)


_CHIP = re.compile(r"chip[_\-]?(\d+)", re.I)


def derive_chip(name: Any, metadata: Optional[Dict[str, Any]]) -> Optional[int]:
    """Which chip a measurement belongs to.

    A bad chip and a bad board call for different actions, so per-chip
    attribution matters. ``hardwareInfoId`` is populated on almost nothing, so
    this reads the name prefix first and falls back to ``device_index``.
    """
    match = _CHIP.search(str(name or ""))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    if isinstance(metadata, dict):
        for key in ("device_index", "chip_index", "chip", "deviceIndex"):
            value = metadata.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def classify_value(value: Any) -> Tuple[str, Optional[float], Optional[str]]:
    """Split a measurement value into (kind, numeric, text)."""
    if isinstance(value, bool):
        return BOOL, 1.0 if value else 0.0, None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return STR, None, str(value)[:200]
        # NaN/inf would poison every aggregate downstream.
        if number != number or number in (float("inf"), float("-inf")):
            return STR, None, str(value)[:200]
        return NUM, number, None
    if value is None:
        return STR, None, None
    return STR, None, str(value)[:200]


# ------------------------------------------------------------------ extraction

def extract_items(raw: Any, run: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten one run's event stream into test-item rows.

    Each measurement is attributed to the step it was emitted under, so an item
    keeps its bridge back to the boolean test case the line already knows.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", "replace")
    if not isinstance(raw, str):
        return []

    step_name: Dict[str, str] = {}
    step_status: Dict[str, str] = {}
    pending: List[Dict[str, Any]] = []

    release = stations.release_of(run.get("version"))
    base = {
        "run_id": run.get("runId"),
        "dut": run.get("dutSerial"),
        "station": run.get("stationKey"),
        "level": run.get("level"),
        "suite": run.get("suite"),
        "release": release,
        "start_ts": run.get("startTs"),
    }

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # a truncated final line is expected
        if not isinstance(event, dict):
            continue

        artifact = event.get("testStepArtifact") or {}
        step_id = artifact.get("testStepId")

        start = artifact.get("testStepStart")
        if isinstance(start, dict) and step_id is not None:
            step_name[step_id] = str(start.get("name") or "")
            continue

        end = artifact.get("testStepEnd")
        if isinstance(end, dict) and step_id is not None:
            step_status[step_id] = str(end.get("status") or "")
            continue

        measurement = artifact.get("measurement")
        if not isinstance(measurement, dict):
            continue

        name = measurement.get("name")
        metadata = measurement.get("metadata")
        kind, number, text = classify_value(measurement.get("value"))
        validators = measurement.get("validators") or []

        pending.append({
            **base,
            "step_id": step_id,
            "item": template_name(name),
            "item_raw": str(name) if name is not None else None,
            "chip": derive_chip(name, metadata),
            "dims": json.dumps(metadata, separators=(",", ":")) if metadata else None,
            "unit": measurement.get("unit"),
            "vtype": kind,
            "num": number,
            "txt": text,
            # Recorded so the day validators start arriving, it is visible
            # immediately rather than silently ignored.
            "limits": json.dumps(validators, separators=(",", ":")) if validators else None,
            "ts": event.get("timestamp"),
        })

    # Step names/statuses are only known once their events have been seen.
    for row in pending:
        step_id = row.pop("step_id", None)
        row["step"] = step_name.get(step_id) or None
        row["step_status"] = step_status.get(step_id) or None
    return pending


# -------------------------------------------------------------------- storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    run_id      TEXT NOT NULL,
    dut         TEXT,
    station     TEXT,
    level       TEXT,
    suite       TEXT,
    release     TEXT,
    start_ts    INTEGER,
    step        TEXT,
    step_status TEXT,
    item        TEXT NOT NULL,
    item_raw    TEXT,
    chip        INTEGER,
    dims        TEXT,
    unit        TEXT,
    vtype       TEXT,
    num         REAL,
    txt         TEXT,
    limits      TEXT,
    ts          TEXT
);
CREATE INDEX IF NOT EXISTS idx_item        ON items(item, station);
CREATE INDEX IF NOT EXISTS idx_item_num    ON items(item, station, vtype, num);
CREATE INDEX IF NOT EXISTS idx_run         ON items(run_id);
CREATE INDEX IF NOT EXISTS idx_dut         ON items(dut);
CREATE TABLE IF NOT EXISTS ingested (
    run_id TEXT PRIMARY KEY,
    rows   INTEGER,
    at     TEXT
);
"""

COLUMNS = ("run_id", "dut", "station", "level", "suite", "release", "start_ts",
           "step", "step_status", "item", "item_raw", "chip", "dims", "unit",
           "vtype", "num", "txt", "limits", "ts")


def open_db(path: Optional[Path] = None) -> sqlite3.Connection:
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    # Bulk inserts of ~850k rows; the default sync mode makes this crawl.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def already_ingested(conn: sqlite3.Connection, run_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM ingested WHERE run_id = ?", (run_id,)).fetchone()
    return row is not None


def ingest(conn: sqlite3.Connection, run_id: str, rows: Sequence[Dict[str, Any]]) -> int:
    """Replace a run's rows. Idempotent, so a re-collection cannot double-count."""
    conn.execute("DELETE FROM items WHERE run_id = ?", (run_id,))
    conn.executemany(
        "INSERT INTO items ({}) VALUES ({})".format(
            ",".join(COLUMNS), ",".join("?" * len(COLUMNS))),
        [tuple(row.get(col) for col in COLUMNS) for row in rows],
    )
    conn.execute(
        "INSERT OR REPLACE INTO ingested(run_id, rows, at) VALUES (?,?,datetime('now'))",
        (run_id, len(rows)),
    )
    conn.commit()
    return len(rows)


# ------------------------------------------------------------------ analytics

def percentile(sorted_values: Sequence[float], fraction: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def catalog(conn: sqlite3.Connection, station: Optional[str] = None,
            limit: int = 40) -> List[Dict[str, Any]]:
    """The test-item catalog: what items exist and how measurable they are."""
    where, params = "WHERE vtype IN ('num','bool')", []
    if station:
        where += " AND station = ?"
        params.append(station)
    sql = """
        SELECT item, station, unit, vtype,
               COUNT(*) AS samples,
               COUNT(DISTINCT dut) AS duts,
               COUNT(DISTINCT run_id) AS runs,
               COUNT(DISTINCT item_raw) AS instances,
               MIN(num) AS lo, MAX(num) AS hi, AVG(num) AS mean
        FROM items {}
        GROUP BY item, station, vtype
        HAVING duts >= 2
        ORDER BY duts DESC, samples DESC
        LIMIT ?
    """.format(where)
    return [dict(r) for r in conn.execute(sql, params + [limit])]


def item_stats(conn: sqlite3.Connection, item: str, station: Optional[str] = None,
               release: Optional[str] = None,
               only_status: Optional[str] = None) -> Dict[str, Any]:
    """Distribution of one numeric item, optionally restricted to a population.

    ``only_status`` filters on the *step* verdict, which is how an empirical
    limit is built: describe the COMPLETE population, then judge a suspect
    value against it.
    """
    sql = "SELECT num FROM items WHERE item = ? AND vtype = 'num' AND num IS NOT NULL"
    params: List[Any] = [item]
    if station:
        sql += " AND station = ?"; params.append(station)
    if release:
        sql += " AND release = ?"; params.append(release)
    if only_status:
        sql += " AND step_status = ?"; params.append(only_status)
    sql += " ORDER BY num"

    values = [r[0] for r in conn.execute(sql, params)]
    if not values:
        return {"item": item, "samples": 0}

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return {
        "item": item, "station": station, "release": release,
        "population": only_status or "all",
        "samples": len(values),
        "min": values[0], "max": values[-1], "mean": mean,
        "sd": variance ** 0.5,
        "p1": percentile(values, 0.01), "p25": percentile(values, 0.25),
        "median": percentile(values, 0.50), "p75": percentile(values, 0.75),
        "p99": percentile(values, 0.99),
    }


def per_dut(conn: sqlite3.Connection, item: str, station: Optional[str] = None,
            agg: str = "MAX") -> List[Dict[str, Any]]:
    """One row per DUT for a high-cardinality item.

    A per-lane item has thousands of values per unit, so a cross-DUT
    distribution needs **two** aggregation levels: reduce within the unit first
    (worst lane, typically MAX), then compare across units. Skipping the first
    level plots lanes, not units, and hides which board is bad.
    """
    if agg not in ("MAX", "MIN", "AVG", "COUNT"):
        raise ValueError("unsupported aggregate: {}".format(agg))
    sql = """
        SELECT dut, release, step_status,
               {}(num) AS value, COUNT(*) AS lanes
        FROM items
        WHERE item = ? AND vtype = 'num' AND num IS NOT NULL
    """.format(agg)
    params: List[Any] = [item]
    if station:
        sql += " AND station = ?"; params.append(station)
    sql += " GROUP BY dut, release, step_status ORDER BY value DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def histogram(values: Sequence[float], bins: int = 24) -> Dict[str, Any]:
    """Fixed-bin histogram — what gets published instead of raw values."""
    numbers = sorted(v for v in values if v is not None)
    if not numbers:
        return {"bins": [], "lo": None, "hi": None}
    lo, hi = numbers[0], numbers[-1]
    if hi == lo:
        return {"bins": [len(numbers)], "lo": lo, "hi": hi}
    width = (hi - lo) / bins
    counts = [0] * bins
    for value in numbers:
        index = min(bins - 1, int((value - lo) / width))
        counts[index] += 1
    return {"bins": counts, "lo": lo, "hi": hi, "width": width}


def margin(value: float, stats: Dict[str, Any]) -> Optional[float]:
    """How far a value sits from the reference population, in sigma.

    This is the stand-in for a published limit. It is a *relative* statement —
    "8 sigma outside the passing population" — never "outside spec", because
    the spec is not published (see the module docstring).
    """
    sd = stats.get("sd")
    if not sd:
        return None
    return (value - stats["mean"]) / sd


def summary_counts(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute("""
        SELECT COUNT(*) AS rows, COUNT(DISTINCT item) AS items,
               COUNT(DISTINCT item_raw) AS instances,
               COUNT(DISTINCT run_id) AS runs, COUNT(DISTINCT dut) AS duts
        FROM items
    """).fetchone()
    kinds = {r["vtype"]: r["n"] for r in conn.execute(
        "SELECT vtype, COUNT(*) AS n FROM items GROUP BY vtype")}
    withlimits = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE limits IS NOT NULL").fetchone()["n"]
    return {**dict(row), "kinds": kinds, "withPublishedLimits": withlimits}
