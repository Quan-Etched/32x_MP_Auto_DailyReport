"""New build or retest — which units are seeing a suite for the first time.

THE QUESTION THIS ANSWERS
------------------------
When a suite is released to fix something, "it passes now" is only evidence if
the units it passed on are not the units it was developed against. That is
exactly what was asked of the mlt_2026.225 validation: 24 units went through it,
8 of them the debug set that the fix was written on, and the interesting number
is how the other 16 did.

No page could answer it, because nothing said which units were new. This does:
every run is marked as a **new build** (the first time that unit has been
through that station in the window) or a **retest**, and a retest carries what
happened last time.

WHY "NEW" IS WINDOW-RELATIVE, AND WHY THAT IS SAID OUT LOUD
------------------------------------------------------------
A unit is called new when it has not been seen at that station inside the
collected window. Widen the window and some of today's new builds become
retests. That is the same caveat first-pass yield carries in docs/metrics.md,
and it matters more here: a unit built months ago and retested today looks new
if the window is short. The page prints the window it used.

The stronger signal is on the retests, and it is not window-relative in the same
way: if a unit failed here before, that failure is a fact regardless of how far
back we looked.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, pega, stations, version

#: Days of history to publish. Long enough to hold a validation campaign and
#: the batch it is being compared against.
DEFAULT_DAYS = 14

NEW = "new"
RETEST_AFTER_FAIL = "retest-fail"
RETEST_AFTER_PASS = "retest-pass"


def _day_of(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _failure_names(run: Dict[str, Any]) -> List[str]:
    """The distinct test classes that failed, in the order they ran."""
    names: List[str] = []
    for failure in run.get("failures") or []:
        name = failure.get("display") or failure.get("test")
        if name and name not in names:
            names.append(name)
    return names


def _link(run: Dict[str, Any], host: str) -> Optional[str]:
    """Back to the controller's own page for the run, slot included."""
    run_id = run.get("runId") or ""
    if "#slot" in run_id:
        base, _, slot = run_id.partition("#slot")
        try:
            return pega.run_url(base, int(slot), host=host)
        except ValueError:
            return pega.run_url(base, None, host=host)
    return pega.run_url(run_id, None, host=host) if run_id else None


#: Which controller serves a station's links.
CONTROLLER = {station.key: station.controller or "pega3"
              for station in stations.STATIONS}


def build_bundle(payload: Dict[str, Any], days: int = DEFAULT_DAYS) -> Dict[str, Any]:
    runs = sorted((run for run in payload.get("runs", []) if run.get("startTs")),
                  key=lambda run: run["startTs"])

    labels = {entry["key"]: entry.get("label", entry["key"])
              for entry in (payload.get("stations") or [])}

    # Walk the whole window in time order so a run's history is everything that
    # came before it, then publish only the tail. A unit's first appearance is
    # only "first" relative to what was looked at.
    history: Dict[tuple, List[Dict[str, Any]]] = {}
    marked: List[Dict[str, Any]] = []

    for run in runs:
        station = run.get("stationKey")
        dut = (run.get("dutSerial") or "").strip()
        if not station or not dut or station in (stations.ENGINEERING,
                                                 stations.UNCLASSIFIED):
            continue
        key = (station, dut)
        prior = history.get(key) or []

        if not prior:
            kind = NEW
        else:
            last = prior[-1]
            kind = (RETEST_AFTER_FAIL if last["status"] in ("fail", "error")
                    else RETEST_AFTER_PASS)

        entry = {
            "day": _day_of(run.get("startTs")),
            "ts": run.get("startTs"),
            "dut": dut,
            "station": station,
            "stationLabel": labels.get(station, station),
            "kind": kind,
            "attempt": len(prior) + 1,
            "status": run.get("status") or "unknown",
            "failures": _failure_names(run),
            "suite": run.get("suite"),
            # What happened last time, which is the whole reason a retest is
            # interesting: a unit that previously failed the thing a release
            # claims to fix is the unit worth watching.
            "priorStatus": prior[-1]["status"] if prior else None,
            "priorFailures": prior[-1]["failures"] if prior else [],
            "url": _link(run, CONTROLLER.get(station, "pega3")),
        }
        marked.append(entry)
        history.setdefault(key, []).append(
            {"status": entry["status"], "failures": entry["failures"]})

    days_present = sorted({entry["day"] for entry in marked if entry["day"]})
    keep = set(days_present[-days:]) if days_present else set()
    rows = [entry for entry in marked if entry["day"] in keep]
    rows.sort(key=lambda entry: (entry["ts"] or 0), reverse=True)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "window": payload.get("window", {}),
        "publishedDays": sorted(keep),
        "source": payload.get("dataSource") or {},
        "counts": _counts(rows),
        "stations": [
            {"key": key, "label": labels.get(key, key),
             "runs": sum(1 for row in rows if row["station"] == key)}
            for key in sorted({row["station"] for row in rows},
                              key=lambda k: labels.get(k, k))
        ],
        "rows": rows,
    }


def _counts(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rate(subset: List[Dict[str, Any]]) -> Optional[float]:
        graded = [row for row in subset if row["status"] in ("pass", "fail", "error")]
        if not graded:
            return None
        return sum(1 for row in graded if row["status"] == "pass") / len(graded)

    new = [row for row in rows if row["kind"] == NEW]
    after_fail = [row for row in rows if row["kind"] == RETEST_AFTER_FAIL]
    after_pass = [row for row in rows if row["kind"] == RETEST_AFTER_PASS]
    return {
        "runs": len(rows),
        "units": len({(row["station"], row["dut"]) for row in rows}),
        "new": {"runs": len(new), "rate": rate(new)},
        "retestAfterFail": {"runs": len(after_fail), "rate": rate(after_fail)},
        "retestAfterPass": {"runs": len(after_pass), "rate": rate(after_pass)},
    }


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "builds.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli builds` — do not edit.\n"
        "window.__FACTORY_BUILDS__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target
