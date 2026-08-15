"""End-to-end first-pass yield, one row per test step.

WHAT THIS ANSWERS
-----------------
"How is the line doing" asked once, across every stage a unit passes through,
in the one number a factory actually runs on: **first-pass yield** — of the
units that reached a stage for the first time, how many passed on that first
attempt.

Everything else on this dashboard is per-station and 30 days. This is the whole
line over the last seven days, on one page, which is what a weekly meeting can
hold.

WHY FPY AND NOT THE PASS RATE
-----------------------------
The station page's pass rate counts runs. A unit that fails, is retested and
passes contributes one failure and one pass, and the stage looks 50%. FPY
counts *units on their first attempt*, so that unit is one failure — and the
gap between the two numbers is the retest load, which is the cost the line
actually pays. Both are published here, side by side, precisely so the gap is
visible rather than argued about.

THE COHORT MATTERS AND IS STATED
--------------------------------
"First attempt" is only meaningful if we can see the attempt. FPY here counts
units whose *first ever run at that stage inside the collected history* falls
in the reported window; a unit that first ran three weeks ago and came back
this week is a retest, not a first pass, and is excluded from the FPY
denominator while still counting in the final yield. The history is 30 days, so
a unit built before that could be miscounted as new — the page prints the
window it used.

WHAT IS NOT MEASURED HERE
-------------------------
WST, FT and SLT happen at Sigurd, in systems this repo does not collect (see
stations.py). Their numbers are carried as declared values with a named source
and an as-of date, and rendered differently from the measured ones, because a
figure someone typed in and a figure computed from 1704 runs should never look
alike on a slide.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, rootcause, stations, version

#: Days reported. A week: long enough to smooth a bad shift, short enough that
#: a fix landed on Tuesday still shows.
DEFAULT_DAYS = 7

#: Days of history walked to decide whether a unit is new to a stage. Longer
#: than the reported window on purpose — see the module docstring.
HISTORY_DAYS = 30

GRADED = ("pass", "fail", "error")

#: Stages measured elsewhere, carried so the chart is the whole line rather
#: than the part we happen to collect. Hand-entered, which is why every one
#: names who reported it and when — and why the page marks them.
EXTERNAL: Dict[str, Dict[str, Any]] = {
    "wst": {
        "yield": 0.353,
        "source": "Sigurd, reported in #production-test-eng",
        "asOf": "2026-08-14",
        "note": "Wafer sort. Reported figure — not collected by this pipeline.",
    },
    "ft": {
        "yield": 0.843,
        "source": "Sigurd, reported in #production-test-eng",
        "asOf": "2026-08-14",
        "note": "Final test. Reported figure — not collected by this pipeline.",
    },
}

#: Stations whose repeat runs are a *sequence*, not a retest. VBB provisioning
#: puts every board through eight suites (PROD_01_vbb_provisioning,
#: PROD_02_vbb_validate…, flash_and_lockdown_bootloader and five more), all
#: mapped to one station — so counting units with more than one run gives a
#: 100% retest rate for a stage that retests almost nothing.
MULTI_SUITE = ("vbb_provision",)


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def build_bundle(payload: Dict[str, Any], days: int = DEFAULT_DAYS) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    runs = sorted(
        (run for run in payload.get("runs", [])
         if run.get("startTs") and run.get("stationKey") and run.get("dutSerial")
         and run.get("status") in GRADED),
        key=lambda run: run["startTs"])

    history: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        history[(run["stationKey"], run["dutSerial"])].append(run)

    registry = {entry["key"]: entry for entry in stations.registry()}
    rows: List[Dict[str, Any]] = []

    for key in sorted({station for station, _dut in history},
                      key=lambda k: registry.get(k, {}).get("order", 999)):
        units = {dut: rs for (station, dut), rs in history.items() if station == key}
        window = {dut: [r for r in rs if _day(r["startTs"]) >= start]
                  for dut, rs in units.items()}
        window = {dut: rs for dut, rs in window.items() if rs}
        if not window:
            continue

        # New to this stage: its very first run in the collected history landed
        # inside the window. These are the only units an FPY can be asked of.
        fresh = [dut for dut in window if _day(units[dut][0]["startTs"]) >= start]
        first_pass = sum(1 for dut in fresh if units[dut][0]["status"] == "pass")
        passed = sum(1 for rs in window.values()
                     if any(r["status"] == "pass" for r in rs))
        repeats = sum(1 for rs in window.values() if len(rs) > 1)

        rows.append({
            "key": key,
            "label": registry.get(key, {}).get("label", key),
            "controller": registry.get(key, {}).get("controller"),
            "units": len(window),
            "runs": sum(len(rs) for rs in window.values()),
            "newUnits": len(fresh),
            "fpy": (first_pass / len(fresh)) if fresh else None,
            "finalYield": passed / len(window),
            # Retest load: units that needed more than one run this week. Left
            # out where repeat runs are a provisioning sequence rather than a
            # second attempt at the same test.
            "retestRatio": None if key in MULTI_SUITE else repeats / len(window),
            "retestUnits": None if key in MULTI_SUITE else repeats,
            "retestNote": ("repeat runs here are a provisioning sequence, not "
                           "retests") if key in MULTI_SUITE else None,
            "topFailures": _top_failures(
                [r for rs in window.values() for r in rs]),
            "measured": True,
        })

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "window": {"from": start, "to": end, "days": days},
        "historyDays": HISTORY_DAYS,
        "source": payload.get("dataSource") or {},
        "rows": rows,
        "external": [
            dict(EXTERNAL[key], key=key,
                 label=registry.get(key, {}).get("label", key.upper()),
                 measured=False)
            for key in ("wst", "ft") if key in EXTERNAL
        ],
        "totals": _totals(rows),
    }


def _top_failures(runs: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """What actually failed, leaves only.

    Containers are dropped for the same reason they are everywhere else here:
    a nest fails because a leaf under it did, so it tops every list and names
    nothing.
    """
    counts: Dict[str, int] = defaultdict(int)
    for run in runs:
        if run.get("status") == "pass":
            continue
        for failure in run.get("failures") or []:
            name = failure.get("display") or failure.get("test")
            if not name or rootcause.is_container(failure.get("display"),
                                                  failure.get("test")):
                continue
            counts[name] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"name": name, "runs": n, "area": rootcause.area(name)}
            for name, n in ranked]


#: Below this many first-time units, a stage's FPY is a coin toss with a
#: decimal point on it and must not enter the rolled figure. L10 SFT ran one
#: unit this week; multiplying by its 0% would report the whole line at 0%,
#: which is arithmetically correct and completely false.
MIN_COHORT = 20


def _totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    graded = [row for row in rows if row["fpy"] is not None]
    counted = [row for row in graded if row["newUnits"] >= MIN_COHORT]
    thin = [row for row in rows if row["newUnits"] < MIN_COHORT]
    return {
        "stations": len(rows),
        "units": sum(row["units"] for row in rows),
        "runs": sum(row["runs"] for row in rows),
        # Rolled through: the probability a unit clears every measured stage
        # first time. A product, because that is what it is — and the number
        # nobody had computed for this line.
        "rolledFpy": _product([row["fpy"] for row in counted]) if counted else None,
        "rolledOver": [row["label"] for row in counted],
        # Named, not hidden. That these stages are too thin to roll is itself
        # the readiness finding, and burying it would make the headline look
        # like whole-line coverage.
        "excludedThin": [{"label": row["label"], "newUnits": row["newUnits"],
                          "units": row["units"]} for row in thin],
        "minCohort": MIN_COHORT,
    }


def _product(values: List[float]) -> float:
    out = 1.0
    for value in values:
        out *= value
    return out


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "fpy.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli fpy` — do not edit.\n"
        "window.__FACTORY_FPY__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target
