"""Part SN -> test records: the three tiers, and why a part gets the tier it gets.

WHAT THIS MODULE DECIDES
------------------------
Given one top-level serial, walk its active genealogy and attach to every part
SN the test evidence that actually applies to it. The hard part is not the walk.
It is being honest about *which* parts can have a test record at all, because a
tree of empty lists looks identical to a broken collector.

THE THREE TIERS
---------------
``direct``
    A record whose own DUT / unit serial **is** this part SN. Two ways this
    happens, and both are real:

    * SFIS ``process_events`` where ``unit_sn == part_sn``. Only Etched-numbered
      sub-assemblies get these — Pega routes what it serialized.
    * An EOS run where ``dutSerial == part_sn``. For the Sohu module this is the
      interposer barcode (``JE607…``), so the deepest interesting part in the
      product has first-class MLT/SLT records. Verified live: 233 of 282 August
      SLT DUTs are SFIS components.

``inherited``
    No record names this part, but a test ran on an **ancestor** while this part
    was installed in it. This is the only truthful way to attach evidence to a
    DIMM, a NIC, a cold plate or a cable, and it is what a failure investigation
    actually wants: *what did this rack pass while this NIC was in it.*

    Bounded by the edge window ``[valid_from, valid_to)``. Unbounded inheritance
    would hand a swapped-out DIMM the tests that ran after it was removed, which
    is worse than no answer — it is a wrong answer that looks thorough.

``none_expected``
    A vendor-barcode part that no station tests by serial and whose ancestors
    have no tests in the window either. Stated as a verdict, never as an empty
    list, because "nothing tested this" and "we failed to look" are different
    facts and conflating them costs a day of a failure investigation.

AND ONE FLAG THAT IS NOT A TIER
-------------------------------
``traceability_gap`` is a *separate* boolean, not a fifth coverage value, and the
distinction is load-bearing. An **Etched-numbered** serial — something Pega
serialized and therefore routes — with no direct records of its own is an escape
whether or not its parent happened to be tested while it was installed.

Folding it into ``coverage`` hid exactly the cases worth finding: a serialized
board with no route history but a tested parent came out ``inherited_only`` and
read as fine. Coverage answers *what evidence exists*; the flag answers *should
there have been more*. They are different questions and they get different
fields.

WHY THE FIXTURE CAVEAT IS ON EVERY EOS RECORD
---------------------------------------------
EOS records one run per fixture and a module fixture drives eight chips, so a
``fail`` means at least one of eight failed. Records therefore carry
``fixture_scope`` when the run's level is one of the module levels and the DUT is
not the part itself. Reading a fixture verdict as a part verdict understates
yield eightfold on a single-chip escape (measured, see Analysis/src/factory/chips.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import stations

#: Serial shapes that Pega serializes and therefore routes. Observed across
#: every live unit, rack and PV1 as of 2026-08-31: Etched serials are all-digit,
#: 12 or 15 characters, and begin ``26``. Everything else in the genealogy is a
#: vendor barcode (``JCS0R8001057``, ``BR80J1013800059``, ``P140025010007CFG``,
#: ``28G5200357``) or a short vendor number (``705260033``, ``3546300006``).
#: This is a rule about the data, not a spec — if Etched issues a serial outside
#: it, the only symptom is a part reported ``none_expected`` that should have
#: been a ``gap``, so widen it here when that happens.
def is_etched_serial(sn: Optional[str]) -> bool:
    text = (sn or "").strip()
    return text.isdigit() and len(text) in (12, 15) and text.startswith("26")


#: EOS levels whose runs are fixture-scoped rather than unit-scoped.
FIXTURE_LEVELS = frozenset({"module", "slt"})

_FAR_FUTURE = "9999-12-31T23:59:59Z"


def _ts(value: Optional[str]) -> str:
    """Comparable timestamp string. Everything upstream is UTC ISO-8601, so
    lexical order is chronological order — no parsing, no timezone bugs."""
    return (value or "").replace("+00:00", "Z")


@dataclass
class Part:
    """One node of the topology, with its evidence."""

    slot: str
    sn: str
    component_type: str = ""
    component_name: str = ""
    mpn: str = ""
    epn: str = ""
    depth: int = 0
    path: Tuple[str, ...] = ()
    parent_sn: str = ""
    raw_location: Optional[str] = None
    slot_confidence: str = ""
    linked_at: str = ""
    last_seen_at: str = ""
    valid_to: str = ""
    macs: List[str] = field(default_factory=list)
    direct: List[Dict[str, Any]] = field(default_factory=list)
    inherited: List[Dict[str, Any]] = field(default_factory=list)
    coverage: str = "unknown"
    #: Set when Pega serialized this part but has no route history for it. See
    #: the module docstring: orthogonal to ``coverage``, never merged into it.
    traceability_gap: bool = False
    #: True when this part's own ``/api/serial`` payload is in the snapshot. A
    #: part whose lookup failed looks *identical* to a part with no records, and
    #: conflating them made the tool report a traceability escape for a serial it
    #: had simply failed to fetch. Never claim an escape we did not look for.
    observed: bool = False
    #: Coverage of everything *below* this part, so a reader scanning the top of
    #: a 6U can see which branch is untested without opening it. A module whose
    #: own record is only an assembly scan but whose ASIC failed MLT is the case
    #: this exists for — the interesting fact is three levels down.
    subtree: Dict[str, int] = field(default_factory=dict)
    children: List["Part"] = field(default_factory=list)


def _sfis_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for event in payload.get("process_events") or []:
        station = event.get("station")
        section = event.get("section")
        out.append(
            {
                "ts": _ts(event.get("process_ts")),
                "station": station,
                "kind": stations.sfis_kind(station, section),
                "result": stations.result(event.get("result")),
                "route": event.get("route"),
                "section": event.get("section"),
                "line": event.get("line"),
                "source": "sfis",
            }
        )
    return out


def _eos_records(runs: Iterable[Dict[str, Any]], *, own_dut: bool) -> List[Dict[str, Any]]:
    out = []
    for run in runs or ():
        level = (run.get("level") or "").lower()
        record = {
            "ts": _ts(run.get("startedAt")),
            "station": stations.from_eos(level, run.get("suite")),
            "kind": "test",
            "result": stations.result(run.get("result")),
            "source": "eos",
            "level": level,
            "suite": run.get("suite"),
            "release": run.get("version"),
            "run_id": run.get("runId"),
            "dut_sn": run.get("dutSerial"),
        }
        if level in FIXTURE_LEVELS and not own_dut:
            record["fixture_scope"] = True
        out.append(record)
    return out


def _sort(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records.sort(key=lambda r: (r.get("ts") or "", r.get("station") or ""))
    return records


def build(
    root_sn: str,
    *,
    serials: Dict[str, Dict[str, Any]],
    eos_by_dut: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Assemble the graph for one top-level serial.

    ``serials`` maps SN -> the receiver's ``/api/serial/{sn}`` payload. It is
    passed in rather than fetched so this function is pure: the same snapshot
    always produces the same graph, which is what makes a rendered YAML
    diffable across days and reproducible after the upstream is gone.
    """
    eos_by_dut = eos_by_dut or {}
    root_payload = serials.get(root_sn) or {}

    root_direct = _sort(
        _sfis_records(root_payload)
        + _eos_records(eos_by_dut.get(root_sn) or [], own_dut=True)
    )

    parts: List[Part] = []

    def walk(node: Dict[str, Any], parent_sn: str, depth: int, path: Tuple[str, ...]):
        for child in node.get("children") or []:
            sn = str(child.get("serial") or "")
            slot = str(child.get("slot") or child.get("component_type") or "?")
            here = path + (slot,)
            # The receiver's tree carries slot/type/serial/valid_from; the flat
            # `current_children` list carries mpn/epn/mac for the *root's* direct
            # children only. Deeper nodes therefore look up their own payload for
            # those attributes when we have it, and go without when we do not.
            own = serials.get(sn) or {}
            meta = _child_meta(serials.get(parent_sn) or {}, sn) or {}
            part = Part(
                slot=slot,
                sn=sn,
                component_type=str(child.get("component_type") or ""),
                component_name=str(meta.get("component_name") or ""),
                mpn=str(meta.get("mpn") or ""),
                epn=str(meta.get("epn") or ""),
                depth=depth + 1,
                path=here,
                parent_sn=parent_sn,
                raw_location=child.get("raw_location"),
                slot_confidence=str(meta.get("slot_confidence") or ""),
                linked_at=_ts(child.get("valid_from") or meta.get("valid_from")),
                last_seen_at=_ts(meta.get("last_seen_at")),
                macs=_split_macs(meta.get("macaddress")),
                direct=_sort(
                    _sfis_records(own)
                    + _eos_records(eos_by_dut.get(sn) or [], own_dut=True)
                ),
            )
            parts.append(part)
            walk(child, sn, depth + 1, here)

    walk(root_payload.get("current_tree") or {}, root_sn, 0, ())

    # --- tier 2: inheritance, bounded by the edge window ---------------------
    # Ancestor evidence is indexed by SN so a part at depth 3 inherits from every
    # serial above it, not just its immediate parent: a 6U's L10 FAT run is the
    # relevant evidence for a DIMM three levels down.
    by_sn: Dict[str, Part] = {p.sn: p for p in parts}
    ancestor_records: Dict[str, List[Dict[str, Any]]] = {root_sn: root_direct}
    for part in parts:
        ancestor_records[part.sn] = part.direct

    for part in parts:
        window_start = part.linked_at or ""
        window_end = part.valid_to or _FAR_FUTURE
        inherited: List[Dict[str, Any]] = []
        for ancestor_sn in _ancestor_sns(part, by_sn, root_sn):
            for record in ancestor_records.get(ancestor_sn) or []:
                if record.get("kind") != "test":
                    continue  # an assembly scan on the parent is not a test
                stamp = record.get("ts") or ""
                if window_start and stamp < window_start:
                    continue
                if stamp >= window_end:
                    continue
                copy = dict(record, on=ancestor_sn, via="installed_in")
                if (copy.get("level") or "") in FIXTURE_LEVELS:
                    copy["fixture_scope"] = True
                inherited.append(copy)
        part.inherited = _sort(inherited)

    for part in parts:
        part.observed = part.sn in serials
        part.coverage = _coverage(part)
        # Requires `observed`: a failed lookup is not evidence of a missing
        # route history. Reporting a false escape to Pega costs their time and
        # this report's credibility, which is the only thing making it useful.
        part.traceability_gap = (
            part.observed and is_etched_serial(part.sn) and not part.direct
        )

    _rollup(parts)

    return {
        "root": root_sn,
        "root_direct": root_direct,
        "root_payload": root_payload,
        "parts": parts,
    }


