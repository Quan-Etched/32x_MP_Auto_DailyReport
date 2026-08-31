"""The tier logic, on hand-built payloads shaped like the receiver's real ones.

These are the rules that decide what a reader is told about a part, so they are
tested against constructed data rather than only observed against live data:
a live check tells you today's answer, a fixture tells you the rule.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shopfloor import graph

ROOT = "268947020002"
MODULE = "268862090001"          # Etched-serialized: Pega routes it
COLDPLATE = "SW5VBJ"             # vendor barcode: nothing tests it by SN
SOHU = "JE60702845202602090204"  # vendor barcode, but EOS tests it directly
ORPHAN = "268999990001"          # Etched-serialized with no records at all


def payload(sn, children=(), process=(), kids_meta=()):
    return {
        "serial": sn,
        "process_events": [
            {"unit_sn": sn, "process_ts": ts, "station": st, "section": sec,
             "result": res, "route": "PIW0"}
            for ts, st, sec, res in process
        ],
        "current_children": list(kids_meta),
        "current_tree": {"serial": sn, "children": list(children)},
    }


def node(slot, sn, ctype, valid_from, children=()):
    return {"slot": slot, "serial": sn, "component_type": ctype,
            "raw_location": None, "valid_from": valid_from,
            "children": list(children)}


def fixture():
    sohu = node("BO_0", SOHU, "BO", "2026-08-24T10:00:00Z")
    coldplate = node("Cold_Plate_0", COLDPLATE, "COP", "2026-08-26T01:00:00Z")
    orphan = node("XX_0", ORPHAN, "MB", "2026-08-26T01:00:00Z")
    module = node("GPUM_3", MODULE, "GPUM", "2026-08-28T05:00:00Z",
                  [sohu, coldplate, orphan])
    # A real snapshot holds one /api/serial payload per node in the tree, leaves
    # included — `mirror.collect_sfis` walks the whole tree, because MPN/MAC/slot
    # attributes are only exposed one level at a time. The leaf payloads below
    # are what "we looked and there was nothing" looks like, as distinct from
    # a serial missing from the snapshot entirely.
    serials = {
        ROOT: payload(ROOT, [module],
                      process=[("2026-08-29T00:00:00Z", "Assy1", "ASSY", "PASS")],
                      kids_meta=[{"component_sn": MODULE, "component_name": "SOHU MOD",
                                  "mpn": "NONE", "slot_confidence": "location"}]),
        MODULE: payload(MODULE, [sohu, coldplate, orphan],
                        process=[("2026-08-27T07:43:10Z", "Sohu Module Test", "TEST", "PASS"),
                                 ("2026-08-26T01:59:35Z", "Replenish PG25", "TEST", "PASS")],
                        kids_meta=[{"component_sn": SOHU, "component_name": "INTERPOSER BOARD SOHU CHIP",
                                    "slot_confidence": "missing_location"},
                                   {"component_sn": COLDPLATE, "component_name": "COLDPLATE",
                                    "slot_confidence": "location"}]),
        SOHU: payload(SOHU),
        COLDPLATE: payload(COLDPLATE),
        ORPHAN: payload(ORPHAN),
    }
    eos = {SOHU: [{"runId": "mlt_x_20260815", "level": "slt", "suite": "mlt",
                   "dutSerial": SOHU, "startedAt": "2026-08-15T21:46:03Z",
                   "version": "2026.220.0", "result": "fail"}]}
    return serials, eos


def build():
    serials, eos = fixture()
    return graph.build(ROOT, serials=serials, eos_by_dut=eos)


def by_sn(built):
    return {p.sn: p for p in built["parts"]}


def test_direct_eos_record_on_a_part_sn():
    part = by_sn(build())[SOHU]
    assert part.coverage == "tested", part.coverage
    assert [r["station"] for r in part.direct] == ["MLT"]
    assert part.direct[0]["result"] == "fail"
    # A module-level run is one fixture over eight chips. When the part IS the
    # DUT the caveat does not apply, and claiming it would understate the result.
    assert "fixture_scope" not in part.direct[0]


def test_vendor_part_inherits_only_real_tests_from_its_parent():
    part = by_sn(build())[COLDPLATE]
    assert part.coverage == "inherited_only", part.coverage
    stations = [r["station"] for r in part.inherited]
    assert "Sohu Module Test" in stations
    # Greasing the TIM cell is not evidence the coldplate was tested.
    assert "Replenish PG25" not in stations
    assert all(r["on"] == MODULE for r in part.inherited)


def test_inheritance_is_bounded_by_the_edge_window():
    """A part installed after a test ran must not inherit that test."""
    serials, eos = fixture()
    # Move the coldplate's link to *after* the module test.
    for container in (serials[ROOT], serials[MODULE]):
        for child in container["current_tree"]["children"]:
            for grandchild in child.get("children") or []:
                if grandchild["serial"] == COLDPLATE:
                    grandchild["valid_from"] = "2026-08-30T00:00:00Z"
            if child["serial"] == COLDPLATE:
                child["valid_from"] = "2026-08-30T00:00:00Z"
    built = graph.build(ROOT, serials=serials, eos_by_dut=eos)
    part = by_sn(built)[COLDPLATE]
    assert part.inherited == [], [r["station"] for r in part.inherited]
    assert part.coverage == "none_expected"


def test_serialized_part_with_no_route_history_is_flagged_even_when_covered():
    """The regression this split exists for.

    ORPHAN is Etched-serialized and has no records of its own, but its parent was
    tested while it was installed — so its *coverage* is legitimately
    `inherited_only`. Folding the escape into `coverage` made it read as fine.
    """
    parts = by_sn(build())
    assert parts[ORPHAN].coverage == "inherited_only"
    assert parts[ORPHAN].traceability_gap is True
    assert parts[COLDPLATE].traceability_gap is False   # vendor barcode, expected
    assert parts[MODULE].traceability_gap is False      # serialized and routed
    found = {row["sn"] for row in graph.gaps(build())["serialized_without_records"]}
    assert found == {ORPHAN}


def test_process_only_is_distinguished_from_tested():
    """The module's own SFIS record includes a real test, so it is `tested`;
    a unit with only assembly scans must not be."""
    built = build()
    assert by_sn(built)[MODULE].coverage == "tested"
    root_kinds = {r["kind"] for r in built["root_direct"]}
    assert root_kinds == {"assembly"}


def test_subtree_rollup_surfaces_a_failure_from_three_levels_down():
    part = by_sn(build())[MODULE]
    assert part.subtree.get("tested") == 1
    assert part.subtree.get("failing_parts") == 1, part.subtree


def test_a_failed_lookup_is_not_reported_as_a_traceability_escape():
    """The regression that matters most to anyone downstream.

    ORPHAN is Etched-serialized with no records, which is a real escape *when we
    looked*. Drop its parent's payload from the snapshot and we did not look —
    reporting an escape then sends Pega a false positive, which costs their time
    and the report's credibility.
    """
    serials, eos = fixture()
    built = graph.build(ROOT, serials=serials, eos_by_dut=eos)
    assert by_sn(built)[ORPHAN].traceability_gap is True   # we looked: real

    # Now simulate the lookups that failed: the snapshot has the tree (it came
    # from MODULE's parent) but MODULE's children's own payloads never arrived.
    partial = {ROOT: serials[ROOT], MODULE: serials[MODULE]}
    built = graph.build(ROOT, serials=partial, eos_by_dut=eos)
    parts = by_sn(built)
    assert parts[ORPHAN].traceability_gap is False
    assert parts[ORPHAN].coverage == "not_observed"
    assert graph.gaps(built)["serialized_without_records"] == []
    assert {row["sn"] for row in graph.gaps(built)["not_observed"]} >= {ORPHAN}


def test_replacement_history_is_flat_and_names_both_serials():
    """Shaped from the receiver's documented schema, not from live data — no unit
    mirrored so far has a swap, so this fixture is the only thing holding the
    field names honest."""
    serials, eos = fixture()
    serials[MODULE]["inferred_replacements"] = [{
        "parent_sn": MODULE, "normalized_slot": "Cold_Plate_0",
        "component_type": "COP", "old_component_sn": "SW5OLD",
        "new_component_sn": COLDPLATE, "replaced_at": "2026-08-25T00:00:00Z",
        "reason": "new_link_same_parent_slot",
    }]
    serials[MODULE]["previous_children"] = [{
        "parent_sn": MODULE, "normalized_slot": "BO_9", "component_type": "BO",
        "component_sn": "JE60700000000000000000",
        "valid_to": "2026-08-20T00:00:00Z", "ended_reason": "explicit_delink",
    }]
    built = graph.build(ROOT, serials=serials, eos_by_dut=eos)
    rows = graph.history(built, serials)
    assert len(rows) == 2, rows
    swap = next(r for r in rows if r["slot"] == "Cold_Plate_0")
    assert swap["removed_sn"] == "SW5OLD" and swap["installed_sn"] == COLDPLATE
    assert swap["detected_by"] == "new_link_same_parent_slot"
    removal = next(r for r in rows if r["slot"] == "BO_9")
    assert removal["installed_sn"] is None
    assert removal["detected_by"] == "explicit_delink"
    # Sorted oldest first, so a history reads as a timeline.
    assert [r["at"] for r in rows] == sorted(r["at"] for r in rows)


def test_missing_location_is_reported():
    found = {row["sn"] for row in graph.gaps(build())["slot_position_unknown"]}
    assert SOHU in found


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print("graph: ok" if not failures else f"graph: {failures} FAILED")
    sys.exit(1 if failures else 0)
