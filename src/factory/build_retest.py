"""Retests, split out from new builds — the line's own "Retest" tab, rebuilt.

WHY THIS IS A SEPARATE PAGE
---------------------------
The daily tracker shows one row per unit with the latest attempt winning, so a
unit that failed at 09:00 and passed at 14:00 appears once, as a pass. That is
the right shape for "what is the state of the line today" and the wrong shape
for the question the field report asks: how did the *new* units do, and
separately, how did the units we were re-running do?

Combining them flatters the day. A shift that starts twenty fresh modules and
re-runs fifteen known-bad ones has two yields, and the average of them
describes neither.

THE FORMAT IS THE LINE'S
------------------------
Laid out like the workbook's ``08-13 Retest`` tab: the original attempt on the
left — result, failing test case, link — and the retest on the right, for MLT
and HTT on one row per unit. That tab is what the line already reads in its
reviews, and a page that rearranges it makes two people compare two shapes.

WHAT COUNTS AS A RETEST
-----------------------
A unit with more than one graded run at a station inside the window. The window
is seven days and the attempts are numbered inside it, which is stated on the
page: a unit first tested eight days ago and re-run today is a first attempt
here, and calling it anything else would need history the reader cannot see.

Every build is included — production, validation and debug alike — because the
tracker includes them and this page must reconcile with the tracker. Each
attempt carries the build it ran, so release-only is a filter rather than a
different page.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import build_dailyexcel, config, pega, version

#: Days reported. The same seven the station page and the weekly tracker use.
DEFAULT_DAYS = 7

#: The two module stations, in the order a unit meets them.
STATIONS = (("mlt", "MLT"), ("htt", "HTT"))

GRADED = ("pass", "fail")


def collect(days: int = DEFAULT_DAYS) -> Dict[str, Any]:
    """Every attempt each unit made at MLT and HTT inside the window.

    Walked straight from pega3 rather than through ``pega_collect``, which
    drops validation and debug builds: the tracker keeps them and this page
    has to agree with the tracker. The build is carried on every attempt so a
    reader can tell them apart.
    """
    today = datetime.now(timezone.utc).date()
    window = [(today - timedelta(days=offset)).strftime("%Y-%m-%d")
              for offset in range(days - 1, -1, -1)]

    attempts: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list))
    parts: Dict[str, str] = {}
    runs_seen = 0

    for day in window:
        try:
            listing = pega.day_suite_runs(day)
        except pega.PegaUnavailable:
            continue
        for entry in listing:
            run_id = entry.get("suite_run_id") or ""
            suite = entry.get("suite_name") or ""
            station = build_dailyexcel.station_of(run_id, suite)
            if not station:
                continue
            # Same exclusions as the tracker: dry runs, smoke tests, an
            # engineer's branch. Validation and debug builds are kept.
            if (build_dailyexcel.ENGINEERING.search(run_id)
                    or build_dailyexcel.ENGINEERING.search(suite)):
                continue
            try:
                detail = pega.suite_run(run_id)
            except pega.PegaUnavailable:
                continue
            runs_seen += 1
            started = entry.get("start_time") or ""
            for part in pega.participants(detail):
                dut = part["dut"]
                if entry.get("dut_part_number"):
                    parts.setdefault(dut, entry["dut_part_number"])
                attempts[dut][station].append({
                    "day": day,
                    "started": started,
                    "status": part["status"],
                    "suite": suite,
                    "failures": build_dailyexcel._unit_failures(detail, part["slot"]),
                    "url": pega.run_url(run_id, part["slot"]),
                    "short": run_id.rsplit("_run_", 1)[-1],
                })

    for dut in attempts:
        for station in attempts[dut]:
            attempts[dut][station].sort(key=lambda a: a["started"])

    return {"window": window, "attempts": attempts, "parts": parts,
            "runs": runs_seen}


def build_bundle(collected: Dict[str, Any]) -> Dict[str, Any]:
    window = collected["window"]
    attempts = collected["attempts"]

    rows: List[Dict[str, Any]] = []
    for dut in sorted(attempts):
        by_station = attempts[dut]
        retested = {station for station, _label in STATIONS
                    if len([a for a in by_station.get(station, [])
                            if a["status"] in GRADED]) > 1}
        if not retested:
            continue

        row: Dict[str, Any] = {
            "dut": dut,
            "pn": collected["parts"].get(dut, ""),
            "day": min(a["day"] for runs in by_station.values() for a in runs),
            "retested": sorted(retested),
            "attempts": {},
        }
        for station, _label in STATIONS:
            graded = [a for a in by_station.get(station, [])
                      if a["status"] in GRADED]
            if not graded:
                continue
            row["attempts"][station] = {
                "first": graded[0],
                "last": graded[-1],
                "count": len(graded),
                # Recovered: failed the first time and passed in the end. The
                # number the retest column exists to produce.
                "recovered": (graded[0]["status"] == "fail"
                              and graded[-1]["status"] == "pass"),
                "stillFailing": graded[-1]["status"] == "fail",
            }
        rows.append(row)

    rows.sort(key=lambda r: (r["day"], r["dut"]))

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "window": {"from": window[0], "to": window[-1], "days": len(window)},
        "source": {
            "label": "pega3 (ESVM)",
            "note": "every attempt each unit made, straight from the "
                    "controller — validation and debug builds included, "
                    "named on each attempt",
        },
        "split": _split(attempts),
        "rows": rows,
        "runs": collected["runs"],
    }


def _split(attempts: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> Dict[str, Any]:
    """New builds against retests, per station.

    The whole point of the page. A shift that starts twenty fresh modules and
    re-runs fifteen known-bad ones has two yields, and the average of them
    describes neither — which is why the field report splits them and the
    daily tracker, which shows one row per unit, cannot.
    """
    out: Dict[str, Any] = {}
    for station, label in STATIONS:
        fresh_pass = fresh = again = again_pass = recovered = 0
        for by_station in attempts.values():
            graded = [a for a in by_station.get(station, [])
                      if a["status"] in GRADED]
            if not graded:
                continue
            fresh += 1
            if graded[0]["status"] == "pass":
                fresh_pass += 1
            if len(graded) > 1:
                again += 1
                if graded[-1]["status"] == "pass":
                    again_pass += 1
                if graded[0]["status"] == "fail" and graded[-1]["status"] == "pass":
                    recovered += 1
        out[station] = {
            "label": label,
            # "New input": every unit's first attempt in the window, which is
            # the population a first-pass yield is about.
            "units": fresh,
            "firstPass": fresh_pass,
            "firstPassRate": (fresh_pass / fresh) if fresh else None,
            # Retested: units that came back at least once.
            "retested": again,
            "retestRate": (again / fresh) if fresh else None,
            "retestPassed": again_pass,
            "retestPassRate": (again_pass / again) if again else None,
            "recovered": recovered,
        }
    return out


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "retest.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli retest` — do not edit.\n"
        "window.__FACTORY_RETEST__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target
