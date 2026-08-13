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

#: Units listed in the retest table. The counts above it always cover every
#: unit; only the row list is capped.
RETEST_DETAIL_LIMIT = 60


def build_bundle(
    payload: Dict[str, Any], state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    runs: List[Dict[str, Any]] = payload.get("runs", [])
    tz_name = payload.get("timezone", config.timezone_name())
    by_station = daily.split_by_station(runs)
    level_errors = payload.get("levelErrors") or {}

    views: Dict[str, Any] = {}
    registry: List[Dict[str, Any]] = []

    for entry in payload.get("stations") or stations.registry():
        key = entry["key"]
        bucket = by_station.get(key, [])
        blocked_by = _blocking_error(entry, level_errors)
        registry.append(dict(entry, runs=len(bucket), blockedBy=blocked_by))
        views[key] = _view(bucket, tz_name)

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
        views[stations.UNCLASSIFIED] = _view(unclassified, tz_name)

    # "All stations" is the union of classified runs — the unclassified tail is
    # excluded so it cannot quietly inflate line-wide yield.
    classified = [r for r in runs if (r.get("stationKey") or stations.UNCLASSIFIED)
                  != stations.UNCLASSIFIED]
    views["__all__"] = _view(classified, tz_name)
    registry.insert(0, {
        "key": "__all__", "label": "All stations", "state": "active",
        "order": 0, "runs": len(classified), "blockedBy": None,
        "note": "Every classified run across all stations.",
    })

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "collectedAt": payload.get("generatedAt"),
        "timezone": tz_name,
        "window": payload.get("window", {}),
        "source": payload.get("source", "eos-api"),
        "levelErrors": level_errors,
        "stations": registry,
        "views": views,
        "fetch": fetchstate.summary(state or {}),
    }


def _blocking_error(entry: Dict[str, Any], level_errors: Dict[str, str]) -> Optional[str]:
    """The API error that explains an empty station, if there is one."""
    for level in entry.get("levels") or []:
        if level in level_errors:
            return level_errors[level]
    return None


def _view(runs: List[Dict[str, Any]], tz_name: str) -> Dict[str, Any]:
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
        "daily": daily.daily_yield(runs, tz_name),
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
