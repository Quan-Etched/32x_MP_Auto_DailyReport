"""Per-chip verdicts inside a fixture run.

THE THING THIS EXISTS TO FIX
----------------------------
A module test runs eight chips at once in one fixture, and EOS records the
result as **one run with one status**. The line records it as **eight units**,
one per slot. So a run where a single chip failed is ``fail`` in EOS and seven
``Passed`` plus one ``Failed`` on the line's own tracker — and the two are both
right about different things.

Measured on ``mlt_2026.220.0-git2f1c2f23_20260812_013949``: 492 tests, run
status ``fail``, and per chip four good and four bad. Reading that run as one
failure understates yield eightfold on a single-chip escape; reading it as one
pass would hide the escape entirely.

Every disagreement found between the line's 08-11/08-12 tabs and EOS ran in
this direction — sheet ``Passed``, EOS ``fail``, never the reverse — which is
the signature of exactly this and of nothing else.

HOW A CHIP IS IDENTIFIED
------------------------
The chip index is in the test name, in two spellings that both appear inside a
single run::

    server_setup_bootloader_result_chip4     suffix
    chip6_llama70b_tp1_forward_iterated      prefix
    chip3                                    bare (a container)

so the pattern accepts the index anywhere it is delimited by ``_`` or a
boundary. A name with no index at all is **fixture-level** — ``server_setup``,
``vbb_dependent_tests`` — and is reported separately rather than being charged
to a chip that did not cause it.

Containers are excluded for the same reason the Pareto excludes them: a nest
fails whenever anything under it fails, so counting both double-counts, and the
useful signature is always the leaf.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import rootcause

#: ``chip4`` anywhere it is delimited: ``_chip4``, ``chip4_``, or the whole name.
CHIP = re.compile(r"(?:^|_)chip(\d+)(?:_|$)", re.IGNORECASE)

#: Verdicts that mean the chip produced a result. Mirrors ``daily.GRADED``.
BAD = ("fail", "error")


def chip_of(name: Optional[str]) -> Optional[int]:
    """The chip index a test name refers to, or None if it is fixture-level."""
    if not name:
        return None
    match = CHIP.search(name)
    return int(match.group(1)) if match else None


def grade(run: Dict[str, Any]) -> Dict[str, Any]:
    """Split one fixture run into per-chip verdicts.

    Returns ``{"chips": {index: {...}}, "fixture": {...}, "slots": n}``. A chip
    entry carries its own status and the first failing leaf test, which is what
    the line writes in its "Failure Test Case" column.
    """
    chips: Dict[int, Dict[str, Any]] = {}
    fixture_fails: List[str] = []

    for test in run.get("tests") or []:
        name = test.get("name") or test.get("displayName") or ""
        status = (test.get("status") or "unknown").lower()

        # Same rule as the Pareto: a container "fails" only because a leaf did.
        # EOS calls the class "displayName"; it is the only reliable container
        # marker, since a bare "chip3" tells you nothing on its own.
        if rootcause.is_container(name, test.get("displayName")):
            continue

        index = chip_of(name)
        if index is None:
            if status in BAD:
                fixture_fails.append(name)
            continue

        entry = chips.setdefault(index, {"pass": 0, "fail": 0, "skip": 0,
                                         "unknown": 0, "firstFail": None})
        if status in BAD:
            entry["fail"] += 1
            if entry["firstFail"] is None:
                entry["firstFail"] = _display(test, name)
        elif status == "pass":
            entry["pass"] += 1
        elif status == "skip":
            entry["skip"] += 1
        else:
            entry["unknown"] += 1

    for entry in chips.values():
        entry["status"] = _verdict(entry)

    return {
        "chips": dict(sorted(chips.items())),
        # A fixture-level failure is not attributed to a chip: it is the rig,
        # the server or the harness, and blaming a slot for it would be a guess.
        "fixture": {"failed": bool(fixture_fails), "firstFail": fixture_fails[0]
                    if fixture_fails else None, "count": len(fixture_fails)},
        "slots": len(chips),
    }


def _verdict(entry: Dict[str, Any]) -> str:
    if entry["fail"]:
        return "fail"
    if entry["pass"]:
        return "pass"
    if entry["skip"]:
        return "skip"
    return "unknown"


def _display(test: Dict[str, Any], name: str) -> str:
    """The class name if EOS gave one — that is what the line writes down.

    The tracker's failure column says ``BootloaderResultTestCase``, not
    ``server_setup_bootloader_result_chip4``; the class is the shared signature
    across the eight chips, and the snake-case id is one chip's instance of it.
    """
    return test.get("displayName") or name


def summarize(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Unit-level pass/fail across many runs, for a yield figure.

    Counts chips, not runs: this is the population the line means when it says
    "yield", and it is the number the daily tracker's tabs total up.
    """
    passed = failed = other = 0
    graded_runs = 0
    for run in runs:
        result = grade(run)
        if not result["chips"]:
            continue
        graded_runs += 1
        for entry in result["chips"].values():
            if entry["status"] == "pass":
                passed += 1
            elif entry["status"] == "fail":
                failed += 1
            else:
                other += 1
    graded = passed + failed
    return {
        "units": passed + failed + other,
        "passed": passed,
        "failed": failed,
        "ungraded": other,
        "runs": graded_runs,
        "yield": (passed / graded) if graded else None,
    }
