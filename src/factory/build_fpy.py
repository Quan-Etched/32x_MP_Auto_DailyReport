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
from typing import Any, Dict, List, Optional, Sequence

from . import config, outcomes, rootcause, stations, version

#: Days reported. A week: long enough to smooth a bad shift, short enough that
#: a fix landed on Tuesday still shows.
DEFAULT_DAYS = 7

#: Days of history walked to decide whether a unit is new to a stage. Longer
#: than the reported window on purpose — see the module docstring — and now as
#: long as the controllers keep, so "first attempt" means first attempt rather
#: than first attempt this month.
HISTORY_DAYS = 90

GRADED = ("pass", "fail", "error")

#: Stages measured elsewhere, carried so the chart is the whole line rather
#: than the part we happen to collect.
#:
#: Read from weekly/external_yields.json, which a human edits — WST and FT are
#: Sigurd's and arrive by message, so there is nowhere for them to come from
#: automatically. Keeping them in a data file rather than in this module means
#: updating them on a Saturday is an edit to a number, not a patch to a
#: program, and the figure carries the date and the person who reported it.
EXTERNAL_FILE = config.REPO_ROOT / "weekly" / "external_yields.json"

#: Used when the file is missing, so a fresh checkout still renders the shape
#: of the page. Marked stale by the same asOf machinery as any other figure.
EXTERNAL_FALLBACK: Dict[str, Dict[str, Any]] = {
    "wst": {"yield": None, "source": "not reported", "asOf": None,
            "note": "Wafer sort. Add it to weekly/external_yields.json."},
    "ft": {"yield": None, "source": "not reported", "asOf": None,
           "note": "Final test. Add it to weekly/external_yields.json."},
}


