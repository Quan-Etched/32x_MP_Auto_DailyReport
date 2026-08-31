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
The (level, suite) -> station half is **not reimplemented here**. It lives in
``Analysis/src/factory/stations.py``, where it is verified against a 30-day live
window and already handles the renames — ``L10_6U_FAT`` -> ``L10_FAT`` at
release 220, HTT running under ``rdqs_sweep_training``, MLT appearing under both
``module`` and ``slt``. A second copy would be wrong the first time the line
renames a suite, and nobody would notice which copy was stale.

So this module imports ``classify()`` and adds only what Analysis has no reason
to know: the SFIS route-station half, which Analysis never sees.

If Analysis is not on the box, ``FALLBACK`` keeps the tool working with a much
coarser map, and ``registry_source()`` says which one is in use — so a reader can
tell a canonical station name from a best guess.
"""

from __future__ import annotations

import re
import sys
from typing import Optional, Tuple

from . import config

_classify = None
_source = "fallback"

try:  # Analysis's registry is the source of truth when it is reachable.
    if str(config.ANALYSIS_SRC) not in sys.path:
        sys.path.insert(0, str(config.ANALYSIS_SRC))
    from factory.stations import classify as _classify  # type: ignore
    from factory.stations import label_of as _label_of  # type: ignore

    _source = f"Analysis ({config.ANALYSIS_SRC})"
except Exception:  # ImportError, or a factory package that moved
    _label_of = None

#: Coarse (level, suite-pattern) -> label, used only when Analysis is absent.
FALLBACK: Tuple[Tuple[str, str, str], ...] = (
    ("slt", r"^mlt", "MLT"),
    ("module", r"^mlt", "MLT"),
    ("module", r"^(htt_)?rdqs_sweep_training$", "HTT"),
    ("module", r"^baking$|^tim$", "TIM"),
    ("slt", r"^slt", "SLT"),
    ("slt", r"^chip_screening", "Chip Screening"),
    ("l10", r"FAT$", "L10 FAT"),
    ("l10", r"SFT$", "L10 SFT"),
    ("l10", r"RIN$", "L10 RIN"),
    ("l10", r"^L10_2U$", "L10 2U"),
    ("l6", r"vbb", "VBB Provisioning"),
    ("l11", r".", "L11"),
)


def registry_source() -> str:
    """Which mapping is live. Written into every snapshot manifest."""
    return _source


def from_eos(level: Optional[str], suite: Optional[str]) -> str:
    """Station label for an EOS run.

    Falls back to ``level/suite`` rather than to a guess: an unrecognised suite
    is a new or renamed stage, and printing the raw pair is how somebody notices
    and adds it. Silently bucketing it as "other" is how a station disappears
    from a yield report for a month.
    """
    if _classify is not None:
        key = _classify(level, suite)
        if _label_of is not None:
            label = _label_of(key)
            if label:
                return label
        if key and key not in {"unclassified", "engineering"}:
            return key
    for want_level, pattern, label in FALLBACK:
        if (level or "").lower() == want_level and re.search(
            pattern, suite or "", re.I
        ):
            return label
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
