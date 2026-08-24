"""What happened to a unit at a station, as one of five outcomes.

THE TAXONOMY
The line used to have two words for a unit's fate — pass and fail — and they
could not carry the question people were actually asking. "Fail" lumped a module
that failed once and passed on the retest together with one that failed and is
still sitting on a shelf. Those are opposite situations: the first cost a
fixture slot, the second cost a module.

So, per unit per station, inside a window:

  pass         its first attempt passed. Clean.
  retest-pass  its first attempt failed and a later attempt passed. It is back
               in the production flow. Chris Zhu's question is the size of this
               bucket as a share of the first-attempt failures.
  bonepile     its first attempt failed and it has never passed — no retest at
               all, or every retest failed too. Still out.
  no-result    it ran but no attempt produced a verdict. Rare, and it must not
               be silently folded into either side: a unit with no result is not
               a pass and blaming the module for it is worse.

  fail         NOT a fifth exclusive bucket. It is the union of retest-pass and
               bonepile: every unit whose first attempt failed. Kept as a name
               because that is the word the line uses and because a filter that
               offers pass/fail/retest-pass/bonepile without saying how they
               nest invites somebody to add the percentages up past 100.

The four exclusive outcomes partition every unit that has a graded attempt, plus
no-result for the ones that do not. That is asserted in the tests, because a
taxonomy that does not add up is worse than the two words it replaced.

WINDOW-RELATIVE, LIKE FIRST-PASS YIELD
"First attempt" means first inside the window. A unit tested before it looks
like a first attempt here, exactly as build_fpy counts it, so outcome counts and
first-pass yield reconcile against the same denominator. Stated rather than
corrected: the alternative is a population nobody can reconstruct.

SCOPE
MLT and HTT. TIM is measured and published in its own column but is not part of
the retest question — it is a bake, its repeats are a different animal, and the
line asked for the module line only.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import stations

#: The stations this is asked of, in flow order.
SCOPE = ("mlt", "htt")

#: A verdict that counts as an attempt. Anything else is not a result.
GRADED = ("pass", "fail", "error")

PASS = "pass"
RETEST_PASS = "retest-pass"
BONEPILE = "bonepile"
NO_RESULT = "no-result"

#: The four that partition the population, in the order they are presented.
EXCLUSIVE = (PASS, RETEST_PASS, BONEPILE, NO_RESULT)

#: Label, and the one-line definition that has to travel with the number.
LABELS = {
    PASS: ("Pass", "passed first time"),
    RETEST_PASS: ("Retest Pass",
                  "failed first, passed on a retest — back in the flow"),
    BONEPILE: ("Bonepile",
               "failed first and has never passed — no retest, or every "
               "retest failed"),
    NO_RESULT: ("No result", "ran but produced no verdict"),
    "fail": ("Fail", "any first-attempt failure — Retest Pass plus Bonepile"),
}

#: Colours, so the page, the DOE chart and the deck agree. Retest Pass is amber
#: rather than green: it ended well but it cost a second insertion, and drawing
#: it as a pass hides the cost.
COLOURS = {
    PASS: "#2f8f4e",
    RETEST_PASS: "#c8860d",
    BONEPILE: "#c0392b",
    NO_RESULT: "#8a8882",
}


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def classify(attempts: Sequence[Dict[str, Any]]) -> str:
    """One unit's attempts at one station, in time order, to an outcome."""
    graded = [a for a in attempts if a.get("status") in GRADED]
    if not graded:
        return NO_RESULT
    if graded[0]["status"] == "pass":
        return PASS
    return RETEST_PASS if any(a["status"] == "pass" for a in graded[1:]) \
        else BONEPILE


def by_unit(runs: Iterable[Dict[str, Any]],
            start: Optional[str] = None,
            end: Optional[str] = None,
            scope: Sequence[str] = SCOPE) -> Dict[str, Dict[str, List[dict]]]:
    """station -> unit -> its attempts inside the window, in time order."""
    held: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for run in runs:
        key = run.get("stationKey")
        if key not in scope or not run.get("startTs"):
            continue
        day = _day(run["startTs"])
        if start and day < start:
            continue
        if end and day > end:
            continue
        held[key][run["dutSerial"]].append(run)
    for station in held:
        for dut in held[station]:
            held[station][dut].sort(key=lambda r: r.get("startTs") or 0)
    return held


def tally(runs: Iterable[Dict[str, Any]],
          start: Optional[str] = None,
          end: Optional[str] = None,
          scope: Sequence[str] = SCOPE) -> List[Dict[str, Any]]:
    """One row per station: how many units landed in each outcome.

    Carries the release split for the retest passes, because "it came back" and
    "a new build brought it back" are different findings and the second is the
    one with an owner.
    """
    registry = {entry["key"]: entry for entry in stations.registry()}
    held = by_unit(runs, start, end, scope)
    rows = []
    for key in scope:
        units = held.get(key) or {}
        if not units:
            continue
        counts = {name: 0 for name in EXCLUSIVE}
        same_rel = other_rel = 0
        for dut, attempts in units.items():
            outcome = classify(attempts)
            counts[outcome] += 1
            if outcome != RETEST_PASS:
                continue
            graded = [a for a in attempts if a.get("status") in GRADED]
            failed_on = stations.release_of(graded[0].get("version"))
            back = next(a for a in graded[1:] if a["status"] == "pass")
            if stations.release_of(back.get("version")) == failed_on:
                same_rel += 1
            else:
                other_rel += 1

        total = len(units)
        first_failed = counts[RETEST_PASS] + counts[BONEPILE]
        rows.append({
            "key": key,
            "label": registry.get(key, {}).get("label", key.upper()),
            "units": total,
            "counts": dict(counts),
            # The union, named once here so no page has to add it up itself.
            "fail": first_failed,
            "firstPassYield": (counts[PASS] / total) if total else None,
            "recoveryRate": (counts[RETEST_PASS] / first_failed)
                            if first_failed else None,
            "sameRelease": same_rel,
            "differentRelease": other_rel,
        })
    return rows


