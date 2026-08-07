"""Hourly manufacturing metrics over the normalized run table.

Metric definitions live in ``docs/metrics.md``. This module is the reference
implementation: the CLI ``report`` command and the unit tests both use it, and
``dashboard/app.js`` mirrors the same definitions client-side so filters can
re-aggregate without a round trip. If you change a definition, change it in all
three places — the tests in ``tests/test_hourly.py`` pin this side.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import config
from .parse import is_failure


def _tzinfo(name: Optional[str] = None):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name or config.timezone_name())
    except Exception:  # noqa: BLE001
        return timezone.utc


def hour_key(ts: int, tz_name: Optional[str] = None) -> str:
    """Bucket a UTC epoch second into a local hour label, ``YYYY-MM-DDTHH``."""
    local = datetime.fromtimestamp(ts, _tzinfo(tz_name))
    return local.strftime("%Y-%m-%dT%H")


def percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    """Linear-interpolated percentile. ``fraction`` is 0..1."""
    numbers = sorted(value for value in values if value is not None)
    if not numbers:
        return None
    if len(numbers) == 1:
        return float(numbers[0])
    position = fraction * (len(numbers) - 1)
    lower = int(position)
    upper = min(lower + 1, len(numbers) - 1)
    weight = position - lower
    return float(numbers[lower] * (1 - weight) + numbers[upper] * weight)


def usable(runs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Runs that can be placed on the timeline. Others cannot be rate-analyzed."""
    return [run for run in runs if run.get("startTs")]