def _rollup(parts: List[Part]) -> None:
    """Tally each part's descendants' coverage onto it."""
    by_path = {part.path: part for part in parts}
    for part in parts:
        cursor = part.path[:-1]
        while cursor:
            ancestor = by_path.get(cursor)
            if ancestor is not None:
                ancestor.subtree[part.coverage] = (
                    ancestor.subtree.get(part.coverage, 0) + 1
                )
                if part.traceability_gap:
                    ancestor.subtree["traceability_gap"] = (
                        ancestor.subtree.get("traceability_gap", 0) + 1
                    )
                fails = sum(
                    1 for r in part.direct if r.get("result") in {"fail", "error"}
                )
                if fails:
                    ancestor.subtree["failing_parts"] = (
                        ancestor.subtree.get("failing_parts", 0) + 1
                    )
            cursor = cursor[:-1]


def _ancestor_sns(
    part: Part, by_sn: Dict[str, Part], root_sn: str
) -> List[str]:
    """Every serial above this part, nearest first."""
    chain = []
    cursor = part.parent_sn
    seen = set()
    while cursor and cursor not in seen:
        seen.add(cursor)
        chain.append(cursor)
        parent = by_sn.get(cursor)
        cursor = parent.parent_sn if parent else ""
    if root_sn not in chain:
        chain.append(root_sn)
    return chain


