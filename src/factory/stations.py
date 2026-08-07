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

Verified against a 30-day window on 2026-08-07.
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
        }


#: Ordered as the line runs: module test -> chip screening -> SLT -> L10 -> L11.
STATIONS: List[Station] = [
    Station(
        key="mlt", label="MLT", level="module", order=10,
        patterns=[r"^mlt$", r"^sohu_mlt", r"^mlt_\d+$"],
        note="Module-level test. 210 runs in the 30 days to 2026-08-07.",
    ),
    Station(
        key="htt", label="HTT", state=UNMAPPED, order=20,
        note="No suite matching HTT exists in EOS at any level "
             "(searched suite, version, runId and prefix over 30 days). "
             "Add the suite name to this registry entry and it starts working.",
    ),
    Station(
        key="chip_screening", label="Chip Screening", levels=("slt", "module"), order=30,
        patterns=[r"^chip_screening"],
        note="Runs at both slt and module level.",
    ),
    Station(
        key="slt", label="SLT", levels=("slt", "l6"), order=40,
        patterns=[r"^slt$", r"^sohu_slt$", r"^slt_\d+"],
        note="System-level test.",
    ),
    Station(
        key="l10_fat", label="L10 FAT", levels=("l10", "l6"), order=50,
        patterns=[r"^L10_6U_FAT$", r"^FAT$"],
        note="Final assembly test. Debug variants (L10_6U_FAT_krish, "
             "L10_6U_FAT_debug_krish) are deliberately excluded — they are "
             "engineering runs and would distort yield.",
    ),
    Station(
        key="l10_sft", label="L10 SFT", levels=("l10", "l6"), order=60,
        patterns=[r"^L10_6U_SFT$", r"^SFT$"],
        note="System function test.",
    ),
    Station(
        key="l10_rin", label="L10 RIN", levels=("l10", "l6"), order=70,
        patterns=[r"^L10_6U_RIN$", r"^RIN$"],
        note="Run-in. Low volume — 10 runs in 30 days, so most days are a "
             "thin sample.",
    ),
    Station(
        key="l11_provision", label="L11 Provision", level="l11",
        state=BLOCKED, order=80,
        patterns=[r"provision"],
        note="EOS returns HTTP 502: the API key's IAM role is denied "
             "s3:ListBucket on etched-mfg-prod-l11-raw. The suite pattern is "
             "an unverified guess and must be confirmed once access is granted.",
    ),
    Station(
        key="l11_test", label="L11 Test", level="l11",
        state=BLOCKED, order=90,
        patterns=[r"^L11", r"test"],
        note="Blocked by the same IAM denial as L11 Provision. Pattern unverified.",
    ),
]

#: Runs that match no station. Kept visible rather than dropped — a suite that
#: nobody has mapped is a finding, not noise.
UNCLASSIFIED = "unclassified"

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
    """Return the station key for a run, or :data:`UNCLASSIFIED`.

    First match in registry order wins, so the ordering above is meaningful:
    narrower patterns must come before broader ones.
    """
    for station in STATIONS:
        if station.matches(level, suite):
            return station.key
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