def bucket_runs(
    runs: Iterable[Dict[str, Any]], tz_name: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in usable(runs):
        buckets[hour_key(run["startTs"], tz_name)].append(run)
    return dict(buckets)


def hourly_metrics(
    runs: Iterable[Dict[str, Any]], tz_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """One row per local hour that has at least one run start.

    Rate metrics are per *started* hour: a run is counted in the hour it started,
    so throughput reads as "units the line put into test during that hour".
    """
    rows = []
    for hour, hour_runs in sorted(bucket_runs(runs, tz_name).items()):
        rows.append(_metrics_for(hour, hour_runs))
    return rows


def _metrics_for(hour: str, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(runs)
    passed = sum(1 for run in runs if run.get("status") == "pass")
    failed = sum(1 for run in runs if run.get("status") == "fail")
    errored = sum(1 for run in runs if run.get("status") == "error")
    scored = passed + failed + errored  # runs with a verdict; excludes unknown/skip

    first_attempts = [run for run in runs if run.get("attempt") == 1]
    fpy_passed = sum(1 for run in first_attempts if run.get("status") == "pass")

    durations = [
        float(run["durationSec"])
        for run in runs
        if run.get("durationSec") not in (None, "")
    ]

    tests_run = 0
    tests_failed = 0
    failure_counter: Counter = Counter()
    for run in runs:
        counts = run.get("testCounts") or {}
        tests_run += sum(counts.get(key, 0) for key in ("pass", "fail", "error"))
        tests_failed += counts.get("fail", 0) + counts.get("error", 0)
        for failure in run.get("failures") or []:
            failure_counter[failure.get("test") or "(unnamed)"] += 1

    return {
        "hour": hour,
        "runs": total,
        "units": len({run.get("dutSerial") for run in runs if run.get("dutSerial")}),
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "passRate": (passed / scored) if scored else None,
        "firstAttempts": len(first_attempts),
        "firstPassYield": (fpy_passed / len(first_attempts)) if first_attempts else None,
        "cycleTimeMedian": percentile(durations, 0.5),
        "cycleTimeP90": percentile(durations, 0.9),
        "testsRun": tests_run,
        "testsFailed": tests_failed,
        "stations": dict(
            Counter(run.get("station") or "(unknown)" for run in runs)
        ),
        "topFailures": failure_counter.most_common(5),
    }


def failure_pareto(
    runs: Iterable[Dict[str, Any]], limit: int = 12
) -> List[Dict[str, Any]]:
    """Failing tests ranked by occurrence, with cumulative share.

    Counted per *run occurrence*: a test that fails in three runs scores three,
    which is what a line lead wants to act on.
    """
    counter: Counter = Counter()
    codes: Dict[str, Counter] = defaultdict(Counter)
    duts: Dict[str, set] = defaultdict(set)

    for run in runs:
        for failure in run.get("failures") or []:
            name = failure.get("test") or "(unnamed)"
            counter[name] += 1
            if failure.get("code"):
                codes[name][failure["code"]] += 1
            if run.get("dutSerial"):
                duts[name].add(run["dutSerial"])

    total = sum(counter.values())
    rows = []
    cumulative = 0
    for name, count in counter.most_common(limit):
        cumulative += count
        top_code = codes[name].most_common(1)
        rows.append(
            {
                "test": name,
                "failures": count,
                "share": (count / total) if total else 0.0,
                "cumulativeShare": (cumulative / total) if total else 0.0,
                "duts": len(duts[name]),
                "topCode": top_code[0][0] if top_code else None,
            }
        )
    return rows


def station_breakdown(
    runs: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Per-station totals over the whole selection."""
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[run.get("station") or "(unknown)"].append(run)

    rows = []
    for station, station_runs in grouped.items():
        scored = [r for r in station_runs if r.get("status") in ("pass", "fail", "error")]
        passed = sum(1 for r in scored if r.get("status") == "pass")
        durations = [
            float(r["durationSec"]) for r in station_runs if r.get("durationSec") not in (None, "")
        ]
        rows.append(
            {
                "station": station,
                "runs": len(station_runs),
                "units": len({r.get("dutSerial") for r in station_runs if r.get("dutSerial")}),
                "passRate": (passed / len(scored)) if scored else None,
                "cycleTimeMedian": percentile(durations, 0.5),
            }
        )
    rows.sort(key=lambda row: row["runs"], reverse=True)
    return rows


def dut_breakdown(runs: Iterable[Dict[str, Any]], limit: int = 25) -> List[Dict[str, Any]]:
    """DUTs ranked by failure count — the repeat-offender list."""
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run.get("dutSerial"):
            grouped[run["dutSerial"]].append(run)

    rows = []
    for dut, dut_runs in grouped.items():
        failures = sum(1 for r in dut_runs if is_failure(r.get("status", "unknown")))
        ordered = sorted(dut_runs, key=lambda r: r.get("startTs") or 0)
        rows.append(
            {
                "dut": dut,
                "runs": len(dut_runs),
                "failures": failures,
                "lastStatus": ordered[-1].get("status") if ordered else "unknown",
                "stations": sorted({r.get("station") or "(unknown)" for r in dut_runs}),
            }
        )
    rows.sort(key=lambda row: (row["failures"], row["runs"]), reverse=True)
    return rows[:limit]


def summary(runs: Iterable[Dict[str, Any]], tz_name: Optional[str] = None) -> Dict[str, Any]:
    """Headline numbers for the whole selection."""
    run_list = list(runs)
    placed = usable(run_list)
    hours = hourly_metrics(placed, tz_name)
    active_hours = len(hours)

    scored = [r for r in run_list if r.get("status") in ("pass", "fail", "error")]
    passed = sum(1 for r in scored if r.get("status") == "pass")
    first_attempts = [r for r in run_list if r.get("attempt") == 1]
    fpy_passed = sum(1 for r in first_attempts if r.get("status") == "pass")
    durations = [
        float(r["durationSec"]) for r in run_list if r.get("durationSec") not in (None, "")
    ]
    units = {r.get("dutSerial") for r in run_list if r.get("dutSerial")}

    return {
        "runs": len(run_list),
        "runsWithoutTimestamp": len(run_list) - len(placed),
        "units": len(units),
        "activeHours": active_hours,
        "unitsPerHour": (len(units) / active_hours) if active_hours else None,
        "runsPerHour": (len(placed) / active_hours) if active_hours else None,
        "passRate": (passed / len(scored)) if scored else None,
        "firstPassYield": (fpy_passed / len(first_attempts)) if first_attempts else None,
        "cycleTimeMedian": percentile(durations, 0.5),
        "cycleTimeP90": percentile(durations, 0.9),
        "totalFailures": sum(len(r.get("failures") or []) for r in run_list),
    }
