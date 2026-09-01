"""Compile the run-level drill-down bundle behind ``runs.html``.

WHY A SEPARATE BUNDLE
---------------------
``stations.js`` is pre-aggregated by design (one row per day, per release, per
area) — that is what makes the station page small. But every number on that page
is a count of *runs*, and the first question a reader has about a number is
"which runs?". Answering it needs the individual rows, so they live here rather
than bloating a bundle whose whole point is that it is aggregated.

The page is reached by clicking any number, and its filter travels in the URL
hash, so a link to "MLT, release 220, failures only" is copy-pasteable.

FILTER SEMANTICS ARE THE DASHBOARD'S, NOT NEW ONES
--------------------------------------------------
A drill-down whose row count disagrees with the tile it came from is worse than
no drill-down, so the filters mirror ``daily.py`` exactly:

``status=abort``   ``status == "error"``. The line says abort; EOS says error.
``status=graded``  the ``daily.GRADED`` triple — pass, fail, error. Not skip or
                   unknown, which never produced a verdict.
``attempt=first``  ``attempt == 1``, the FPY numerator's population.
``day=``           ``daily.day_key`` — the factory-local calendar day, which is
                   why the day is precomputed here instead of in the browser.
``release=``       ``stations.release_of`` — likewise precomputed rather than
                   re-deriving the version regex in JS.

SIZE
----
Test cases are the bulk: ~134k rows across ~1.2k runs, but only ~760 distinct
test names, because every run of a suite repeats its suite's list. Interning the
names into ``testNames`` and storing indices takes the payload from ~5.9 MB to
~1.5 MB (~100 KB over the wire, gzipped), which is small enough to ship whole
and skip lazy per-run fetches — the drill-down opens instantly and works over
``file://``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config, daily, fetchstate, links, rootcause, stations

#: Test-case verdicts, interned to an index. Anything unrecognised becomes
#: ``unknown`` rather than being dropped — a status nobody has seen before is a
#: thing to notice, not to hide.
TEST_STATUSES: Tuple[str, ...] = ("pass", "fail", "error", "skip", "unknown")


def build_bundle(
    payload: Dict[str, Any], state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = payload.get("runs", [])
    tz_name = payload.get("timezone", config.timezone_name())

    names: Dict[str, int] = {}
    containers: set = set()
    rows = [_row(run, tz_name, names, containers) for run in runs]
    # Newest first: a reader who opens the table without a filter wants today.
    rows.sort(key=lambda row: row["t"] or 0, reverse=True)

    labels = {
        entry["key"]: entry["label"]
        for entry in (payload.get("stations") or stations.registry())
    }
    labels.setdefault(stations.UNCLASSIFIED, "Unclassified")
    labels.setdefault("__all__", "All stations")

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "collectedAt": payload.get("generatedAt"),
        "timezone": tz_name,
        "window": payload.get("window", {}),
        "source": payload.get("source", "eos-api"),
        "stationLabels": labels,
        "testStatuses": list(TEST_STATUSES),
        "testNames": list(names),
        # Indices into testNames that are parent nodes, not real tests. A
        # container "fails" only because something under it failed, so the
        # First fail column skips them — otherwise it reports `chip1` where the
        # actual signature is the leaf underneath. Same rule as the Pareto
        # (rootcause.is_container), applied once per name rather than per row.
        "containerNames": sorted(containers),
        "runs": rows,
        # The hand-reported figures, raw and with their asOf intact.
        #
        # WST and FT come from Sigurd by message and are typed into
        # weekly/external_yields.json. The weekly bundle already filters them to
        # the week they describe — see build_fpy._external_in, and the reason
        # there is a good one — but a page that lets a reader pick any range has
        # to apply that test itself, so it needs the date rather than the
        # verdict. Passed straight through; nothing here interprets them.
        "external": _external(),
        "stationOrder": [station["key"] for station in stations.registry()],
        "links": dict(links.describe(), **_controller_links(payload)),
        "fetch": fetchstate.summary(state or {}),
    }


def _controller_links(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Where a run can be opened, when the run came from the controllers.

    OCP Logs has no per-run URL, so the EOS view can only offer its search
    page. The controllers do: every run id here is exactly the id in a
    /suite_run/ path, and the slot rides on it after a #. Sending someone from
    the controller-sourced page to OCP's search box was making them look up, by
    hand, a run we already hold the address of.

    A template plus a station->host map rather than a URL per run: the map is
    eleven entries and the URLs would be one per run.
    """
    if payload.get("source") != "pega":
        return {}
    return {
        "pega": {
            "urlTemplate": "http://{host}:3000/suite_run/{run}?slot_number={slot}",
            "runTemplateNoSlot": "http://{host}:3000/suite_run/{run}",
            "hosts": {station.key: station.controller
                      for station in stations.STATIONS if station.controller},
            "note": "opens on the controller that ran it — ESVM login admin/admin",
        }
    }