def external() -> Dict[str, Dict[str, Any]]:
    """The hand-reported yields, or a marked absence."""
    try:
        raw = json.loads(EXTERNAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(EXTERNAL_FALLBACK)

    out: Dict[str, Dict[str, Any]] = {}
    for key, default in EXTERNAL_FALLBACK.items():
        entry = raw.get(key)
        if not isinstance(entry, dict) or entry.get("yield") is None:
            out[key] = dict(default)
            continue
        out[key] = {
            "yield": entry.get("yield"),
            "asOf": entry.get("asOf"),
            "source": entry.get("source") or "reported",
            "note": entry.get("note") or "",
        }
    return out


#: Stations whose repeat runs are a *sequence*, not a retest. VBB provisioning
#: puts every board through eight suites (PROD_01_vbb_provisioning,
#: PROD_02_vbb_validate…, flash_and_lockdown_bootloader and five more), all
#: mapped to one station — so counting units with more than one run gives a
#: 100% retest rate for a stage that retests almost nothing.
MULTI_SUITE = ("vbb_provision",)

#: Stages that report quantity only — units and runs, never a yield or a
#: retest rate.
#:
#: Empty since 2026-08-23. L10 and L11 used to publish counts and no yield:
#: their volumes are single digits a week, a percentage over three chassis
#: swings 33 points on one unit, and it would get quoted anyway. The note said
#: to remove the prefix when the line decided L10 yield meant something, and
#: the line has.
#:
#: What makes it safe now is that the rolled figure is scoped to MLT x HTT
#: (ROLLED_STATIONS). A two-unit stage can no longer drag the headline to zero,
#: which was the actual damage this policy was preventing. The yields publish
#: with their unit counts beside them and a thin-cohort mark, so the reader can
#: see a 50% that is one unit of two for what it is.
COUNTS_ONLY_PREFIXES: tuple = ()

COUNTS_ONLY_NOTE = "chassis and rack level, in bring-up — quantity only"


def counts_only(key: str) -> bool:
    return key.startswith(COUNTS_ONLY_PREFIXES)


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def build_bundle(payload: Dict[str, Any], days: int = DEFAULT_DAYS,
                 start: Optional[str] = None, end: Optional[str] = None,
                 exclude: Sequence[str] = (),
                 min_cohort: Optional[int] = None) -> Dict[str, Any]:
    """The window's yield per step.

    ``start``/``end`` pin the window to real dates — a working week runs Monday
    to Sunday, and a rolling "last seven days" quietly straddles two of them,
    which is how a Monday meeting ends up discussing a number that includes
    the previous Sunday.
    """
    floor = MIN_COHORT if min_cohort is None else min_cohort
    today = datetime.now(timezone.utc).date()
    if start is None:
        start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    if end is None:
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
        if key in exclude:
            continue
        units = {dut: rs for (station, dut), rs in history.items() if station == key}
        window = {dut: [r for r in rs
                        if start <= _day(r["startTs"]) <= end]
                  for dut, rs in units.items()}
        window = {dut: rs for dut, rs in window.items() if rs}
        if not window:
            continue

        # New to this stage: its very first run in the collected history landed
        # inside the window. These are the only units an FPY can be asked of.
        fresh = [dut for dut in window if _day(units[dut][0]["startTs"]) >= start]
        # Two floors, because the two figures have different denominators: a
        # stage can test fifty units of which three are new, and its final
        # yield is then perfectly readable while its first-pass yield is not.
        readable = len(fresh) >= floor
        yield_readable = len(window) >= floor
        if counts_only(key):
            readable = yield_readable = False
        # Below the floor but not silent: publish the yield and mark it, rather
        # than withholding it. Asked for explicitly for L10 and L11, where the
        # counts are small and will stay small for a while, and the alternative
        # was a column of dashes that read as "no testing happened".
        thin_cohort = bool(len(window)) and not yield_readable
        first_pass = sum(1 for dut in fresh if units[dut][0]["status"] == "pass")

        # Bonepile recovery, asked for by name: of the units that failed their
        # first pass, how many got back into the production flow — and did a
        # software release do it, or did the same build pass on a second go?
        #
        # The distinction is the whole finding. Recovered on the SAME release
        # means the first failure did not reproduce: marginal, flaky, or a
        # handling problem, and the unit was probably always good. Recovered on
        # a DIFFERENT release means a software fix released it. One of those is
        # a test-escape problem and the other is a schedule item, and a single
        # "recovery rate" hides which.
        #
        # Population is the window-relative first attempt, the same one FPY
        # uses, so first-pass fails and FPY reconcile: 350 MLT units at 71.2%
        # leaves 100 first-pass failures, and this counts those 100.
        # MLT and HTT only. TIM is a bake: its repeats are a thermal soak
        # being run again, not a module being given a second chance, and
        # reporting a "bonepile recovery" for it invited the number to be read
        # as the same kind of thing. It keeps its own yield column.
        bone = [] if key not in outcomes.SCOPE else [
            dut for dut in window
            if window[dut][0]["status"] in ("fail", "error")]
        same_rel = other_rel = 0
        for dut in bone:
            attempts = window[dut]
            failed_on = stations.release_of(attempts[0].get("version"))
            back = next((r for r in attempts[1:] if r["status"] == "pass"), None)
            if back is None:
                continue
            if stations.release_of(back.get("version")) == failed_on:
                same_rel += 1
            else:
                other_rel += 1
        recovered_back = same_rel + other_rel
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
            # Published whenever there is anything to divide, floor or no
            # floor, and marked when the cohort is thin.
            #
            # It used to be withheld below MIN_COHORT, on the grounds that a
            # 0.0% over two units is not a yield and printing one invites
            # somebody to quote it. That was right about the arithmetic and
            # wrong about the reader: a column of dashes across L10 and L11
            # read as "no testing happened here", which is a worse claim than a
            # number with its denominator beside it. `readable` still says
            # whether the figure can be leaned on, and it still gates the
            # rolled product; `thinCohort` says it on the page.
            "fpy": (first_pass / len(fresh)) if fresh else None,
            "finalYield": (passed / len(window)) if window else None,
            "readable": readable,
            "yieldReadable": yield_readable,
            "passedUnits": passed,
            "firstPassUnits": first_pass if readable else None,
            # Retest load: units that needed more than one run this week. Left
            # out where repeat runs are a provisioning sequence rather than a
            # second attempt at the same test.
            # Plainly: the share of units that had to be run more than once.
            # Chris Zhu's question, in his words: what share of first-pass
            # failed units are recovered from the bonepile and back into the
            # production flow. Split by whether the pass came on the same
            # software release or a different one.
            "bonepile": None if key not in outcomes.SCOPE else {
                "firstPassFailed": len(bone),
                "recovered": recovered_back,
                "recoveryRate": (recovered_back / len(bone)) if bone else None,
                "sameRelease": same_rel,
                "differentRelease": other_rel,
                "stillOut": len(bone) - recovered_back,
            },
            "retestRatio": None if (key in MULTI_SUITE or counts_only(key))
                           else repeats / len(window),
            "retestUnits": None if (key in MULTI_SUITE or counts_only(key))
                           else repeats,
            "retestNote": COUNTS_ONLY_NOTE if counts_only(key) else
                          ("repeat runs here are a provisioning sequence, not "
                           "retests") if key in MULTI_SUITE else None,
            "countsOnly": counts_only(key),
            # True where a yield is published over too few units to lean on.
            # The page prints it beside the number; nothing computes with it.
            "thinCohort": thin_cohort,
            "topFailures": _top_failures(
                [r for rs in window.values() for r in rs]),
            "measured": True,
        })

    reported = external()
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "window": {"from": start, "to": end, "days": days},
        "excluded": list(exclude),
        "historyDays": HISTORY_DAYS,
        "source": payload.get("dataSource") or {},
        "rows": rows,
        "external": [
            dict(_external_in(reported[key], start, end), key=key,
                 label=registry.get(key, {}).get("label", key.upper()),
                 measured=False)
            for key in ("wst", "ft") if key in reported
        ],
        "totals": _totals(rows, floor),
    }



