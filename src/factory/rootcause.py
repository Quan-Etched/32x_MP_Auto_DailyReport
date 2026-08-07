"""Failure signature -> root-cause area.

Ported verbatim from ``test-daily/tools/build_dashboard.py`` (``RC_RULES``) so
that the "Top yield hits" Pareto here buckets failures **identically** to the
existing daily dashboard. If the two ever disagree, the same failure appears
under two different area names in two places and nobody trusts either — so keep
them in sync, and change both together.

Rules are ordered and first-match-wins: the MLT buckets come first and keep
priority on any substring shared with the L10 families appended after them.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

RC_RULES: Sequence[Tuple[str, Sequence[str]]] = [
    ("PMBIST", ["pmbist"]),
    ("C2C", ["c2c"]),
    ("Power Virus / Thermal", ["powervirus", "thermal"]),
    ("PCIe AER", ["aercheck", "aer "]),
    ("VFIO / VM", ["vfio", "sohuvm", "vmtest"]),
    ("Llama / SaSort", ["llama", "sasort"]),
    ("Bootloader / Secure Boot", ["bootloader", "secureboot", "recovery", "boot loop"]),
    ("Lane Repair", ["lanerepair"]),
    ("FLR", ["flr"]),
    ("MTC Stress", ["mtcstress"]),
    ("Enumeration / BAR / I2C", ["no bar", "enumerat", "i2ctest", "rpc proxy"]),
    ("Mezzanine / HW", ["mezz", "mezzanine"]),
    ("Process Detector", ["pdtestcase", "sohupd"]),
    ("MTT", ["mtt"]),
    ("Device Info / SA mask", ["sa mask", "deviceinfo"]),
    # L10 6U system-test families (FAT is mostly firmware/provisioning, SFT is
    # content). Appended, so the MLT buckets above keep priority.
    ("Firmware / BIOS Update", ["firmwareupdate", "biosupdate", "broadcomupdate",
                                "cpldfirmware", "hotreload"]),
    ("Provisioning", ["softwareprovisioning", "provision"]),
    ("Memory Check", ["checkmemory"]),
    ("NIC / Link", ["checknic", "interfacelinkstatus", "loopbacktopology"]),
    ("Host / Reboot", ["hostreboot"]),
    ("Model Staging", ["stagemodelregistry"]),
    ("Disk", ["diskstress"]),

    # --- Added here, not yet in test-daily -------------------------------
    # Signatures that only show up in the EOS payload. They were the largest
    # remaining "Other" contributors; port these back to
    # test-daily/tools/build_dashboard.py to keep the two dashboards agreeing.
    ("RDQS Training", ["rdqssweep"]),
    ("VRM", ["vrmtestcase", "setupvrm"]),
    ("PCIe Setup", ["pciesetup"]),
    ("DTS / Thermal sensor", ["dtstestcase"]),
    ("PEX Firmware", ["pexfirmware"]),
    ("System Log", ["systemlogstates"]),
    ("MLP / Collective", ["mlptp", "collective"]),
]

OTHER = "Other"

#: Parent nodes in the test tree, not failure signatures. EOS emits one entry
#: per nested container (``SltModuleNestedTestCase`` for a chip,
#: ``ServerNestedTestCase`` for a phase) alongside the real leaf tests, and a
#: container "fails" purely because something under it failed. Counting both
#: double-counts every failure and buries the real causes — these were 63% of
#: the unmatched bucket. ``parent_id`` is null on every entry observed, so the
#: class-name suffix is the only marker available.
CONTAINER_SUFFIXES = ("nestedtestcase",)


def is_container(*signals: Optional[str]) -> bool:
    """True when a failure entry is an aggregate parent rather than a real test."""
    for signal in signals:
        if not signal:
            continue
        text = re.sub(r"[\s_\-./]+", "", str(signal).lower())
        if text.endswith(CONTAINER_SUFFIXES):
            return True
    return False


def area(*signals: Optional[str]) -> str:
    """Bucket a failure into a root-cause area.

    Pass every string that might carry the signature — EOS gives a stable
    ``unique_id`` (``CHK_BIOS_BOOT_ORDER``), a class name
    (``CheckBiosBootOrder``) and often an error code, and the keyword may live
    in any of them.

    Matching is done twice: once on the raw lowercased text, and once with
    separators removed. The rules were written against CamelCase class names
    (``SohuServerBiosUpdate`` -> ``biosupdate``), so a snake_case id like
    ``update_bmc_bios`` only matches after ``_``/``-``/space are stripped.
    Without that pass, most EOS identifiers fall through to "Other" and the
    Pareto says nothing.
    """
    raw = " ".join(str(s) for s in signals if s).lower()
    if not raw.strip():
        return OTHER
    squashed = re.sub(r"[\s_\-./]+", "", raw)
    for name, keys in RC_RULES:
        for key in keys:
            if key in raw:
                return name
            stripped = re.sub(r"[\s_\-./]+", "", key)
            if stripped and stripped in squashed:
                return name
    return OTHER


def areas() -> List[str]:
    return [name for name, _ in RC_RULES] + [OTHER]
