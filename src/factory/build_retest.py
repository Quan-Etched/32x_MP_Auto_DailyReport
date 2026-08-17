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

#: Where the trace starts.
#:
#: 2026-08-07, not a rolling seven days — the workbook's retest tab starts
#: there ("08-17 Retest with 225-226", whose first rows are dated 08-07), and a
#: retest trace that begins after a unit's first failure shows the retest and
#: hides what it was retesting. The window runs from here to today, so it
#: lengthens rather than sliding.
WINDOW_START = "2026-08-07"

#: The two module stations, in the order a unit meets them.
STATIONS = (("mlt", "MLT"), ("htt", "HTT"))

GRADED = ("pass", "fail")


def collect(start: str = WINDOW_START, end: Optional[str] = None) -> Dict[str, Any]:
    """Every attempt each unit made at MLT and HTT inside the window.

    Walked straight from pega3 rather than through ``pega_collect``, which
    drops validation and debug builds: the tracker keeps them and this page
    has to agree with the tracker. The build is carried on every attempt so a
    reader can tell them apart.
    """
    first = datetime.strptime(start, "%Y-%m-%d").date()
    last = (datetime.strptime(end, "%Y-%m-%d").date() if end
            else datetime.now(timezone.utc).date())
    window = [(first + timedelta(days=offset)).strftime("%Y-%m-%d")
              for offset in range((last - first).days + 1)]

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

    # One row per unit *per station*, carrying every attempt rather than just
    # the first and the last. Sixteen columns of first-and-last was the
    # workbook's shape and it does not survive a unit that was re-run four
    # times across three builds — which is most of them here.
    rows: List[Dict[str, Any]] = []
    for dut in sorted(attempts):
        for station, label in STATIONS:
            graded = [a for a in attempts[dut].get(station, [])
                      if a["status"] in GRADED]
            if len(graded) < 2:
                continue
            builds = []
            for a in graded:
                if a["suite"] not in builds:
                    builds.append(a["suite"])
            rows.append({
                "dut": dut,
                "pn": collected["parts"].get(dut, ""),
                "station": station,
                "stationLabel": label,
                "day": graded[0]["day"],
                "lastDay": graded[-1]["day"],
                "count": len(graded),
                "attempts": [_attempt(a) for a in graded],
                "firstBuild": graded[0]["suite"],
                "lastBuild": graded[-1]["suite"],
                "firstBuildShort": short_build(graded[0]["suite"]),
                "lastBuildShort": short_build(graded[-1]["suite"]),
                # Re-run against a different build is a different event from
                # re-run against the same one: the first is a fix being tried,
                # the second is a flake being chased.
                "builds": builds,
                "crossedBuild": len(builds) > 1,
                "recovered": (graded[0]["status"] == "fail"
                              and graded[-1]["status"] == "pass"),
                "stillFailing": graded[-1]["status"] == "fail",
                "outcome": ("Recovered"
                            if graded[0]["status"] == "fail"
                            and graded[-1]["status"] == "pass"
                            else "Still failing"
                            if graded[-1]["status"] == "fail"
                            else "Passed throughout"),
            })

    rows.sort(key=lambda r: (r["day"], r["dut"], r["station"]))

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "window": {"from": window[0], "to": window[-1], "days": len(window),
                   "anchored": WINDOW_START},
        "source": {
            "label": "pega3 (ESVM)",
            "note": "every attempt each unit made, straight from the "
                    "controller — validation and debug builds included, "
                    "named on each attempt",
        },
        "split": _split(attempts),
        # No pre-aggregated diagram: it has to follow the page's filter, and
        # shipping one here as well would be a second implementation of the
        # same five lines, free to disagree with the one on screen.
        "rows": rows,
        "runs": collected["runs"],
    }


def _attempt(a: Dict[str, Any]) -> Dict[str, Any]:
    return {"day": a["day"], "status": a["status"], "suite": a["suite"],
            "build": short_build(a["suite"]), "short": a["short"],
            "url": a["url"], "failures": a["failures"]}


def short_build(suite: str) -> str:
    """``mlt_validation_2026.225.0-gitb937ca2c`` -> ``225 validation``.

    The station prefix repeats on every node and the commit is nine characters
    of noise on a diagram; the release number and whether it is a validation
    build are what distinguishes one from another.
    """
    name = suite or ""
    release = ""
    for chunk in name.split("_"):
        if chunk[:5].replace(".", "").isdigit() and "." in chunk:
            release = chunk.split(".")[1] if chunk.count(".") >= 1 else chunk
            break
    marks = []
    lowered = name.lower()
    if "validation" in lowered:
        marks.append("validation")
    if "debug" in lowered:
        marks.append("debug")
    return " ".join([release or name] + marks).strip()


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