#: How long a hand-reported figure may be carried forward before it stops
#: being shown.
#:
#: These arrive weekly, so three missed reports is the point at which "last
#: known" stops meaning anything. Carrying forever was the original defect in
#: another form: a marked-but-ancient number is still the number somebody
#: screenshots.
CARRY_DAYS = 21


def _external_in(entry: Dict[str, Any], start: str, end: str) -> Dict[str, Any]:
    """A hand-reported figure, carried forward but never backward.

    WST and FT arrive from Sigurd as one number with the day it is about, and
    they do not arrive every week — "FT: no new update" is a normal message. So
    a window that has no figure of its own should show the last one rather than
    a dash, which is what was asked for; the whole question is how it is
    labelled.

    THE ASYMMETRY IS THE POINT
    Forward is fine and backward is nonsense. This function used to blank the
    figure on any window that did not contain its ``asOf``, and the reason was a
    real bug: the week of 06-08 — before the line existed — published WST 35.3%
    because August's number was being pinned to every window. Carrying forward
    fixes the dash without reintroducing that, because a figure from 08-14 shown
    on the week of 08-17 is genuinely the latest known, and one from 08-14 shown
    on the week of 06-08 is not a figure about that week at all.

    So there are four outcomes, and each says which it is:

    ``fresh``    ``asOf`` falls inside the window. The figure is this window's.
    ``carried``  ``asOf`` is before it, within CARRY_DAYS. Shown, marked, with
                 its date and age, because "nobody reported one this week" and
                 "there is no such measurement" are different facts.
    ``stale``    older than CARRY_DAYS. Not shown — three missed weekly reports
                 in, "last known" has stopped meaning anything.
    ``ahead``    ``asOf`` is after the window. Not shown, and this is the case
                 the original rule existed for.
    """
    if entry.get("yield") is None:
        return dict(entry, state="absent")       # already a marked absence

    as_of = entry.get("asOf")
    note = (entry.get("note") or "").strip()

    if not as_of:
        return dict(entry, **{
            "yield": None, "state": "absent",
            "source": "undated figure",
            "note": (note + " The reported figure carries no date.").strip(),
        })

    if start <= as_of <= end:
        return dict(entry, state="fresh", ageDays=0)

    if as_of > end:
        return dict(entry, **{
            "yield": None, "state": "ahead",
            "source": "not reported by this week",
            "note": (note + " First reported for {}.".format(as_of)).strip(),
        })

    age = (datetime.strptime(end, "%Y-%m-%d").date()
           - datetime.strptime(as_of, "%Y-%m-%d").date()).days
    if age > CARRY_DAYS:
        return dict(entry, **{
            "yield": None, "state": "stale", "ageDays": age,
            "source": "no figure within {} days".format(CARRY_DAYS),
            "note": (note + " Last reported for {}, {} days before the end of "
                            "this week.".format(as_of, age)).strip(),
        })

    return dict(entry, **{
        "state": "carried", "ageDays": age,
        "note": (note + " Carried forward: no new figure since {}.".format(
            as_of)).strip(),
    })

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