#: A unit that never reached the next station. Not an outcome it had there —
#: the absence of one — and the Sankey has to draw it or the ribbons leaving MLT
#: will not sum to the ribbons arriving at HTT, which is the one property that
#: makes a Sankey readable.
DID_NOT_ARRIVE = "did-not-arrive"


def flows(runs: Iterable[Dict[str, Any]],
          start: Optional[str] = None,
          end: Optional[str] = None,
          scope: Sequence[str] = SCOPE) -> Dict[str, Any]:
    """The MLT -> HTT transition, unit by unit, as Sankey ribbons.

    Why a flow rather than two bar charts: the question underneath all of this
    is what happens to a module *after* it fails, and that is a question about
    the step between two stations. Two stacked bars can show that MLT had 10
    retest passes and HTT had 0; only the flow shows whether the modules MLT
    recovered went on to pass HTT, fail it, or never turn up.

    Units that appear at the second station without appearing at the first are
    real — they were tested before this window opened — and they enter as their
    own source band rather than being dropped, because dropping them makes the
    arriving totals disagree with the station's own count.
    """
    held = by_unit(runs, start, end, scope)
    first, second = scope[0], scope[1]
    left = held.get(first) or {}
    right = held.get(second) or {}

    ribbons: Dict[tuple, int] = defaultdict(int)
    for dut, attempts in left.items():
        source = classify(attempts)
        target = classify(right[dut]) if dut in right else DID_NOT_ARRIVE
        ribbons[(source, target)] += 1
    # Arrived at the second station without being seen at the first.
    for dut, attempts in right.items():
        if dut not in left:
            ribbons[("not-seen-here", classify(attempts))] += 1

    return {
        "from": first,
        "to": second,
        "fromLabel": LABELS[PASS] and first.upper(),
        "toLabel": second.upper(),
        "ribbons": [{"source": source, "target": target, "units": n}
                    for (source, target), n in sorted(
                        ribbons.items(), key=lambda kv: -kv[1])],
        "leftTotal": len(left),
        "rightTotal": len(right),
    }


def weeks_back(payload: Dict[str, Any], count: int = 6) -> List[Dict[str, Any]]:
    """One entry per ISO week with runs in scope, newest last."""
    from . import build_weekly

    runs = payload.get("runs") or []
    seen = set()
    for run in runs:
        if run.get("stationKey") in SCOPE and run.get("startTs"):
            seen.add(_day(run["startTs"]))
    if not seen:
        return []

    import datetime as dt
    labels = {}
    for day in seen:
        date = dt.date.fromisoformat(day)
        monday = date - dt.timedelta(days=date.weekday())
        labels[build_weekly.week_label(monday)] = monday

    out = []
    for label in sorted(labels)[-count:]:
        monday = labels[label]
        start = monday.isoformat()
        end = (monday + dt.timedelta(days=6)).isoformat()
        rows = tally(runs, start, end)
        for row in rows:
            check(row)
        out.append({
            "week": label, "from": start, "to": end,
            "stations": rows,
            "flow": flows(runs, start, end),
        })
    return out


def build_bundle(payload: Dict[str, Any], count: int = 6) -> Dict[str, Any]:
    from . import version

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "build": version.describe(),
        "source": payload.get("dataSource") or {},
        "scope": list(SCOPE),
        "labels": {name: {"label": text, "why": why}
                   for name, (text, why) in LABELS.items()},
        "colours": dict(COLOURS),
        "exclusive": list(EXCLUSIVE),
        "didNotArrive": DID_NOT_ARRIVE,
        "weeks": weeks_back(payload, count),
    }


def write_bundle(bundle: Dict[str, Any], path=None):
    import json

    from . import config

    target = path or (config.DASHBOARD_DATA_DIR / "outcomes.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "// Generated by `python -m factory.cli outcomes` — do not edit.\n"
        "window.__FACTORY_OUTCOMES__ = "
        + json.dumps(bundle, separators=(",", ":"), sort_keys=True)
        + ";\n", encoding="utf-8")
    return target


def check(row: Dict[str, Any]) -> None:
    """The partition has to add up. Called by the tests and the builders."""
    counts = row["counts"]
    total = sum(counts[name] for name in EXCLUSIVE)
    if total != row["units"]:
        raise AssertionError(
            "{}: outcomes sum to {} but {} units were seen — the taxonomy has "
            "a gap or an overlap".format(row["key"], total, row["units"]))
