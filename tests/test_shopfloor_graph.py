"""The tier rules: what a part SN is told about its own test history.

These decide what a reader sees, so they are tested against constructed payloads
rather than only observed against live data — a live check tells you today's
answer, a fixture tells you the rule.

Payload shapes mirror the TY2 receiver's ``/api/serial/{sn}`` response, including
the detail that a real snapshot holds one payload per node in the tree, leaves
included: ``shopfloor.mirror`` walks the whole tree because MPN/MAC/slot
attributes are only exposed one level at a time.
"""

import unittest

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
    """A 4U node → Sohu module → {interposer, cold plate, an unrouted board}."""
    sohu = node("BO_0", SOHU, "BO", "2026-08-24T10:00:00Z")
    coldplate = node("Cold_Plate_0", COLDPLATE, "COP", "2026-08-26T01:00:00Z")
    orphan = node("XX_0", ORPHAN, "MB", "2026-08-26T01:00:00Z")
    module = node("GPUM_3", MODULE, "GPUM", "2026-08-28T05:00:00Z",
                  [sohu, coldplate, orphan])
    serials = {
        ROOT: payload(ROOT, [module],
                      process=[("2026-08-29T00:00:00Z", "Assy1", "ASSY", "PASS")],
                      kids_meta=[{"component_sn": MODULE, "component_name": "SOHU MOD",
                                  "mpn": "NONE", "slot_confidence": "location"}]),
        MODULE: payload(MODULE, [sohu, coldplate, orphan],
                        process=[("2026-08-27T07:43:10Z", "Sohu Module Test", "TEST", "PASS"),
                                 ("2026-08-26T01:59:35Z", "Replenish PG25", "TEST", "PASS")],
                        kids_meta=[{"component_sn": SOHU,
                                    "component_name": "INTERPOSER BOARD SOHU CHIP",
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


class ShopfloorGraph(unittest.TestCase):
    def setUp(self):
        self.serials, self.eos = fixture()
        self.built = graph.build(ROOT, serials=self.serials, eos_by_dut=self.eos)
        self.parts = {p.sn: p for p in self.built["parts"]}

    def rebuild(self, serials=None, eos=None):
        built = graph.build(ROOT, serials=serials or self.serials,
                            eos_by_dut=eos or self.eos)
        return built, {p.sn: p for p in built["parts"]}

    # --- tier 1: direct ----------------------------------------------------

    def test_an_eos_run_attaches_to_the_part_sn_it_names(self):
        """The join the whole tool rests on: EOS files MLT under the interposer
        barcode, which is a component serial in the genealogy."""
        part = self.parts[SOHU]
        self.assertEqual(part.coverage, "tested")
        self.assertEqual([r["station"] for r in part.direct], ["MLT"])
        self.assertEqual(part.direct[0]["result"], "fail")
        # A module run covers eight chips, but when the part IS the DUT the
        # caveat does not apply and claiming it would understate the result.
        self.assertNotIn("fixture_scope", part.direct[0])

    def test_process_only_is_distinguished_from_tested(self):
        self.assertEqual(self.parts[MODULE].coverage, "tested")
        self.assertEqual({r["kind"] for r in self.built["root_direct"]}, {"assembly"})

    # --- tier 2: inherited -------------------------------------------------

    def test_a_vendor_part_inherits_only_real_tests_from_its_parent(self):
        part = self.parts[COLDPLATE]
        self.assertEqual(part.coverage, "inherited_only")
        stations = [r["station"] for r in part.inherited]
        self.assertIn("Sohu Module Test", stations)
        # Greasing the TIM cell is not evidence the cold plate was tested, even
        # though Pega files it under section: TEST.
        self.assertNotIn("Replenish PG25", stations)
        self.assertTrue(all(r["on"] == MODULE for r in part.inherited))

    def test_inheritance_is_bounded_by_the_edge_window(self):
        """A part installed after a test ran must not inherit that test."""
        for container in (self.serials[ROOT], self.serials[MODULE]):
            for child in container["current_tree"]["children"]:
                for grandchild in child.get("children") or []:
                    if grandchild["serial"] == COLDPLATE:
                        grandchild["valid_from"] = "2026-08-30T00:00:00Z"
                if child["serial"] == COLDPLATE:
                    child["valid_from"] = "2026-08-30T00:00:00Z"
        _, parts = self.rebuild()
        self.assertEqual(parts[COLDPLATE].inherited, [])
        self.assertEqual(parts[COLDPLATE].coverage, "none_expected")

    # --- the flags ---------------------------------------------------------

    def test_serialized_part_with_no_route_history_is_flagged_even_when_covered(self):
        """Why the escape is a flag and not a fifth coverage value.

        ORPHAN is Etched-serialized with no records of its own, but its parent
        was tested while it was installed — so its coverage is legitimately
        ``inherited_only``. Folding the escape into coverage made it read as fine.
        """
        self.assertEqual(self.parts[ORPHAN].coverage, "inherited_only")
        self.assertTrue(self.parts[ORPHAN].traceability_gap)
        self.assertFalse(self.parts[COLDPLATE].traceability_gap)  # vendor: expected
        self.assertFalse(self.parts[MODULE].traceability_gap)     # serialized, routed
        found = {row["sn"] for row in graph.gaps(self.built)["serialized_without_records"]}
        self.assertEqual(found, {ORPHAN})

    def test_a_failed_lookup_is_not_reported_as_a_traceability_escape(self):
        """The regression that matters most to anyone downstream.

        A part we never fetched is indistinguishable from a part with no records.
        Reporting an escape then sends Pega a false positive, which costs their
        time and the report's only real asset, which is being trusted.
        """
        partial = {ROOT: self.serials[ROOT], MODULE: self.serials[MODULE]}
        built, parts = self.rebuild(serials=partial)
        self.assertFalse(parts[ORPHAN].traceability_gap)
        self.assertEqual(parts[ORPHAN].coverage, "not_observed")
        self.assertEqual(graph.gaps(built)["serialized_without_records"], [])
        self.assertIn(ORPHAN, {row["sn"] for row in graph.gaps(built)["not_observed"]})

    def test_missing_location_is_reported(self):
        found = {row["sn"] for row in graph.gaps(self.built)["slot_position_unknown"]}
        self.assertIn(SOHU, found)

    # --- rollup and history ------------------------------------------------

    def test_subtree_rollup_surfaces_a_failure_from_three_levels_down(self):
        part = self.parts[MODULE]
        self.assertEqual(part.subtree.get("tested"), 1)
        self.assertEqual(part.subtree.get("failing_parts"), 1)

    def test_replacement_history_is_flat_and_names_both_serials(self):
        """Shaped from the receiver's documented schema, not from live data — no
        unit mirrored so far has a swap, so this fixture is the only thing
        holding the field names honest."""
        self.serials[MODULE]["inferred_replacements"] = [{
            "parent_sn": MODULE, "normalized_slot": "Cold_Plate_0",
            "component_type": "COP", "old_component_sn": "SW5OLD",
            "new_component_sn": COLDPLATE, "replaced_at": "2026-08-25T00:00:00Z",
            "reason": "new_link_same_parent_slot",
        }]
        self.serials[MODULE]["previous_children"] = [{
            "parent_sn": MODULE, "normalized_slot": "BO_9", "component_type": "BO",
            "component_sn": "JE60700000000000000000",
            "valid_to": "2026-08-20T00:00:00Z", "ended_reason": "explicit_delink",
        }]
        built, _ = self.rebuild()
        rows = graph.history(built, self.serials)
        self.assertEqual(len(rows), 2)
        swap = next(r for r in rows if r["slot"] == "Cold_Plate_0")
        self.assertEqual(swap["removed_sn"], "SW5OLD")
        self.assertEqual(swap["installed_sn"], COLDPLATE)
        self.assertEqual(swap["detected_by"], "new_link_same_parent_slot")
        removal = next(r for r in rows if r["slot"] == "BO_9")
        self.assertIsNone(removal["installed_sn"])
        # Sorted oldest first, so a history reads as a timeline.
        self.assertEqual([r["at"] for r in rows], sorted(r["at"] for r in rows))


class SerialShape(unittest.TestCase):
    """Which serials Pega issues, and therefore routes. See graph.is_etched_serial."""

    def test_etched_serials_are_recognised(self):
        for sn in ("268862070001", "268524700000037", "264968350001"):
            self.assertTrue(graph.is_etched_serial(sn), sn)

    def test_vendor_barcodes_are_not(self):
        for sn in ("JCS0R8001057", "705260033", "3546300006", "SW5VBJ",
                   "BR80J1013800059", "AH093025-57", ""):
            self.assertFalse(graph.is_etched_serial(sn), sn)


if __name__ == "__main__":
    unittest.main()