#: The rolled figure is the module line, and only the module line.
#:
#: It used to multiply every stage with a readable cohort, which as of 2026-W34
#: means TIM as well — and TIM's 35.9% dragged the W34 headline to 19.7% when
#: the number the line quotes for that week is MLT x HTT. TIM is measured and
#: reported in its own column; it is not part of the accumulated module yield
#: yet, and a headline that silently changes meaning the week a new station
#: starts reporting is worse than one with a stated scope.
#:
#: The scope is named in `rolledOver`, which every page prints beside the
#: number, so widening this list re-labels the pages rather than moving a
#: number nobody can account for.
ROLLED_STATIONS = ("mlt", "htt")


def _totals(rows: List[Dict[str, Any]], floor: int = MIN_COHORT) -> Dict[str, Any]:
    labels = {entry["key"]: entry.get("label", entry["key"])
              for entry in stations.registry()}
    graded = [row for row in rows if row["fpy"] is not None]
    in_scope = [row for row in graded if row["key"] in ROLLED_STATIONS]
    # Both halves, or no product. See `rolledFpy`.
    complete = len(in_scope) == len(ROLLED_STATIONS)
    thin_scope = [row for row in in_scope if not row["readable"]]
    absent = [labels.get(key, key.upper()) for key in ROLLED_STATIONS
              if key not in {row["key"] for row in in_scope}]
    thin = [row for row in rows
            if not row["readable"] and not row.get("countsOnly")]
    return {
        "stations": len(rows),
        "units": sum(row["units"] for row in rows),
        "runs": sum(row["runs"] for row in rows),
        # Rolled through: the probability a unit clears the module line first
        # time. A product, because that is what it is — and the number nobody
        # had computed for this line. Scope is ROLLED_STATIONS, and `rolledOver`
        # names it so the pages can say which stages are in the number.
        #
        # PUBLISHED THIN RATHER THAN WITHHELD, asked for on 2026-09-08.
        # A thin stage's own yield has published-and-marked since L10 and L11
        # wanted their numbers; the product went on being withheld, so 2026-W36
        # — MLT 40% over 10 first-time units, HTT 78.9% over 19 — had a blank
        # headline while both its halves were on the page. A blank is not the
        # more cautious answer, it is a different claim: two people read it as
        # "the week was not measured" in one day. So the product publishes with
        # its cohorts named in `rolledThin`, and every page marks it.
        #
        # BOTH HALVES OR NOTHING. The figure is called MLT x HTT and one
        # station is not a product of two: 2026-W31 ran MLT before HTT existed,
        # and 54.5% under that heading would be a different measure wearing the
        # headline's name. `rolledMissing` says which half is absent, which is
        # the same rule the all-hands chart already applies week by week.
        "rolledFpy": (_product([row["fpy"] for row in in_scope])
                      if complete else None),
        "rolledOver": [row["label"] for row in in_scope] if complete else [],
        # What makes the published product thin, or — where it is withheld —
        # what it was waiting for. Either way these are the in-scope stations
        # whose first-pass cohort is under the floor, with the denominator each
        # was taken over.
        #
        # First-pass yield is over *first-time* units, and W36 put 90 units
        # through MLT of which 10 had never been there before. `excludedThin`
        # names every thin stage; this names only the ones in the product.
        "rolledThin": [{"label": row["label"], "newUnits": row["newUnits"],
                        "units": row["units"]}
                       for row in thin_scope],
        # The half that did not run, or ran without a first-time unit to take a
        # yield over. Non-empty is exactly when `rolledFpy` is None.
        "rolledMissing": absent,
        # Named, not hidden. That these stages are too thin to roll is itself
        # the readiness finding, and burying it would make the headline look
        # like whole-line coverage.
        "excludedThin": [{"label": row["label"], "newUnits": row["newUnits"],
                          "units": row["units"]} for row in thin],
        "minCohort": floor,
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
