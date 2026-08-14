"""Measure the gap between the two station pages, at build time.

WHY THIS IS COMPUTED AND NOT WRITTEN DOWN
------------------------------------------
The two pages disagree, and the first question anyone asks about a yield number
is whether it is right. A paragraph explaining the difference is only as good as
the day someone wrote it; a table computed from both bundles on every build is
still true tomorrow, and it can be pointed at.

So this compares the two payloads the pipeline has just produced and states the
difference per station, in the units the reader is looking at. Nothing here is
asserted — every figure comes from one of the two bundles.

WHAT THE DIFFERENCE IS
----------------------
EOS records **one run per fixture**: one ``dutSerial``, no slot, one status for
eight chips. The controllers record **one result per unit**. So the same eight
modules are one row on one page and eight on the other, and a fixture where one
chip failed is a failure on the first and seven passes plus one failure on the
second.

Neither is wrong. They answer different questions, and the line asks the second.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Stations worth listing even when one side has nothing — an empty L11 on the
#: EOS side is the most load-bearing row in the table.
ALWAYS_SHOW = ("l11_provision", "l11_test")


def _summary(bundle: Dict[str, Any], key: str) -> Dict[str, Any]:
    view = (bundle.get("views") or {}).get(key) or {}
    return view.get("summary") or {}


def _rate(summary: Dict[str, Any]) -> Optional[float]:
    return summary.get("passRate")


def build(eos: Dict[str, Any], pega: Dict[str, Any]) -> Dict[str, Any]:
    """A row per station: what each source says, and by how much they differ."""
    labels = {entry["key"]: entry.get("label", entry["key"])
              for entry in (pega.get("stations") or []) + (eos.get("stations") or [])}

    keys: List[str] = []
    for entry in (eos.get("stations") or []):
        if entry["key"] not in keys:
            keys.append(entry["key"])
    for entry in (pega.get("stations") or []):
        if entry["key"] not in keys:
            keys.append(entry["key"])

    rows = []
    for key in keys:
        if key in ("engineering", "unclassified"):
            continue
        left, right = _summary(eos, key), _summary(pega, key)
        left_runs, right_runs = left.get("runs", 0), right.get("runs", 0)
        if not left_runs and not right_runs and key not in ALWAYS_SHOW:
            continue
        rows.append({
            "key": key,
            "label": labels.get(key, key),
            "eosRuns": left_runs,
            "pegaRuns": right_runs,
            "eosRate": _rate(left),
            "pegaRate": _rate(right),
            # How many records the controllers produce for each EOS one. On the
            # module line this lands near eight, which is the slot count, and
            # that is the whole explanation in one number.
            "expansion": (round(right_runs / left_runs, 1)
                          if left_runs and right_runs else None),
        })

    eos_all, pega_all = _summary(eos, "__all__"), _summary(pega, "__all__")
    return {
        "generatedAt": pega.get("generatedAt"),
        "rows": rows,
        "totals": {
            "eosRuns": eos_all.get("runs", 0),
            "pegaRuns": pega_all.get("runs", 0),
            "eosRate": _rate(eos_all),
            "pegaRate": _rate(pega_all),
            # The unit-yield figure this page already computes from the chip
            # names in EOS. It is derived on one side and measured on the
            # other, so agreement between them is the check that both are
            # describing the same thing.
            "eosUnitYield": ((eos.get("views") or {}).get("__all__") or {})
                            .get("units", {}).get("yield"),
        },
        "sources": {
            "eos": eos.get("dataSource") or {},
            "pega": pega.get("dataSource") or {},
        },
    }
