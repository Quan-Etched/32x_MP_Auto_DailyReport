"""Per-release test-item manifests, and a compatibility diff between releases.

WHAT THIS ANSWERS
-----------------
"For release 207, what test items exist, what do they measure, and what changed
versus 204 — what was added, removed, or edited?"

THE IDENTITY THAT MAKES A DIFF POSSIBLE
---------------------------------------
An item is identified by ``(station, item template)`` — see ``items.py`` for why
templating is what turns 7,472 instance names into ~1,000 stable items. That
identity is what survives across releases, so set arithmetic on it is meaningful.

Each ``(release, item)`` gets a **signature**: value type, unit, instance count,
chip coverage, the test steps it appears under, and (for numeric items) the
distribution. A diff is then set operations on identity plus field comparison on
signatures.

ABSENCE OF EVIDENCE IS NOT EVIDENCE OF ABSENCE
----------------------------------------------
This is the trap in a release diff, and it is the main thing this module is
careful about. Release 203 in the live data has **one run**; release 190 has 31.
Naively diffing them reports ~200 "removed" items when the truth is that a single
run simply did not exercise them.

Two defences:

* **Prevalence** — the fraction of a release's runs in which an item appeared. An
  item present in 1 of 31 runs is weak evidence of existence, and its absence in
  the next release is weak evidence of removal.
* **Confidence** — a release with fewer than :data:`MIN_RUNS_CONFIDENT` runs
  produces a diff labelled ``low`` and every add/remove in it is marked
  unconfirmed. The UI must show that, not hide it.

A diff never silently asserts a removal it cannot support.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config, items as items_mod, stations

log = logging.getLogger(__name__)

#: Below this many runs, a release cannot support add/remove claims.
MIN_RUNS_CONFIDENT = 3

#: An item seen in fewer than this fraction of a release's runs is "occasional";
#: its appearance or disappearance is reported but flagged as weak.
PREVALENCE_WEAK = 0.5

#: Distribution comparison needs enough samples on both sides to mean anything.
MIN_SAMPLES_FOR_SHIFT = 30

#: Standardized median move (in prior-release sigma) that counts as a shift.
SHIFT_SIGMA = 3.0

#: Fold-change that counts as a shift when sigma is unusable (e.g. sd == 0).
SHIFT_RATIO = 3.0

# Change kinds, ordered most to least consequential. The order IS the severity
# ranking used for sorting and colouring.
KIND_REMOVED = "removed"
KIND_TYPE = "type-changed"
KIND_UNIT = "unit-changed"
KIND_ADDED = "added"
KIND_COVERAGE = "coverage-changed"
KIND_MOVED = "step-moved"
KIND_SHIFT = "distribution-shift"

SEVERITY = [KIND_REMOVED, KIND_TYPE, KIND_UNIT, KIND_ADDED,
            KIND_COVERAGE, KIND_MOVED, KIND_SHIFT]

#: Why each kind matters, surfaced in the UI so a reader need not guess.
KIND_MEANING = {
    KIND_REMOVED: "The item is no longer measured. Any trend on it stops here.",
    KIND_TYPE: "Value type changed (e.g. number to string). Breaks trending and "
               "any distribution built on it.",
    KIND_UNIT: "Unit changed. Every chart axis and threshold on this item now "
               "means something different.",
    KIND_ADDED: "New item, first measured in this release. No history to compare.",
    KIND_COVERAGE: "Same item, different amount measured (instance or chip count "
                   "changed). Coverage moved, not the measurement.",
    KIND_MOVED: "The item is now reported under a different test step, so it "
                "attributes to a different test case.",
    KIND_SHIFT: "Same item and unit, but the values moved. Either the hardware, "
                "the test conditions, or an unpublished limit changed.",
}


# ------------------------------------------------------------------ signatures

def release_meta(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """One row per (station, release) with its coverage."""
    rows = []
    for r in conn.execute("""
        SELECT station, release,
               COUNT(DISTINCT run_id) AS runs,
               COUNT(DISTINCT dut)    AS duts,
               COUNT(DISTINCT item)   AS items,
               COUNT(DISTINCT item_raw) AS instances,
               COUNT(*) AS samples,
               MIN(start_ts) AS first_ts, MAX(start_ts) AS last_ts
        FROM items
        WHERE release IS NOT NULL
        GROUP BY station, release
    """):
        entry = dict(r)
        entry["confident"] = entry["runs"] >= MIN_RUNS_CONFIDENT
        rows.append(entry)
    rows.sort(key=lambda e: (e["station"], stations.release_sort_key(e["release"])))
    return rows


def item_signatures(conn: sqlite3.Connection, station: str,
                    release: str) -> Dict[str, Dict[str, Any]]:
    """Signature of every item in one (station, release).

    Numeric statistics are computed only for numeric items, and only from rows
    with a real value — a percentile over a mixed column is meaningless.
    """
    runs_total = conn.execute(
        "SELECT COUNT(DISTINCT run_id) n FROM items WHERE station=? AND release=?",
        (station, release)).fetchone()["n"] or 0

    signatures: Dict[str, Dict[str, Any]] = {}
    for r in conn.execute("""
        SELECT item,
               COUNT(*) AS samples,
               COUNT(DISTINCT item_raw) AS instances,
               COUNT(DISTINCT run_id) AS runs_present,
               COUNT(DISTINCT dut) AS duts
        FROM items WHERE station=? AND release=?
        GROUP BY item
    """, (station, release)):
        signatures[r["item"]] = {
            "item": r["item"],
            "samples": r["samples"],
            "instances": r["instances"],
            "runsPresent": r["runs_present"],
            "duts": r["duts"],
            "prevalence": (r["runs_present"] / runs_total) if runs_total else 0.0,
        }

    # Dominant type and unit. A mixed item is reported as its most common type
    # rather than silently picking one.
    for r in conn.execute("""
        SELECT item, vtype, unit, COUNT(*) AS n
        FROM items WHERE station=? AND release=?
        GROUP BY item, vtype, unit
    """, (station, release)):
        sig = signatures.get(r["item"])
        if sig is None:
            continue
        sig.setdefault("_types", Counter())[r["vtype"]] += r["n"]
        if r["unit"]:
            sig.setdefault("_units", Counter())[r["unit"]] += r["n"]

    for r in conn.execute("""
        SELECT item, GROUP_CONCAT(DISTINCT chip) AS chips,
               GROUP_CONCAT(DISTINCT step) AS steps
        FROM items WHERE station=? AND release=?
        GROUP BY item
    """, (station, release)):
        sig = signatures.get(r["item"])
        if sig is None:
            continue
        sig["chips"] = sorted({int(c) for c in (r["chips"] or "").split(",") if c not in ("", None)})
        sig["steps"] = sorted({s for s in (r["steps"] or "").split(",") if s})

    for sig in signatures.values():
        types = sig.pop("_types", Counter())
        units = sig.pop("_units", Counter())
        sig["vtype"] = types.most_common(1)[0][0] if types else None
        sig["mixedType"] = len(types) > 1
        sig["unit"] = units.most_common(1)[0][0] if units else None
        sig.setdefault("chips", [])
        sig.setdefault("steps", [])

    _attach_numeric_stats(conn, station, release, signatures)
    return signatures


def _attach_numeric_stats(conn, station, release, signatures) -> None:
    numeric = [name for name, sig in signatures.items() if sig.get("vtype") == items_mod.NUM]
    for name in numeric:
        values = [r[0] for r in conn.execute(
            "SELECT num FROM items WHERE station=? AND release=? AND item=? "
            "AND vtype='num' AND num IS NOT NULL ORDER BY num",
            (station, release, name))]
        if not values:
            continue
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        signatures[name]["stats"] = {
            "n": len(values),
            "min": values[0], "max": values[-1], "mean": mean,
            "sd": variance ** 0.5,
            "p25": items_mod.percentile(values, 0.25),
            "median": items_mod.percentile(values, 0.50),
            "p75": items_mod.percentile(values, 0.75),
            "p99": items_mod.percentile(values, 0.99),
        }


# ----------------------------------------------------------------------- diff

def diff_signatures(before: Dict[str, Dict[str, Any]],
                    after: Dict[str, Dict[str, Any]],
                    before_meta: Dict[str, Any],
                    after_meta: Dict[str, Any],
                    step_intern=None) -> Dict[str, Any]:
    """Compatibility diff between two releases of the same station.

    Returns added / removed / changed / unchanged, each entry carrying enough
    context that the UI never has to re-derive anything, plus a confidence
    verdict for the comparison as a whole.
    """
    confident = bool(before_meta.get("confident")) and bool(after_meta.get("confident"))

    added, removed, changed, unchanged = [], [], [], []

    for name in sorted(set(after) - set(before)):
        sig = after[name]
        added.append({
            "item": name, "kinds": [KIND_ADDED], "d": _descriptor(sig),
            # An item that appears in only some runs may have existed before and
            # simply not been sampled.
            "weak": (not confident) or sig["prevalence"] < PREVALENCE_WEAK,
        })

    for name in sorted(set(before) - set(after)):
        sig = before[name]
        removed.append({
            "item": name, "kinds": [KIND_REMOVED], "d": _descriptor(sig),
            "weak": (not confident) or sig["prevalence"] < PREVALENCE_WEAK,
        })

    for name in sorted(set(before) & set(after)):
        a, b = before[name], after[name]
        kinds, notes = [], {}

        if a.get("vtype") != b.get("vtype"):
            kinds.append(KIND_TYPE)
            notes["vtype"] = [a.get("vtype"), b.get("vtype")]
        if (a.get("unit") or None) != (b.get("unit") or None):
            kinds.append(KIND_UNIT)
            notes["unit"] = [a.get("unit"), b.get("unit")]
        if a.get("instances") != b.get("instances") or a.get("chips") != b.get("chips"):
            kinds.append(KIND_COVERAGE)
            notes["instances"] = [a.get("instances"), b.get("instances")]
            if a.get("chips") != b.get("chips"):
                notes["chips"] = [a.get("chips"), b.get("chips")]
        if a.get("steps") != b.get("steps"):
            kinds.append(KIND_MOVED)
            notes["steps"] = [a.get("steps"), b.get("steps")]

        shift = _distribution_shift(a.get("stats"), b.get("stats"))
        if shift and shift.get("shifted"):
            kinds.append(KIND_SHIFT)
            notes["shift"] = shift

        entry = {
            "item": name, "kinds": kinds, "notes": notes, "d": _descriptor(b),
            "weak": (not confident)
                    or min(a["prevalence"], b["prevalence"]) < PREVALENCE_WEAK,
        }
        if kinds:
            changed.append(entry)
        else:
            unchanged.append(name)

    changed.sort(key=lambda e: (SEVERITY.index(e["kinds"][0]), e["item"]))

    counts = Counter()
    for entry in added + removed + changed:
        for kind in entry["kinds"]:
            counts[kind] += 1

    return {
        "from": before_meta.get("release"),
        "to": after_meta.get("release"),
        "station": after_meta.get("station"),
        "confidence": "ok" if confident else "low",
        "confidenceReason": None if confident else (
            "{} run(s) in {} and {} in {}; fewer than {} runs cannot support "
            "add/remove claims — an item may simply not have been exercised."
            .format(before_meta.get("runs"), before_meta.get("release"),
                    after_meta.get("runs"), after_meta.get("release"),
                    MIN_RUNS_CONFIDENT)),
        "counts": dict(counts),
        "totals": {"added": len(added), "removed": len(removed),
                   "changed": len(changed), "unchanged": len(unchanged)},
        "added": added, "removed": removed, "changed": changed,
    }


def _sig6(value: Any) -> Any:
    """Round to 6 significant figures.

    Full float repr costs ~17 characters per number and this payload carries tens
    of thousands of them; 6 figures is far beyond display precision.
    """
    if isinstance(value, float):
        if value == 0 or value != value:
            return 0 if value == 0 else None
        return float("{:.6g}".format(value))
    return value


def _descriptor(sig: Dict[str, Any]) -> Dict[str, Any]:
    """The few fields needed to render a diff row without fetching detail.

    A diff carries the *delta*, not two full signatures — shipping both snapshots
    for every changed item was the single biggest cost in the payload, and the
    full signature is one lazy fetch away in the release detail file.
    """
    out = {"t": sig.get("vtype"), "n": sig.get("instances"), "s": sig.get("samples")}
    if sig.get("unit"):
        out["u"] = sig["unit"]
    return out


def _public(sig: Dict[str, Any], step_intern=None) -> Dict[str, Any]:
    """The signature fields worth shipping to the browser.

    Step names are long and repeat across every item and release, so they are
    interned to indices when an interner is supplied.
    """
    out = {k: sig.get(k) for k in
           ("vtype", "unit", "instances", "samples", "duts", "chips",
            "runsPresent", "mixedType")}
    out["prevalence"] = _sig6(sig.get("prevalence"))
    steps = sig.get("steps") or []
    out["steps"] = [step_intern(s) for s in steps] if step_intern else steps
    if not out["mixedType"]:
        out.pop("mixedType")
    if sig.get("stats"):
        out["stats"] = {k: _sig6(sig["stats"][k]) for k in
                        ("n", "min", "p25", "median", "p75", "p99", "max", "sd")}
    return out


def _distribution_shift(a: Optional[Dict[str, Any]],
                        b: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Has the same item's distribution moved between releases?

    Reported two ways because neither alone survives real data: a standardized
    move in prior-release sigma, and a fold change. BER medians sit near zero, so
    a ratio explodes; a constant item has sd == 0, so sigma is unusable. Whichever
    is meaningful decides.
    """
    if not a or not b:
        return None
    if a["n"] < MIN_SAMPLES_FOR_SHIFT or b["n"] < MIN_SAMPLES_FOR_SHIFT:
        return {"shifted": False, "reason": "insufficient samples",
                "n": [a["n"], b["n"]]}

    ma, mb, sd = a["median"], b["median"], a["sd"]
    sigma = ((mb - ma) / sd) if sd else None
    ratio = (mb / ma) if ma not in (0, None) else None

    shifted = False
    if sigma is not None and abs(sigma) >= SHIFT_SIGMA:
        shifted = True
    elif ratio is not None and (ratio >= SHIFT_RATIO or ratio <= 1.0 / SHIFT_RATIO):
        shifted = True

    return {
        "shifted": shifted,
        "medianBefore": ma, "medianAfter": mb,
        "sigma": sigma, "ratio": ratio,
        "direction": "up" if mb > ma else ("down" if mb < ma else "flat"),
        "n": [a["n"], b["n"]],
    }


