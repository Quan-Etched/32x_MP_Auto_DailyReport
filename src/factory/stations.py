"""The station registry — the line's vocabulary, mapped onto EOS.

"Station" here means a test stage on the line (MLT, L10 FAT, …), which is what
the floor calls it. It is NOT a physical fixture: EOS exposes no fixture field
(see docs/api-usage.md). A station is identified by an EOS ``level`` plus a
match on ``suite``.

Every station the line cares about is listed, including ones that produce no
data today, so the dashboard can say *why* a station is empty instead of
silently omitting it. Three states:

``active``   mapped to a suite that EOS is serving
``unmapped`` the line runs it, but no matching suite name has been found in EOS
``blocked``  the suite exists but the API key cannot read that level's bucket

Verified against a 30-day window on 2026-08-11.

Suite names are not stable over time: around release 220 (2026-08-10) the L10
suites dropped the ``6U_`` infix (``L10_6U_FAT`` -> ``L10_FAT``), and HTT looks
to be gaining an ``htt_`` prefix (a ``htt_rdqs_sweep_training`` run appeared on
2026-08-12 under the DUT serial ``RENAME_TEST_0``). Patterns here accept both
spellings, and should keep accepting both — a pattern that only matches today's
name silently zeroes a station the next time the line renames one.

**The suite name is not the station name.** HTT runs under
``rdqs_sweep_training``; nothing in that string says HTT. The mapping is
verifiable only from the FAMILY column of the OCP Logs UI, which EOS itself does
not serve — ``/runs`` returns seven fields and family is not among them (see
docs/api-usage.md). So "no suite matching X exists" is evidence about a string,
never proof that a station is absent; check the family column before recording a
station as unmapped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

ACTIVE = "active"
UNMAPPED = "unmapped"
BLOCKED = "blocked"


class Station:
    """One test stage on the line."""

    def __init__(
        self,
        key: str,
        label: str,
        level: Optional[str] = None,
        patterns: Sequence[str] = (),
        levels: Sequence[str] = (),
        state: str = ACTIVE,
        note: str = "",
        order: int = 0,
        controller: str = "",
    ) -> None:
        self.key = key
        self.label = label
        #: Some stages appear under more than one level (chip screening runs at
        #: both slt and module), so matching is on a set of levels.
        self.levels = tuple(levels) if levels else ((level,) if level else ())
        self.patterns = tuple(re.compile(p, re.I) for p in patterns)
        self.state = state
        self.note = note
        self.order = order
        #: The ESVM host that drives this stage — pega2 provisions VBB boards,
        #: pega3 the module stations, pega4 L10, pega5 L11. Recorded because it
        #: is the authority on what a station *is*: EOS shows a run's level and
        #: suite, but which physical station ran it is the controller's fact,
        #: and it is what settled the VBB question below.
        self.controller = controller

    def matches(self, level: Optional[str], suite: Optional[str]) -> bool:
        if self.state != ACTIVE or not self.patterns:
            return False
        if self.levels and (level or "").lower() not in self.levels:
            return False
        return any(pattern.match(suite or "") for pattern in self.patterns)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "levels": list(self.levels),
            "state": self.state,
            "note": self.note,
            "order": self.order,
            "controller": self.controller,
        }


#: Ordered as the line runs: module test -> chip screening -> SLT -> L10 -> L11.
STATIONS: List[Station] = [
    Station(
        key="mlt", label="MLT", levels=("module", "slt"), order=10,
        patterns=[r"^mlt$", r"^sohu_mlt", r"^mlt_\d+$"],
        controller="pega3",
        note="Module-level test. Runs under both the module and slt levels: "
             "from 2026-08-11 the same mlt suite began appearing under slt, on "
             "the 22-character JE… serials rather than the 15-digit unit "
             "serials. Same stage — every one of its 135 test-case names is "
             "part of the module-level MLT vocabulary — so the level it lands "
             "under does not change what was tested.",
    ),
    Station(
        key="htt", label="HTT", level="module", order=20,
        # EOS reports the test class (rdqs_sweep_training); pega3 reports the
        # suite it ran under, which is just "htt" once its version is stripped.
        # Both spellings, for the same reason every other station takes both.
        patterns=[r"^(htt_)?rdqs_sweep_training$", r"^htt$"],
        controller="pega3",
        note="Memory training sweep. The suite is named rdqs_sweep_training — "
             "nothing in it says HTT, which is why an earlier search for that "
             "string found nothing and left this station unmapped.",
    ),
    Station(
        key="chip_screening", label="Chip Screening", levels=("slt", "module"), order=30,
        patterns=[r"^chip_screening"],
        controller="pega3",
        note="Runs at both slt and module level.",
    ),
    Station(
        key="slt", label="SLT", levels=("slt", "l6"), order=40,
        patterns=[r"^slt$", r"^sohu_slt$", r"^slt_\d+"],
        controller="pega3",
        note="System-level test.",
    ),
    Station(
        key="l10_fat", label="L10 FAT", levels=("l10", "l6"), order=50,
        patterns=[r"^L10_(6U_)?FAT$", r"^FAT$"],
        controller="pega4",
        note="Final assembly test. 6U chassis, under both the old L10_6U_FAT "
             "and the current L10_FAT name. Debug variants (L10_6U_FAT_krish, "
             "L10_6U_FAT_debug_krish) are deliberately excluded — they are "
             "engineering runs and would distort yield.",
    ),
    Station(
        key="l10_sft", label="L10 SFT", levels=("l10", "l6"), order=60,
        patterns=[r"^L10_(6U_)?SFT$", r"^SFT$"],
        controller="pega4",
        note="System function test. 6U chassis, under both the old L10_6U_SFT "
             "and the current L10_SFT name.",
    ),
    Station(
        key="l10_rin", label="L10 RIN", levels=("l10", "l6"), order=70,
        patterns=[r"^L10_(6U_)?RIN$", r"^RIN$"],
        controller="pega4",
        note="Run-in. Low volume — most days are a thin sample or empty.",
    ),
    Station(
        key="l10_2u", label="L10 2U", levels=("l10", "l6"), order=75,
        patterns=[r"^L10_2U$"],
        controller="pega4",
        note="2U chassis test. A different product from the 6U stations, not a "
             "different stage of it: it shares only 12 of its 27 test cases "
             "with L10 FAT, so its yield is kept separate rather than folded "
             "in. L10_2U_SMOKE (a 2-case smoke test) is excluded.",
    ),
    Station(
        key="vbb_provision", label="VBB Provisioning", level="l6", order=5,
        controller="pega2",
        patterns=[r"^Vbb[A-Z]", r"^vbb_", r"^PROD_\d*_?vbb", r"^CHECK_vbb",
                  r"^PROD_flash_and_lock"],
        note="Provisioning of the VBB board, before module assembly — the first "
             "stage on the line and the largest single group of runs EOS "
             "returns. It sat unclassified for a week because nothing in the "
             "suite names (VbbCec173xProvisioningInternal, "
             "VbbFlashAndLockBootloader, VbbValidateProductionProvisioning) "
             "says which station runs them, and the earlier note asked for the "
             "OCP FAMILY column to settle it.\n\n"
             "pega2 settles it instead: it drives station pt2_l6_vbb1 with DUT "
             "part number PN-VBB and suites PROD_01_vbb_provisioning and "
             "PROD_02_vbb_validate_production_provisioning. A dedicated station, "
             "a dedicated part number and production-prefixed suites are a "
             "production stage, not engineering — so these 289 runs are one, and "
             "counting them as unclassified was hiding the busiest stage on the "
             "line.\n\n"
             "The suite names differ between the two systems (EOS reports the "
             "test-class name, pega2 the suite it ran under), so the patterns "
             "here accept both spellings.",
    ),
    Station(
        key="l11_provision", label="L11 Provision", level="l11",
        state=BLOCKED, order=80,
        patterns=[r"provision"],
        controller="pega5",
        note="EOS returns HTTP 502: the API key's IAM role is denied "
             "s3:ListBucket on etched-mfg-prod-l11-raw. The suite pattern is "
             "an unverified guess and must be confirmed once access is granted.",
    ),
    Station(
        key="l11_test", label="L11 Test", level="l11",
        state=BLOCKED, order=90,
        patterns=[r"^L11", r"test"],
        controller="pega5",
        note="Blocked by the same IAM denial as L11 Provision. Pattern unverified.",
    ),
]

#: Runs that match no station. Kept visible rather than dropped — a suite that
#: nobody has mapped is a finding, not noise.
#:
#: Deliberately left here: ``L10_tests`` (23 runs, 22 of them status=error, on
#: the two engineering DUTs) reads as a dev suite rather than a line stage, and
#: mapping it would put a near-100% failure rate into a station's yield.
UNCLASSIFIED = "unclassified"

#: Runs that are not a line stage at all: debug builds, one-off repros, smoke
#: tests, suites named after a ticket. Kept apart from UNCLASSIFIED because the
#: two mean different things — unclassified is "nobody has worked out what this
#: is", which is a question for somebody, while engineering is "we know exactly
#: what it is and it is not production", which is not. Lumping them together
#: left 39 runs looking like an open question when none of them were, and hid
#: the ones that genuinely are.
#:
#: These are excluded from line-wide yield for the same reason the L10 stations
#: exclude the ``_krish`` debug variants: they run on engineering DUTs and would
#: distort the number.
ENGINEERING = "engineering"

ENGINEERING_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"_krish\b",              # named after the engineer running them
    r"_debug\b",
    r"^L10_tests$",           # dev suite; 22 of its 23 runs are status=error
    r"_SMOKE$",
    r"^selfheal_repro",       # a reproduction, not a stage
    r"_etch\d+$",             # named after a ticket
))

BY_KEY: Dict[str, Station] = {station.key: station for station in STATIONS}


def levels_to_collect() -> List[str]:
    """Every EOS level any active station draws from."""
    levels = set()
    for station in STATIONS:
        if station.state == ACTIVE:
            levels.update(station.levels)
    return sorted(levels)


def blocked_levels() -> List[str]:
    levels = set()
    for station in STATIONS:
        if station.state == BLOCKED:
            levels.update(station.levels)
    return sorted(levels)


def classify(level: Optional[str], suite: Optional[str]) -> str:
    """Return the station key for a run, or :data:`ENGINEERING` / :data:`UNCLASSIFIED`.

    First match in registry order wins, so the ordering above is meaningful:
    narrower patterns must come before broader ones. A run matching no station
    is checked against the engineering patterns before it is called
    unclassified, so "nobody knows what this is" stays a small and meaningful
    list rather than a bin for everything off the production path.
    """
    for station in STATIONS:
        if station.matches(level, suite):
            return station.key
    if any(pattern.search(suite or "") for pattern in ENGINEERING_PATTERNS):
        return ENGINEERING
    return UNCLASSIFIED


def registry() -> List[Dict[str, Any]]:
    return [station.to_dict() for station in sorted(STATIONS, key=lambda s: s.order)]


#: Version strings look like ``2026.207.0-gitd45c8636``; the line calls that
#: release "207". Anything that does not match keeps its full string.
_RELEASE = re.compile(r"^\d{4}\.(\d+)\.")


def release_of(version: Optional[str]) -> Optional[str]:
    """Extract the release number the floor uses from a full version string."""
    if not version:
        return None
    match = _RELEASE.match(str(version))
    return match.group(1) if match else str(version)


def release_sort_key(release: Optional[str]) -> tuple:
    """Numeric where possible, so 9 sorts before 10 rather than after."""
    if release is None:
        return (2, 0, "")
    try:
        return (0, int(release), "")
    except (TypeError, ValueError):
        return (1, 0, str(release))
