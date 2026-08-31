"""One station vocabulary for three systems that each use their own.

THE PROBLEM
-----------
The same physical stage is called three different things:

    the line   SFIS ``station``     EOS (level, suite)          ESVM
    ────────   ──────────────────   ─────────────────────────   ────────────
    MLT        —                    (slt|module, ``mlt``)       pega3 suite
    TIM        ``TIM Baking``       (module, ``baking``)        pega6
    L10 FAT    —                    (l10, ``L10_FAT``)          pega4
    Assy1..8   ``Assy1``            —                           —
    SHIP       ``SHIP``             —                           —

A YAML whose ``station:`` field is sometimes ``baking`` and sometimes
``TIM Baking`` and sometimes ``TIM`` cannot be grouped, filtered or trusted, and
the person reading it during a failure investigation will not know they are the
same stage.

WHERE THE MAPPING COMES FROM
----------------------------
The (level, suite) → station half is **not reimplemented here**. It lives in
``factory.stations``, verified against a 30-day live window, and it already
absorbs the renames — ``L10_6U_FAT`` → ``L10_FAT`` at release 220, HTT running
under ``rdqs_sweep_training``, MLT appearing under both ``module`` and ``slt``.
A second copy would be wrong the first time the line renames a suite, and nobody
would notice which copy was stale.

So this module imports ``classify()`` and adds only what ``factory.stations`` has
no reason to know: the SFIS route-station half, which it never sees.

    Until these two packages shared a repository, this import went through a
    ``sys.path`` insert pointed at a separate checkout, backed by a coarse
    ``FALLBACK`` table for when that checkout was missing and a
    ``registry_source()`` accessor so a reader could tell a canonical station
    name from a best guess. All three are gone. The import cannot half-work now,
    so there is nothing to fall back to and nothing to report. Deleting that
    shim was the main structural reason to merge the repositories.
"""

from __future__ import annotations

import re
from typing import Optional

from factory.stations import classify, label_of


def from_eos(level: Optional[str], suite: Optional[str]) -> str:
    """Station label for an EOS run.

    Falls back to ``level/suite`` rather than to a guess: an unrecognised suite
    is a new or renamed stage, and printing the raw pair is how somebody notices
    and adds it to ``factory.stations``. Silently bucketing it as "other" is how
    a station disappears from a yield report for a month.
    """
    key = classify(level, suite)
    if key and key not in {"unclassified", "engineering"}:
        return label_of(key) or key
    return f"{level or '?'}/{suite or '?'}"


#: What Pega's own ``section`` field means. This is the primary signal and the
#: station name is only a refinement, because ``section`` is a small closed
#: vocabulary Pega controls while station names are free text it renames often:
#: ``Sohu Module Test`` and ``FBT Sanity Test`` are both tests and neither
#: matches any pattern you would have guessed. Observed sections across live
#: traffic: SMT, DIP, ASSY, TEST, QC, PACK.
SECTION_KINDS = {
    "test": "test",
    "qc": "quality",
    "qa": "quality",
    "smt": "fabrication",
    "dip": "fabrication",
    "assy": "assembly",
    "pack": "logistics",
}

#: Station-name patterns, used only when ``section`` is absent or unrecognised.
STATION_KINDS = (
    (r"^assy\s*\d*$|^sohu input$", "assembly"),
    (r"\btest\b|\bft\b|^rin$|^fat$|^sft$|^mda$|xray|x-ray|^spi$|aoi", "test"),
    (r"^aqc|^qa\b|^fqc$|visual", "quality"),
    (r"tim|baking|replenish|dispens", "process"),
    (r"^pack$|^wip$|^ship$|^input$", "logistics"),
)


#: Stations Pega files under ``section: TEST`` that are not tests. Kept as an
#: explicit, short, growable list rather than a cleverer rule, because the only
#: honest way to know is to read the station name and decide — and a reader of
#: this file should be able to see every such decision at once.
#: ``Replenish PG25`` is thermal-paste replenishment on the TIM cell: material
#: handling that Pega routes through the TEST section. Inheriting it as evidence
#: would tell a reader a coldplate had been tested when it had been greased.
STATION_DEMOTE = ((r"^replenish\b", "process"),)


def sfis_kind(station=None, section=None) -> str:
    """What kind of evidence an SFIS process event is.

    Worth carrying on every record because ``PASS`` at ``Assy3`` and ``PASS`` at
    ``Sohu Module Test`` are not the same evidence. A failure investigation that
    reads an assembly scan as a test result concludes the part was tested when it
    was only installed — and only ``kind`` stops that. It is also what gates
    inheritance: a parent's assembly scan says nothing about the child, a
    parent's *test* says a great deal.
    """
    text = (station or "").strip().lower()
    for pattern, kind in STATION_DEMOTE:
        if re.search(pattern, text):
            return kind
    key = (section or "").strip().lower()
    if key in SECTION_KINDS:
        return SECTION_KINDS[key]
    for pattern, kind in STATION_KINDS:
        if re.search(pattern, text):
            return kind
    return "other"


#: Result spellings, normalised. SFIS says ``PASS``, EOS's event stream says
#: ``PASS``/``FAIL`` inside a ``COMPLETE``/``ERROR`` status, and this repo's
#: verdict resolver says ``pass``. A file where the same fact must be grepped
#: two ways is a defect, so everything lands in one vocabulary here.
_RESULTS = {
    "pass": "pass", "passed": "pass", "ok": "pass", "0": "pass",
    "fail": "fail", "failed": "fail", "ng": "fail", "1": "fail",
    "error": "error", "abort": "error", "aborted": "error", "timeout": "error",
    "skip": "skip", "skipped": "skip", "interrupted": "skip",
    "unknown": "unknown", "": "unknown",
}


def result(value) -> str:
    return _RESULTS.get(str(value or "").strip().lower(), "other")