def _coverage(part: Part) -> str:
    """What evidence exists for this part — nothing about whether more should."""
    if not part.observed:
        # We never fetched this serial, so we cannot claim anything about its own
        # records — and every other coverage value is exactly such a claim.
        # `inherited_only` would assert "no direct records exist", which is the
        # one thing we do not know. Any `inherited_records` on the part are still
        # real: they come from an ancestor we *did* observe.
        return "not_observed"
    if any(r.get("kind") == "test" for r in part.direct):
        return "tested"
    if part.direct:
        return "process_only"
    if part.inherited:
        return "inherited_only"
    return "none_expected"


def _child_meta(parent_payload: Dict[str, Any], sn: str) -> Optional[Dict[str, Any]]:
    """MPN / EPN / MAC / slot confidence for a child, from its parent's payload.

    ``current_children`` is the only place these live, and only for one level.
    Returning ``None`` when the parent payload was not mirrored is deliberate:
    the renderer omits the attribute rather than printing a blank that reads as
    "the vendor left it empty".
    """
    for child in parent_payload.get("current_children") or []:
        if str(child.get("component_sn") or "") == sn:
            return child
    return None


def _split_macs(value: Optional[str]) -> List[str]:
    """Split on ``;``. Never treat the field as one address: MB rows carry three
    and PDU rows two, and a single-value read silently drops the rest."""
    if not value:
        return []
    return [chunk.strip() for chunk in str(value).split(";") if chunk.strip()]