# --------------------------------------------------------------------- bundle

def build_bundle(conn: sqlite3.Connection,
                 payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Assemble the releases page bundle.

    Item names are **interned** into one array and referenced by index. They
    average ~40 characters and would otherwise repeat across every release,
    dominating the payload.
    """
    meta = release_meta(conn)
    by_station: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in meta:
        by_station[entry["station"]].append(entry)

    names: List[str] = []
    index: Dict[str, int] = {}
    step_names: List[str] = []
    step_index: Dict[str, int] = {}

    def intern(name: str) -> int:
        if name not in index:
            index[name] = len(names)
            names.append(name)
        return index[name]

    def intern_step(name: str) -> int:
        if name not in step_index:
            step_index[name] = len(step_names)
            step_names.append(name)
        return step_index[name]

    releases: List[Dict[str, Any]] = []
    diffs: List[Dict[str, Any]] = []
    detail: Dict[Tuple[str, str], Dict[str, Any]] = {}
    version_map = _versions_by_release(payload)

    for station, entries in sorted(by_station.items()):
        previous_sig: Optional[Dict[str, Dict[str, Any]]] = None
        previous_meta: Optional[Dict[str, Any]] = None
        for entry in entries:
            signatures = item_signatures(conn, station, entry["release"])
            detail[(station, entry["release"])] = {
                "station": station, "release": entry["release"],
                "sig": {intern(name): _public(sig, intern_step)
                        for name, sig in signatures.items()},
            }
            releases.append({
                **{k: entry[k] for k in ("station", "release", "runs", "duts",
                                         "items", "instances", "samples",
                                         "first_ts", "last_ts", "confident")},
                "versions": sorted(version_map.get((station, entry["release"]), [])),
                "detail": detail_name(station, entry["release"]),
            })
            if previous_sig is not None:
                d = diff_signatures(previous_sig, signatures, previous_meta, entry,
                                    intern_step)
                for bucket in ("added", "removed", "changed"):
                    for row in d[bucket]:
                        row["i"] = intern(row.pop("item"))
                diffs.append(d)
            previous_sig, previous_meta = signatures, entry

    # Per-item cross-release trend for NUMERIC items only, carried in the index.
    # This is what lets an expanded item draw its own history immediately; the
    # alternative — fetching every release's detail file to assemble a series —
    # would download ~600 KB on one click. Numeric items only, because a trend
    # over strings or booleans is not a distribution.
    trends: Dict[str, Dict[str, List[List[Any]]]] = defaultdict(lambda: defaultdict(list))
    for entry in releases:
        station, release = entry["station"], entry["release"]
        for idx, sig in detail[(station, release)]["sig"].items():
            stats = sig.get("stats")
            if not stats:
                continue
            trends[station][str(idx)].append([
                release, stats["n"], stats["median"], stats["p25"], stats["p75"]])

    return {
        "schemaVersion": 1,
        "_detail": detail,          # popped by write_bundle into separate files
        "trends": {s: dict(v) for s, v in trends.items()},
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "timezone": config.timezone_name(),
        "items": names,
        "steps": step_names,
        "releases": releases,
        "diffs": diffs,
        "kindMeaning": KIND_MEANING,
        "severity": SEVERITY,
        "thresholds": {
            "minRunsConfident": MIN_RUNS_CONFIDENT,
            "prevalenceWeak": PREVALENCE_WEAK,
            "minSamplesForShift": MIN_SAMPLES_FOR_SHIFT,
            "shiftSigma": SHIFT_SIGMA,
            "shiftRatio": SHIFT_RATIO,
        },
        "stationLabels": {s["key"]: s["label"] for s in stations.registry()},
    }


def _versions_by_release(payload: Optional[Dict[str, Any]]) -> Dict[Tuple[str, str], set]:
    """Full version strings behind each release number, from the run table."""
    mapping: Dict[Tuple[str, str], set] = defaultdict(set)
    for run in (payload or {}).get("runs", []):
        key = (run.get("stationKey"), stations.release_of(run.get("version")))
        if key[0] and key[1] and run.get("version"):
            mapping[key].add(run["version"])
    return mapping


def detail_name(station: str, release: str) -> str:
    """Filename for one release's full item detail."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(release))
    return "{}-{}.json".format(station, safe)


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Tuple[Path, int]:
    """Write the index bundle plus one detail file per release.

    The index (release table + diffs) is inlined as JS so the page opens even
    from ``file://``. The per-release item signatures — ~700 items x 21 releases,
    the bulk of the data — are separate JSON fetched only when a release is
    opened. That is what keeps the landing page small, and it maps exactly onto
    the click-to-expand flow.
    """
    target = path or (config.DASHBOARD_DATA_DIR / "releases.js")
    target.parent.mkdir(parents=True, exist_ok=True)

    detail = bundle.pop("_detail", {})
    detail_dir = target.parent / "releases"
    detail_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale files so a release that disappears does not linger and get
    # served as if it were current.
    for stale in detail_dir.glob("*.json"):
        stale.unlink()

    written = 0
    for (station, release), payload in detail.items():
        out = detail_dir / detail_name(station, release)
        out.write_text(json.dumps(payload, separators=(",", ":"), default=str),
                       encoding="utf-8")
        written += 1

    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli build` — do not edit.\n"
        "window.__FACTORY_RELEASES__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target, written
