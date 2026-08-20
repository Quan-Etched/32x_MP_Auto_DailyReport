"""Per-station analytics: daily yield, release yield, top yield hits, retest.

The four views the line asked for. Definitions here mirror the existing daily
dashboard (`test-daily`) so the same run produces the same number in both.

Everything takes an already-normalized run list (``collect.collect`` output) and
is pure — no I/O — so the tests can pin the definitions.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import config, rootcause, stations
from .parse import is_failure

#: A rate computed on fewer than this many graded runs is marked "thin sample" —
#: rendered hollow on the trend lines. 1/1 = 100% is not a yield, it is a
#: coin toss, and drawing it solid invites the reader to act on noise.
THIN_SAMPLE = 5


def _tzinfo(name: Optional[str] = None):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name or config.timezone_name())
    except Exception:  # noqa: BLE001
        return timezone.utc


def day_key(ts: int, tz_name: Optional[str] = None) -> str:
    """Local calendar day, ``YYYY-MM-DD``."""
    return datetime.fromtimestamp(ts, _tzinfo(tz_name)).strftime("%Y-%m-%d")


# --------------------------------------------------------------------- grading

#: Runs that carry a verdict. `skip`/`unknown` are excluded from denominators
#: rather than assumed to be passes.
GRADED = ("pass", "fail", "error")


def _tally(runs: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Pass / fail / abort counts. `error` is presented as *abort* on this page,
    matching the line's vocabulary and the existing dashboard's legend."""
    counts = Counter(run.get("status") for run in runs)
    passed = counts.get("pass", 0)
    failed = counts.get("fail", 0)
    aborted = counts.get("error", 0)
    return {
        "runs": len(runs),
        "pass": passed,
        "fail": failed,
        "abort": aborted,
        "graded": passed + failed + aborted,
    }


