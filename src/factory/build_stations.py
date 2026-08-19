"""Compile the per-station views into the stations dashboard bundle.

Unlike the hourly page, this one ships **pre-aggregated** data. The four views
(daily yield, release yield, Pareto, retest) are computed per station in Python
so the browser does not re-implement the definitions a second time — the station
selector switches between prepared slices rather than re-aggregating.

The retest *detail* table is capped; everything else is small by construction
(one row per day, per release, per area).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import chips, config, daily, fetchstate, stations

#: The EOS API is what OCP Logs reads: the same records, the same run ids. A
#: reader who wants to look one up goes to OCP, so that is what the page links.
DEFAULT_SOURCE = {
    "label": "OCP Logs",
    "url": "https://ocplogs.core.etched.com",
    "note": "via the EOS API — one run per fixture",
}

#: Units listed in the retest table. The counts above it always cover every
#: unit; only the row list is capped.
RETEST_DETAIL_LIMIT = 60


#: How much of the collected history the station page reports.
#:
#: Seven days, not thirty. The pages are read to answer "how is the line doing
#: this week", and a month-long average hides the week inside it — a release
#: that landed on Tuesday is a fifth of a 30-day bar and all of a 7-day one.
#: Collection still keeps 30 days: the weekly page needs them to tell a unit's
#: first attempt from its fourth, and trimming at collection time would break
#: that. Trimmed here instead, at the point of reporting.
WINDOW_DAYS = 7

#: The other range the page offers: everything since the line started.
#:
#: A floor date rather than "all of it". The controllers keep ninety days and
#: the earliest of those are bring-up — pega3's first module runs are 08-01, and
#: what sits behind that is a fortnight of a line being built. A range labelled
#: "All" that reached into it would put commissioning into the same bar as
#: production and answer a question nobody asked.
#:
#: Seven days stays the default, for the reason above: the page is read to
#: answer "how is the line doing this week", and a month-long average hides the
#: week inside it. The wider range is there for the question the default cannot
#: answer — whether this week is better or worse than the last three.
RANGE_FLOOR = "2026-08-01"

#: What the page's range control offers. Emitted rather than written into the
#: script so the floor above and the label a reader sees cannot drift apart.
RANGES = [
    {"key": "7d", "label": "7 days", "note": "default"},
    {"key": "all", "label": "All", "note": "since " + RANGE_FLOOR},
]


def _trim(runs: List[Dict[str, Any]], tz_name: str,
          days: int = WINDOW_DAYS) -> List[Dict[str, Any]]:
    if not days:
        return runs
    seen = sorted({daily.day_key(r["startTs"], tz_name)
                   for r in runs if r.get("startTs")})
    if len(seen) <= days:
        return runs
    # Anchored on the newest day *with data* rather than on today, so a quiet
    # weekend does not empty the page.
    cutoff = seen[-days]
    return [r for r in runs
            if r.get("startTs") and daily.day_key(r["startTs"], tz_name) >= cutoff]


def build_bundle(
    payload: Dict[str, Any], state: Optional[Dict[str, Any]] = None,
    window_days: int = WINDOW_DAYS,
) -> Dict[str, Any]:
    tz_name = payload.get("timezone", config.timezone_name())
    runs: List[Dict[str, Any]] = _trim(
        payload.get("runs", []),
        "UTC" if payload.get("source") == "pega" else tz_name,
        window_days)
    # The controllers are the tracker's source, so the tracker's definition of a
    # day wins on that side — both what a day *contains* (one row per unit,
    # last attempt) and where a day *starts*. The tracker cuts days in UTC,
    # reconciled against the line's own sheet: a unit tested at 17:30 Pacific on
    # 08-11 carries a runId stamped 20260812_0030 and the sheet files it under
    # 08-12. Bucketing this page in Pacific put the same units a day earlier and
    # made every row disagree.
    #
    # EOS is one row per fixture and has no tracker to agree with, so it is left
    # counting runs on the factory-local day.
    per_unit = payload.get("source") == "pega"
    day_tz = "UTC" if per_unit else tz_name
    by_station = daily.split_by_station(runs)
    level_errors = payload.get("levelErrors") or {}

    views: Dict[str, Any] = {}
    registry: List[Dict[str, Any]] = []

    for entry in payload.get("stations") or stations.registry():
        key = entry["key"]
        bucket = by_station.get(key, [])
        blocked_by = _blocking_error(entry, level_errors)
        registry.append(dict(entry, runs=len(bucket), blockedBy=blocked_by))
        views[key] = _view(bucket, tz_name, per_unit, day_tz)

    # Runs whose suite matches no station: a finding, not noise.
    unclassified = by_station.get(stations.UNCLASSIFIED, [])
    if unclassified:
        suites = sorted({
            "{}/{}".format(r.get("level"), r.get("suite")) for r in unclassified
        })
        registry.append({
            "key": stations.UNCLASSIFIED,
            "label": "Unclassified",
            "state": "unclassified",
            "order": 999,
            "runs": len(unclassified),
            "blockedBy": None,
            "note": "Runs whose suite matches no station in the registry: "
                    + ", ".join(suites[:12]),
        })
        views[stations.UNCLASSIFIED] = _view(unclassified, tz_name, per_unit, day_tz)

    # Debug builds, repros and smoke tests: a bucket of their own, so
    # "unclassified" keeps meaning "nobody has worked out what this is".
    engineering = by_station.get(stations.ENGINEERING, [])
    if engineering:
        suites = sorted({
            "{}/{}".format(r.get("level"), r.get("suite")) for r in engineering
        })
        registry.append({
            "key": stations.ENGINEERING,
            "label": "Engineering",
            "state": stations.ENGINEERING,
            "order": 998,
            "runs": len(engineering),
            "blockedBy": None,
            "note": "Not a line stage: debug builds, one-off repros, smoke tests "
                    "and suites named after a ticket. Excluded from line-wide "
                    "yield because they run on engineering DUTs. "
                    + ", ".join(suites[:12]),
        })
        views[stations.ENGINEERING] = _view(engineering, tz_name, per_unit, day_tz)

    # "All stations" is the union of production runs — the unclassified tail and
    # the engineering runs are both excluded so neither can quietly move
    # line-wide yield.
    off_line = (stations.UNCLASSIFIED, stations.ENGINEERING)
    classified = [r for r in runs
                  if (r.get("stationKey") or stations.UNCLASSIFIED) not in off_line]
    views["__all__"] = _view(classified, tz_name, per_unit, day_tz)
    registry.insert(0, {
        "key": "__all__", "label": "All stations", "state": "active",
        "order": 0, "runs": len(classified), "blockedBy": None,
        "note": "Every classified run across all stations.",
    })

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        # Which system these numbers came from. Two pages render this same
        # layout from different sources, and the daily yields differ between
        # them; a reader who cannot tell which one they are looking at will
        # eventually quote the wrong number.
        "dataSource": payload.get("dataSource") or DEFAULT_SOURCE,
        "collectedAt": payload.get("generatedAt"),
        "timezone": tz_name,
        # The window the page is *about*, which after trimming is not the
        # window that was collected.
        "window": _reported_window(
            runs, "UTC" if per_unit else tz_name) or payload.get("window", {}),
        # What a day means on this page, so the header can say it rather than
        # leaving a reader to discover it by disagreeing with another page.
        "dayBasis": {"timezone": "UTC" if per_unit else tz_name,
                     "counts": "units, last attempt of the day"
                               if per_unit else "runs"},
        "collectedWindow": payload.get("window", {}),
        "source": payload.get("source", "eos-api"),
        "levelErrors": level_errors,
        "stations": registry,
        "views": views,
        "fetch": fetchstate.summary(state or {}),
    }


def build_ranged_bundle(payload: Dict[str, Any],
                        state: Optional[Dict[str, Any]] = None,
                        floor: str = RANGE_FLOOR) -> Dict[str, Any]:
    """The 7-day bundle, with a second set of views covering everything since
    ``floor`` carried alongside it.

    WHY TWO PRECOMPUTED SETS RATHER THAN ONE AND A CLIENT-SIDE FILTER
    A view is not a list of days that can be sliced. It carries per-release
    aggregates and a failure Pareto, and neither can be re-derived from the
    daily rows a narrower slice would leave — you cannot recover which release
    a failure belonged to from a bar chart of days. The page would have to ship
    every run and re-aggregate in the browser, which is a different and much
    larger change. Two ranges, each aggregated once here, is the honest shape.

    ``views`` stays the 7-day set so that everything already reading it — the
    flow page's links, the cross-source comparison — keeps its meaning without
    knowing this exists. The wider set is additive.

    Station run counts are per-range too: the chips read "MLT 293" over seven
    days and something larger over the month, and a chip that disagreed with
    the chart under it would be the first thing anyone noticed.
    """
    # The same day basis the trim uses, not a string slice of startTs — it is
    # an epoch integer on the controller side, and the controllers cut their
    # days in UTC while EOS cuts them factory-local. Getting this wrong would
    # move the floor by a day on one source and not the other.
    tz_name = ("UTC" if payload.get("source") == "pega"
               else payload.get("timezone", config.timezone_name()))
    floored = dict(payload)
    floored["runs"] = [run for run in payload.get("runs") or []
                       if run.get("startTs")
                       and daily.day_key(run["startTs"], tz_name) >= floor]

    # The floor applies to BOTH ranges, not only to the wide one.
    #
    # It was only on the wide one, and that let "All" show less than "7 days".
    # The default keeps the last seven days *that have data*, so on a line with
    # a quiet fortnight it reaches back past the floor and picks up bring-up
    # that "All" is defined to exclude — a range called All showing fewer runs
    # than the one inside it. Flooring first makes the wide range a superset of
    # the default by construction, which is the only relationship between them
    # anybody would guess.
    bundle = build_bundle(floored, state, WINDOW_DAYS)
    # window_days=0 disables the trim: the floor has already decided how far
    # back this reaches, and a second cut would silently narrow it.
    full = build_bundle(floored, state, 0)

    bundle["ranges"] = {"default": "7d", "floor": floor, "options": RANGES}
    bundle["viewsAll"] = full["views"]
    bundle["stationsAll"] = full["stations"]
    bundle["windowAll"] = full["window"]
    return bundle


def _blocking_error(entry: Dict[str, Any], level_errors: Dict[str, str]) -> Optional[str]:
    """The API error that explains an empty station, if there is one."""
    for level in entry.get("levels") or []:
        if level in level_errors:
            return level_errors[level]
    return None


def _reported_window(runs: List[Dict[str, Any]], tz_name: str) -> Dict[str, Any]:
    days = sorted({daily.day_key(r["startTs"], tz_name)
                   for r in runs if r.get("startTs")})
    return {"from": days[0], "to": days[-1], "days": len(days)} if days else {}


def _view(runs: List[Dict[str, Any]], tz_name: str,
          per_unit: bool = False, day_tz: Optional[str] = None) -> Dict[str, Any]:
    retest = daily.retest(runs, tz_name)
    detail = retest.pop("detail", [])
    return {
        "summary": daily.station_summary(runs, tz_name),
        # Unit-level yield, beside the run-level yield rather than instead of
        # it. A module fixture drives eight chips and EOS scores the fixture, so
        # one bad chip reads as one failed run here and as one failed unit of
        # eight on the line's own tracker. Both numbers are true about different
        # populations, and replacing either with the other loses information:
        # the run figure is what the API measured, the unit figure is what the
        # line means by yield. Null where a station's tests carry no chip index.
        "units": chips.summarize(runs),
        "daily": daily.daily_yield(runs, day_tz or tz_name,
                                   per_unit=per_unit),
        "releases": daily.release_yield(runs, tz_name),
        "pareto": daily.top_yield_hits(runs),
        "firstFailure": daily.first_failure_areas(runs),
        "retest": retest,
        "retestDetail": detail[:RETEST_DETAIL_LIMIT],
        "retestDetailTruncated": max(0, len(detail) - RETEST_DETAIL_LIMIT),
    }


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "stations.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=_default)
    target.write_text(
        "// Generated by `python -m factory.cli build` — do not edit.\n"
        "window.__FACTORY_STATIONS__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target


def _default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    return str(value)