def gaps(graph: Dict[str, Any]) -> Dict[str, Any]:
    """The findings worth acting on, pulled out of one graph."""
    parts: List[Part] = graph["parts"]
    return {
        "serialized_without_records": [
            {"slot": p.slot, "sn": p.sn, "type": p.component_type,
             "coverage": p.coverage, "path": list(p.path)}
            for p in parts
            if p.traceability_gap
        ],
        "slot_position_unknown": [
            {"slot": p.slot, "sn": p.sn, "type": p.component_type}
            for p in parts
            if p.slot_confidence == "missing_location"
        ],
        "no_evidence_at_all": [
            {"slot": p.slot, "sn": p.sn, "type": p.component_type}
            for p in parts
            if p.coverage == "none_expected" and not p.traceability_gap
        ],
        # Not a finding about the product — a finding about this snapshot. Kept
        # beside the others so a reader cannot mistake an incomplete mirror for
        # a clean bill of health.
        "not_observed": [
            {"slot": p.slot, "sn": p.sn, "type": p.component_type}
            for p in parts
            if p.coverage == "not_observed"
        ],
    }


def history(
    graph: Dict[str, Any], serials: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Every part that has been swapped out of this unit, flat and at the top.

    Why flat rather than nested per part: the part that was replaced is *not in
    the current tree*, so there is no node to hang it on. Nesting it under the
    slot's current occupant would read as that occupant's history, which is the
    opposite of true.

    Why it matters more than it looks: "this rack failed and slot 3 has been
    changed twice" is a different investigation from "this rack failed". The
    receiver derives these because Pega sends no explicit DELINK for a swap —
    a later LINK into an occupied slot closes the old edge
    (``inferred_replaced_by_link``) and writes an ``inferred_replacements`` row.

    Sources, both from the receiver: ``inferred_replacements`` (1-for-1 swaps it
    detected) and ``previous_children`` (any closed edge, with why it closed).

    Coverage note: no unit mirrored so far has any replacement history, so this
    is exercised by ``tests/test_graph.py`` against the receiver's documented
    schema rather than validated against live data. Treat the field names as the
    thing to re-check first if it ever renders empty when the UI shows a swap.
    """
    subtree = {part.sn for part in graph["parts"]} | {graph["root"]}
    rows: List[Dict[str, Any]] = []
    for sn in sorted(subtree):
        payload = serials.get(sn) or {}
        for entry in payload.get("inferred_replacements") or []:
            rows.append(
                {
                    "parent_sn": entry.get("parent_sn") or sn,
                    "slot": entry.get("normalized_slot"),
                    "type": entry.get("component_type"),
                    "removed_sn": entry.get("old_component_sn"),
                    "installed_sn": entry.get("new_component_sn"),
                    "at": _ts(entry.get("replaced_at")),
                    "detected_by": entry.get("reason"),
                }
            )
        for entry in payload.get("previous_children") or []:
            # Skip the ones already reported as a 1-for-1 swap above.
            if any(
                row["removed_sn"] == entry.get("component_sn")
                and row["slot"] == entry.get("normalized_slot")
                for row in rows
            ):
                continue
            rows.append(
                {
                    "parent_sn": entry.get("parent_sn") or sn,
                    "slot": entry.get("normalized_slot"),
                    "type": entry.get("component_type"),
                    "removed_sn": entry.get("component_sn"),
                    "installed_sn": None,
                    "at": _ts(entry.get("valid_to")),
                    "detected_by": entry.get("ended_reason"),
                }
            )
    rows.sort(key=lambda row: (row.get("at") or "", row.get("slot") or ""))
    return rows


def counts(graph: Dict[str, Any]) -> Dict[str, int]:
    tally: Dict[str, int] = {}
    for part in graph["parts"]:
        tally[part.coverage] = tally.get(part.coverage, 0) + 1
        if part.traceability_gap:
            tally["traceability_gap"] = tally.get("traceability_gap", 0) + 1
    tally["parts"] = len(graph["parts"])
    return tally
