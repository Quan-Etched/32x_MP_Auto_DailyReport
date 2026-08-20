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
    ("Bootloader / Secure Boot", ["bootloader", "secureboot", "recovery",
                                 "boot loop", "cec173", "devik"]),
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
                                "cpldfirmware", "hotreload",
                                # The controllers' own ids for the same updates.
                                "plx_daemon", "plxdaemon", "vbb_update",
                                "vbbupdate", "bios_boot", "biosboot",
                                "bios_ver", "biosver"]),
    ("Provisioning", ["softwareprovisioning", "provision"]),
    ("Memory Check", ["checkmemory"]),
    ("NIC / Link", ["checknic", "interfacelinkstatus", "loopbacktopology",
                   "lom_nic", "lomnic", "nic_mac", "nicmac"]),
    ("Host / Reboot", ["hostreboot"]),
    ("Model Staging", ["stagemodelregistry"]),
    ("Disk", ["diskstress", "chk_disk", "chkdisk"]),

    # --- Added here, not yet in test-daily -------------------------------
    # Signatures that only show up in the EOS payload. They were the largest
    # remaining "Other" contributors; port these back to
    # test-daily/tools/build_dashboard.py to keep the two dashboards agreeing.
    ("RDQS Training", ["rdqssweep"]),
    ("VRM", ["vrmtestcase", "setupvrm"]),
    ("PCIe Setup", ["pciesetup", "pcie_topology", "pcietopology"]),
    ("DTS / Thermal sensor", ["dtstestcase"]),
    ("PEX Firmware", ["pexfirmware"]),
    ("System Log", ["systemlogstates"]),
    ("MLP / Collective", ["mlptp", "collective"]),

    # --- The controllers' own test ids -----------------------------------
    # Everything above was written against EOS class names — SohuWeightLoadTestCase
    # squashes to "weightloadtestcase" and matches "weightload". The controllers
    # emit the *test id* instead: "weight_load", "chip_bin", "all_attn_tests".
    # No rule mentioned those, so they fell through, and "Other" became a third
    # of every failure on the page — the largest bar on a chart whose whole job
    # is to say where to look, naming nothing and pointing at nobody.
    #
    # These are the signatures that were actually in there, in descending order
    # of how often they failed over thirty days. They are grouped by who would
    # own the fix rather than by which test emitted them, which is the only
    # grouping a Pareto is any use for.
    ("Attention / KV Flush", ["all_attn", "allattn", "kv_flush", "kvflush",
                              "attention"]),
    ("SA Screening", ["sa_column_screen", "sacolumnscreen", "sascreening"]),
    ("Weight Load", ["weight_load", "weightload"]),
    ("Chip ID / eFuse / Bin", ["chip_bin", "chipbin", "chip_id", "chipid",
                               "efuse"]),
    ("DMA", ["_dma", "dma_", "sohudma"]),
    ("SAU PLL / Clocking", ["sau_pll", "saupll", "phase_alignment",
                            "set_clock_profile", "setclockprofile"]),
    ("DVFS / Board Profile", ["dvfs"]),
    ("GPIO", ["gpio"]),
    ("PCIe Lane Margin", ["lane_margin", "lanemargin"]),
    ("HBM Device ID", ["hbm_device_id", "hbmdeviceid"]),
    ("SRAM", ["sram"]),
    ("Flash / Init Config", ["flash_init", "flashinit", "clear_flash"]),
    ("BMC / Power Cycle", ["bmc_pwr", "bmcpwr", "bmc_power", "pwr_cycle",
                           "bmc_check", "bmccheck"]),
    ("OS / Packages", ["linux_packages", "linuxpackages", "nfs_mount",
                       "nfsmount"]),
    ("PSU", ["psu_fw", "psufw", "checkpsu"]),

    # The L10 host checks. Individually small — a dozen or two each — and one
    # family: is the server underneath the chassis healthy enough to test on.
    # Grouped rather than split into fifteen bars of twelve, which would be the
    # "Other" mistake again at a smaller scale.
    ("CPU / Stress", ["chk_cpu", "chkcpu", "cpu_stress", "cpustress",
                      "io_stress", "iostress", "in_host_stress"]),
    ("Server Health", ["server_online", "serveronline", "no_error_log",
                       "noerrorlog", "baseboard"]),
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


#: The per-run noise on a controller test id: an 8-hex run hash, then often a
#: chip index. ``4cce7997_chip5_sram_memory`` and ``162b9d25_chip1_sram_memory``
#: are the same test failing on two runs, and counting them apart turns one
#: signature with a hundred failures into a hundred signatures with one.
RUN_PREFIX = re.compile(r"^[0-9a-f]{6,10}_(chip\d+_|sohu_)?", re.IGNORECASE)


def signature(*signals: Optional[str]) -> str:
    """The test id with its per-run prefix removed, for grouping and display.

    Deliberately not used for bucketing — ``area`` matches on substrings and
    does not care about the prefix. This is for the breakdown under the Pareto,
    where the reader is being shown a list of test names and a list of a
    hundred run-stamped ones is not a list of anything.
    """
    for signal in signals:
        text = (signal or "").strip()
        if text:
            return RUN_PREFIX.sub("", text) or text
    return ""


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