def _row(
    run: Dict[str, Any], tz_name: str, names: Dict[str, int], containers: set
) -> Dict[str, Any]:
    """One run, with short keys — this is the widest structure in the bundle."""
    started = run.get("startTs")
    return {
        "i": run.get("runId"),
        "d": run.get("dutSerial"),
        "k": run.get("stationKey") or stations.UNCLASSIFIED,
        "l": run.get("level"),
        "su": run.get("suite"),
        "v": run.get("version"),
        "r": stations.release_of(run.get("version")),
        "day": daily.day_key(started, tz_name) if started else None,
        "t": started,
        "u": _int_or_none(run.get("durationSec")),
        "s": run.get("status") or "unknown",
        "a": run.get("attempt"),
        "T": [_test(test, names, containers) for test in run.get("tests") or []],
    }


def _external() -> Dict[str, Any]:
    """WST and FT as the file states them, or {} if it cannot be read."""
    from . import build_fpy

    try:
        return build_fpy.external()
    except Exception:                                     # noqa: BLE001
        return {}


def _test(test: Dict[str, Any], names: Dict[str, int], containers: set) -> List[Any]:
    name = test.get("name") or test.get("displayName") or "(unnamed)"
    if name not in names:
        names[name] = len(names)
        # The class name is the only reliable container marker, and it is not
        # carried in the row, so the check has to happen here while it is in hand.
        if rootcause.is_container(name, test.get("displayName")):
            containers.add(names[name])
    status = str(test.get("status") or "unknown").lower()
    if status not in TEST_STATUSES:
        status = "unknown"
    return [names[name], TEST_STATUSES.index(status), _int_or_none(test.get("durationSec"))]


def _int_or_none(value: Any) -> Optional[int]:
    """Seconds, rounded. Sub-second precision is noise in a table of test runs
    and costs bytes on every one of ~134k rows."""
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


#: The two keys that are the whole weight of the bundle. Measured on a live
#: 30-day build: ``testNames`` 5.06 MB across 135,476 entries and ``runs``
#: 3.51 MB across 5,348 — 99.8% of 8.59 MB between them. Everything else, the
#: station labels and orders and windows a page needs to draw its controls, is
#: about 16 KB.
HEAVY_KEYS = ("runs", "testNames")


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    """Write the full bundle, and a light companion beside it.

    The light one carries everything except :data:`HEAVY_KEYS`, with those left
    as empty arrays rather than dropped — a page that captures
    ``DATA.runs`` at load then holds a real array which the on-demand loader
    fills in place, so nothing downstream has to learn about two-phase data.

    Why bother: ``data/runs_pega.js`` is 9.5 MB, nginx serves it uncompressed,
    and over the VPN it arrives at ~42 KB/s — about four minutes during which a
    blocking script tag stops the parser and the page looks like it is missing
    half its features. The light bundle is ~16 KB, which is the difference
    between a page that draws at once and one that appears broken.
    """
    target = path or (config.DASHBOARD_DATA_DIR / "runs.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=_default)
    target.write_text(
        "// Generated by `python -m factory.cli build` — do not edit.\n"
        "window.__FACTORY_RUNS__ = {};\n".format(body),
        encoding="utf-8",
    )
    write_light_bundle(bundle, target)
    return target


def write_light_bundle(bundle: Dict[str, Any], full_path: Path) -> Path:
    """The controls-only companion to ``full_path``.

    Carries a ``full`` block naming the file the heavy keys live in and how big
    it is, so a loader can show a real progress bar and a time estimate before
    it starts rather than an indeterminate spinner.
    """
    light = {key: value for key, value in bundle.items() if key not in HEAVY_KEYS}
    for key in HEAVY_KEYS:
        light[key] = []
    light["full"] = {
        "path": full_path.name,
        "bytes": full_path.stat().st_size if full_path.exists() else 0,
        "counts": {
            key: len(bundle.get(key) or []) for key in HEAVY_KEYS
        },
        "keys": list(HEAVY_KEYS),
    }
    target = full_path.with_name(full_path.stem + "_light.js")
    body = json.dumps(light, separators=(",", ":"), default=_default)
    target.write_text(
        "// Generated by `python -m factory.cli build` — do not edit.\n"
        "// Controls-only companion to {}; the heavy keys arrive on demand.\n"
        "window.__FACTORY_RUNS__ = {};\n".format(full_path.name, body),
        encoding="utf-8",
    )
    return target


def _default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    return str(value)