def _first_attempts(runs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [run for run in runs if run.get("attempt") == 1]


def _fpy(runs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """First-pass yield over the runs given.

    Denominator is first-attempt runs *with a verdict*; a first attempt that was
    skipped never tested the unit.
    """
    firsts = [run for run in _first_attempts(runs) if run.get("status") in GRADED]
    passed = sum(1 for run in firsts if run.get("status") == "pass")
    return {
        "fpyPass": passed,
        "fpyTotal": len(firsts),
        "fpy": (passed / len(firsts)) if firsts else None,
        "thin": len(firsts) < THIN_SAMPLE,
    }


# ------------------------------------------------------- (a) yield vs daily

def daily_yield(
    runs: Sequence[Dict[str, Any]], tz_name: Optional[str] = None,
    per_unit: bool = False,
) -> List[Dict[str, Any]]:
    """One row per calendar day that has runs: pass/fail/abort plus FPY.

    Days with no runs are omitted rather than zero-filled — the reference
    dashboard skips non-production days (weekends) instead of drawing a gap, and
    a zero-run day has no yield to report.

    ``per_unit`` counts a day the way the daily tracker does: one row per unit,
    the last attempt of the day winning, rather than one row per run. The two
    answer different questions and both are defensible, but they were being read
    as the same number on two pages of one dashboard — a unit that failed at
    09:00 and passed at 14:00 is one pass on the tracker and one pass plus one
    failure here. Where the source is the controllers, the tracker is the
    definition and this follows it.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run.get("startTs"):
            grouped[day_key(run["startTs"], tz_name)].append(run)

    rows = []
    for day in sorted(grouped):
        bucket = grouped[day]
        counted = _latest_per_unit(bucket) if per_unit else bucket
        row = {"day": day}
        row.update(_tally(counted))
        # First-pass yield stays over first attempts either way; per-unit only
        # changes which run represents the unit *that day*.
        row.update(_fpy(bucket))
        row["units"] = len({r.get("dutSerial") for r in bucket if r.get("dutSerial")})
        row["perUnit"] = per_unit
        rows.append(row)
    return rows


def _latest_per_unit(bucket: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The last run each unit had that day — the tracker's row for it.

    A unit with no serial cannot be collapsed onto anything, so it is kept as
    its own row rather than silently dropped.
    """
    latest: Dict[str, Dict[str, Any]] = {}
    loose: List[Dict[str, Any]] = []
    for run in sorted(bucket, key=lambda r: r.get("startTs") or 0):
        dut = (run.get("dutSerial") or "").strip()
        if not dut:
            loose.append(run)
            continue
        latest[dut] = run
    return list(latest.values()) + loose


# ----------------------------------------------------- (b) yield vs releases

def release_yield(
    runs: Sequence[Dict[str, Any]], tz_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """One row per software release, with the date range it ran on the line.

    The release is the middle component of the version string
    (``2026.207.0-git…`` -> ``207``). The date range matters: it is what lets a
    reader tell a bad release from a bad week.
    """
    grouped: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[stations.release_of(run.get("version"))].append(run)

    rows = []
    for release in sorted(grouped, key=stations.release_sort_key):
        bucket = grouped[release]
        days = sorted({day_key(r["startTs"], tz_name) for r in bucket if r.get("startTs")})
        row = {
            "release": release if release is not None else "(no version)",
            "firstDay": days[0] if days else None,
            "lastDay": days[-1] if days else None,
            "versions": sorted({r.get("version") for r in bucket if r.get("version")}),
        }
        row.update(_tally(bucket))
        row.update(_fpy(bucket))
        rows.append(row)
    return rows


# ------------------------------------------------------ (c) top yield hits

def top_yield_hits(
    runs: Sequence[Dict[str, Any]], limit: int = 12
) -> List[Dict[str, Any]]:
    """Failure Pareto bucketed to root-cause area, with cumulative share.

    Counted per **failing test occurrence**, and every failing test in a run is
    counted — a run that fails three different areas hits three areas. The
    companion ``first_failure_areas`` counts each failing *run* once, at the
    area of the test that failed first; use that when you want "what stopped
    this unit".
    """
    counter: Counter = Counter()
    examples: Dict[str, Counter] = defaultdict(Counter)
    duts: Dict[str, set] = defaultdict(set)
    detail: Dict[str, Dict[str, Any]] = defaultdict(_detail)

    for run in runs:
        for failure in run.get("failures") or []:
            # Nested containers fail only because a child did; counting both
            # double-counts and buries the real cause.
            if rootcause.is_container(failure.get("display"), failure.get("test")):
                continue
            name = rootcause.area(failure.get("test"), failure.get("display"),
                                  failure.get("code"))
            counter[name] += 1
            if failure.get("test"):
                examples[name][failure["test"]] += 1
            if run.get("dutSerial"):
                duts[name].add(run["dutSerial"])
            _record(detail[name], run, failure)

    return _pareto_rows(counter, examples, duts, limit, detail)


def first_failure_areas(
    runs: Sequence[Dict[str, Any]], limit: int = 12
) -> List[Dict[str, Any]]:
    """One area per failing run — the first failure that stopped the unit."""
    counter: Counter = Counter()
    examples: Dict[str, Counter] = defaultdict(Counter)
    duts: Dict[str, set] = defaultdict(set)

    for run in runs:
        failures = run.get("failures") or []
        if not failures or not is_failure(run.get("status", "unknown")):
            continue
        leaves = [f for f in failures
                  if not rootcause.is_container(f.get("display"), f.get("test"))]
        if not leaves:
            continue
        first = leaves[0]
        name = rootcause.area(first.get("test"), first.get("display"), first.get("code"))
        counter[name] += 1
        if first.get("test"):
            examples[name][first["test"]] += 1
        if run.get("dutSerial"):
            duts[name].add(run["dutSerial"])

    return _pareto_rows(counter, examples, duts, limit)


#: How much of an area's breakdown travels with the page.
#:
#: Enough to answer "which station, which test, which units" without a second
#: request, and bounded so twelve areas do not carry every failure in the
#: window. The full rows are one click further on, in the run table.
DETAIL_TESTS = 8
DETAIL_DUTS = 12


def _detail() -> Dict[str, Any]:
    return {"stations": defaultdict(Counter), "tests": Counter(),
            "duts": Counter(), "days": Counter(), "stationDuts": defaultdict(set)}


def _record(bucket: Dict[str, Any], run: Dict[str, Any],
            failure: Dict[str, Any]) -> None:
    """One failing test occurrence, filed under everything a reader asks next."""
    station = run.get("stationKey") or stations.UNCLASSIFIED
    dut = run.get("dutSerial")
    bucket["stations"][station]["fails"] += 1
    if dut:
        bucket["stationDuts"][station].add(dut)
        bucket["duts"][dut] += 1
    # Grouped on the signature, not the raw id: the controllers stamp a run
    # hash on every test name, so the raw ids are all distinct and a list of
    # them says nothing.
    name = rootcause.signature(failure.get("test"), failure.get("display"))
    if name:
        bucket["tests"][name] += 1


def _pareto_rows(counter, examples, duts, limit,
                 detail=None) -> List[Dict[str, Any]]:
    total = sum(counter.values())
    rows = []
    cumulative = 0
    for name, count in counter.most_common(limit):
        cumulative += count
        top = examples[name].most_common(1)
        row = {
            "area": name,
            "fails": count,
            "share": (count / total) if total else 0.0,
            "cumulativeShare": (cumulative / total) if total else 0.0,
            "duts": len(duts[name]),
            "topTest": top[0][0] if top else None,
        }
        if detail is not None:
            bucket = detail.get(name)
            if bucket:
                row["byStation"] = [
                    {"station": key,
                     "label": stations.label_of(key),
                     "fails": value["fails"],
                     "duts": len(bucket["stationDuts"].get(key) or ())}
                    for key, value in sorted(
                        bucket["stations"].items(),
                        key=lambda kv: -kv[1]["fails"])
                ]
                row["byTest"] = [
                    {"test": test, "fails": hits}
                    for test, hits in bucket["tests"].most_common(DETAIL_TESTS)
                ]
                row["testCount"] = len(bucket["tests"])
                row["topDuts"] = [
                    {"dut": serial, "fails": hits}
                    for serial, hits in bucket["duts"].most_common(DETAIL_DUTS)
                ]
        rows.append(row)
    return rows


# ------------------------------------------------------------- (d) retest

def retest(
    runs: Sequence[Dict[str, Any]], tz_name: Optional[str] = None
) -> Dict[str, Any]:
    """Units that went through a station more than once.

    A retest is *the same DUT serial with more than one run at the same
    station*, within the collected window. Attempt 1 is the unit's first pass;
    attempts 2..n are retests.

    Two things a line lead wants from this, and they are different questions:

    - **Retest rate** — of the units that entered, how many had to go round
      again? That is a flow/capacity number.
    - **Retest recovery** — of the units that failed first time and were
      retried, how many eventually passed? That is a "was the failure real"
      number. A high recovery rate means the station is failing good units.

    Window-relative, exactly like FPY: a unit first tested before the window
    looks like a first attempt here.
    """
    by_dut: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run.get("dutSerial"):
            by_dut[run["dutSerial"]].append(run)

    units: List[Dict[str, Any]] = []
    for dut, dut_runs in by_dut.items():
        ordered = sorted(dut_runs, key=lambda r: r.get("startTs") or 0)
        graded = [r for r in ordered if r.get("status") in GRADED]
        first = graded[0] if graded else None
        last = graded[-1] if graded else None
        passes = sum(1 for r in graded if r.get("status") == "pass")
        units.append({
            "dut": dut,
            "runs": len(ordered),
            "attempts": len(graded),
            "firstStatus": first.get("status") if first else "unknown",
            "lastStatus": last.get("status") if last else "unknown",
            "passes": passes,
            "failures": sum(1 for r in graded if is_failure(r.get("status", "unknown"))),
            "firstDay": day_key(ordered[0]["startTs"], tz_name) if ordered[0].get("startTs") else None,
            "lastDay": day_key(ordered[-1]["startTs"], tz_name) if ordered[-1].get("startTs") else None,
            "releases": sorted(
                {stations.release_of(r.get("version")) for r in ordered if r.get("version")},
                key=stations.release_sort_key,
            ),
        })

    units.sort(key=lambda u: (u["runs"], u["failures"]), reverse=True)

    entered = len(units)
    retested = [u for u in units if u["attempts"] > 1]
    failed_first = [u for u in units if u["firstStatus"] in ("fail", "error")]
    recovered = [u for u in failed_first if u["lastStatus"] == "pass"]
    still_failing = [u for u in units if u["lastStatus"] in ("fail", "error")]

    depth = Counter(min(u["attempts"], 5) for u in units if u["attempts"] >= 1)

    return {
        "units": entered,
        "retestedUnits": len(retested),
        "retestRate": (len(retested) / entered) if entered else None,
        "totalRetestRuns": sum(u["attempts"] - 1 for u in retested),
        "failedFirst": len(failed_first),
        "recovered": len(recovered),
        # Of the units that failed first time, how many ended up passing.
        "recoveryRate": (len(recovered) / len(failed_first)) if failed_first else None,
        "stillFailing": len(still_failing),
        # attempts -> unit count, 5 meaning "5 or more"
        "depth": [{"attempts": k, "units": depth[k]} for k in sorted(depth)],
        "detail": units,
    }


# ------------------------------------------------------------ station rollup

def station_summary(
    runs: Sequence[Dict[str, Any]], tz_name: Optional[str] = None
) -> Dict[str, Any]:
    """Headline numbers for one station."""
    tally = _tally(runs)
    result = dict(tally)
    result.update(_fpy(runs))
    timestamps = [r["startTs"] for r in runs if r.get("startTs")]
    result.update({
        "units": len({r.get("dutSerial") for r in runs if r.get("dutSerial")}),
        "passRate": (tally["pass"] / tally["graded"]) if tally["graded"] else None,
        "lastRunTs": max(timestamps) if timestamps else None,
        "firstRunTs": min(timestamps) if timestamps else None,
    })
    return result


def split_by_station(runs: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Bucket runs by station key, including :data:`stations.UNCLASSIFIED`.

    Reads ``stationKey`` (assigned by the collector from the registry), not
    ``station`` — the latter is the API's own fixture field, which EOS never
    populates.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[run.get("stationKey") or stations.UNCLASSIFIED].append(run)
    return dict(grouped)
