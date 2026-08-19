"""The weekly tracker: a summary of every week, and every week in full.

WHY WEEKS AND NOT "THE LAST SEVEN DAYS"
---------------------------------------
A rolling window straddles two working weeks, so on a Saturday it half-covers
the week being discussed and half the one before. A week here runs **Monday to
Sunday**, which is the week the line actually plans in, and the current week is
Monday to today. Two people comparing "last week" then mean the same days.

WHAT IS IN IT
-------------
Per week, per test step: how many units, how many runs, the first-pass yield,
the yield after retest, and the share of units that had to be run again. Below
:data:`build_fpy.MIN_COHORT` first-time units no yield is published at all —
the counts are, because a 0.0% over two chassis is not a yield and printing one
invites somebody to quote it.

And, per week, the rows behind those numbers: every unit, its serial, the
software release it ran, its verdict and a link into the controller that has
the log. That table is the point of the page — a yield nobody can check is a
yield nobody believes, and the argument about MLT 225 was settled by exactly
this list.

WHAT IS LEFT OUT, DELIBERATELY
------------------------------
VBB provisioning. It is a real stage and it is on the station page, but it is
not part of the product test flow the line reviews, and a provisioning step
sitting between FT and MLT in a yield table invites the wrong comparison.

WST and FT are not here at all: they are Sigurd's and arrive by Slack. The
summary carries a slot for them per week so the number has somewhere to live
once it is asked for.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import build_fpy, build_stations, config, daily, pega, stations, version

#: Weeks published. A quarter, which is as far back as the controllers' detail
#: goes once the archive under weekly/ is doing its job.
DEFAULT_WEEKS = 12

#: How many recent weeks carry their unit-level rows. The rows are the bulk of
#: the bundle — 573 of them in one week — and nobody cross-checks a number from
#: two months ago against a controller that no longer holds the run.
DETAIL_WEEKS = 4

#: Not part of the product test flow being reviewed. See the module docstring.
EXCLUDE = ("vbb_provision",)

#: Which controller serves a station's links.
CONTROLLER = {station.key: station.controller or "pega3"
              for station in stations.STATIONS}


def week_start(day: date) -> date:
    """The Monday of the week ``day`` falls in."""
    return day - timedelta(days=day.weekday())


def week_label(monday: date) -> str:
    """ISO week, as people write it: 2026-W33."""
    year, week, _weekday = monday.isocalendar()
    return "{}-W{:02d}".format(year, week)


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def build_bundle(payload: Dict[str, Any], weeks: int = DEFAULT_WEEKS) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    this_monday = week_start(today)

    out: List[Dict[str, Any]] = []
    for back in range(weeks):
        monday = this_monday - timedelta(days=7 * back)
        sunday = monday + timedelta(days=6)
        # The current week ends today, not on a Sunday that has not happened.
        end = min(sunday, today)
        week = _week(payload, monday, end, sunday, today,
                     detail=back < DETAIL_WEEKS)
        if week["rows"] or week["units"]:
            out.append(week)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "source": payload.get("dataSource") or {},
        "minCohort": build_fpy.MIN_COHORT,
        "excluded": list(EXCLUDE),
        "historyDays": build_fpy.HISTORY_DAYS,
        "weeks": out,
    }


def _week(payload: Dict[str, Any], monday: date, end: date, sunday: date,
          today: date, detail: bool = True) -> Dict[str, Any]:
    start_s, end_s = monday.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    inner = build_fpy.build_bundle(payload, start=start_s, end=end_s,
                                   exclude=EXCLUDE)
    return {
        "week": week_label(monday),
        "from": start_s,
        "to": end_s,
        "endsOn": sunday.strftime("%Y-%m-%d"),
        # Still running. Judged on the week not having ended rather than on
        # end < sunday: the day boundary here is UTC, so at 17:00 Pacific on a
        # Saturday "today" is already Sunday and the week would otherwise be
        # marked complete a day early.
        "partial": today <= sunday,
        "rows": inner["rows"],
        "totals": inner["totals"],
        "external": inner["external"],
        "hasDetail": detail,
        "units": _unit_rows(payload, start_s, end_s) if detail else [],
        # The three charts the station page draws, frozen to this week.
        "charts": _charts(payload, start_s, end_s) if detail else None,
    }


def _charts(payload: Dict[str, Any], start: str, end: str) -> Optional[Dict[str, Any]]:
    """Pass/fail by day, yield by release and the failure Pareto, for this week
    alone.

    WHY THE STATION PAGE'S OWN AGGREGATION, NOT A SECOND ONE
    ``build_stations._view`` already turns a list of runs into exactly these
    three shapes, and the shared chart code already draws them. Writing a
    weekly variant would be a second answer to "what is first-pass yield" and a
    second place for a hollow-marker rule to drift. The only difference here is
    which runs go in: Monday to Sunday of this week, and nothing else.

    Frozen is the point. The station page's charts move with a rolling window,
    so last week's page would quietly re-render as this week's data arrived and
    a figure quoted on Monday would not be there on Friday. A week is a closed
    period; these are the runs that fell inside it.
    """
    tz_name = ("UTC" if payload.get("source") == "pega"
               else payload.get("timezone", config.timezone_name()))
    per_unit = payload.get("source") == "pega"
    runs = [run for run in payload.get("runs") or []
            if run.get("startTs")
            and start <= daily.day_key(run["startTs"], tz_name) <= end]
    if not runs:
        return None

    # The unclassified tail and the engineering runs are excluded here for the
    # same reason the station page excludes them from "All stations": neither
    # is a line stage, and letting them into a weekly yield would move it
    # without anything on the line having changed.
    off_line = (stations.UNCLASSIFIED, stations.ENGINEERING)
    classified = [run for run in runs
                  if (run.get("stationKey") or stations.UNCLASSIFIED) not in off_line]

    view = build_stations._view(classified, tz_name, per_unit, tz_name)
    return {
        "daily": view["daily"],
        "releases": view["releases"],
        "pareto": view["pareto"],
        "firstFailure": view["firstFailure"],
        "runs": len(classified),
    }


def _unit_rows(payload: Dict[str, Any], start: str, end: str) -> List[Dict[str, Any]]:
    """Every unit run in the window: serial, release, verdict, and the log.

    One row per unit per station per attempt, which is the granularity someone
    checking a number needs — "MLT says 65%" is answerable only by looking at
    the units it counted.
    """
    rows: List[Dict[str, Any]] = []
    attempts: Dict[tuple, int] = defaultdict(int)

    for run in sorted((r for r in payload.get("runs", [])
                       if r.get("startTs") and r.get("stationKey")
                       and r.get("dutSerial")),
                      key=lambda r: r["startTs"]):
        station = run["stationKey"]
        if station in EXCLUDE or station in (stations.ENGINEERING,
                                             stations.UNCLASSIFIED):
            continue
        key = (station, run["dutSerial"])
        attempts[key] += 1
        day = _day(run["startTs"])
        if not (start <= day <= end):
            continue

        rows.append({
            "day": day,
            "station": station,
            "dut": run["dutSerial"],
            "release": run.get("suite") or "",
            "status": run.get("status") or "unknown",
            "attempt": attempts[key],
            "failures": _failures(run),
            "url": _link(run, CONTROLLER.get(station, "pega3")),
            "controller": CONTROLLER.get(station, "pega3"),
        })

    rows.sort(key=lambda row: (row["day"], row["station"], row["dut"]))
    return rows


def _failures(run: Dict[str, Any]) -> List[str]:
    from . import rootcause

    names: List[str] = []
    for failure in run.get("failures") or []:
        name = failure.get("display") or failure.get("test")
        if not name or name in names:
            continue
        if rootcause.is_container(failure.get("display"), failure.get("test")):
            continue
        names.append(name)
    return names


def _link(run: Dict[str, Any], host: str) -> Optional[str]:
    run_id = run.get("runId") or ""
    if "#slot" in run_id:
        base, _, slot = run_id.partition("#slot")
        try:
            return pega.run_url(base, int(slot), host=host)
        except ValueError:
            return pega.run_url(base, None, host=host)
    return pega.run_url(run_id, None, host=host) if run_id else None


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "weekly.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli weekly` — do not edit.\n"
        "window.__FACTORY_WEEKLY__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target
