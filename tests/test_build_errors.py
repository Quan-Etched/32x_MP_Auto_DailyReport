"""The failure-to-error-code join.

The join is the whole module, and the two ways it can go quietly wrong are:

  * picking one code when the catalogue offers several. 125 of 177 test cases
    map to more than one code, because a code says *how* a case failed and the
    tracker records only that it did. Choosing would be inventing a diagnosis
    and it would look exactly like a real one.
  * dropping the rows whose case is not in the catalogue at all. Those are 138
    of 1180 today, and a table that hid them would report the line as fully
    catalogued.

Everything here is about those two, plus the shape of the tracker it reads:
"Failure Test Case" then "FI Test Link", repeated per station across the MLT/HTT,
L10 and L11 blocks, with two cases sometimes newline-separated in one cell.
"""

import unittest

from factory import build_errors


def column(key, title, station=None):
    got = {"key": key, "title": title}
    if station:
        got["station"] = station
    return got


#: One MLT/HTT tab wrapped as a bundle, which is what collect() takes — the
#: same shape build_dailyexcel writes and the daily page loads.
def bundle(rows, day="2026-08-20", **extra):
    got = tab(rows, day)
    got.update(extra)
    return {"tabs": [got]}


def tab(rows, day="2026-08-20"):
    return {
        "day": day,
        "columns": [
            column("A", "Date"),
            column("B", "SN"),
            column("E", "MLT Results", "mlt"),
            column("F", "MLT Failure Test Case"),
            column("G", "FI Test Link"),
            column("H", "HTT Results", "htt"),
            column("I", "HTT Failure Test Case"),
            column("J", "FI Test Link"),
        ],
        "rows": rows,
    }


def row(sn, mlt_case="", htt_case="", mlt_link="", htt_link=""):
    return [
        {"v": "2026-08-20"},
        {"v": sn},
        {"v": "Failed" if mlt_case else "Passed"},
        {"v": mlt_case} if mlt_case else {},
        {"v": "run1", "h": mlt_link} if mlt_link else {},
        {"v": "Failed" if htt_case else "Passed"},
        {"v": htt_case} if htt_case else {},
        {"v": "run2", "h": htt_link} if htt_link else {},
    ]


CATALOGUE = {
    "source": "https://example/sheet",
    "readOn": "2026-08-22",
    "codes": [
        {"code": "TH-A-0001", "message": "one way it fails", "action": "RETRY",
         "component": "A", "type": "Hardware", "source": "1X Module Test",
         "bugs": "ETCH-1", "cases": ["OneCodeTestCase", "TwoCodeTestCase"]},
        {"code": "TH-A-0002", "message": "another way", "action": "ESCALATE",
         "component": "A", "type": "Data", "source": "1X Module Test",
         "bugs": "", "cases": ["TwoCodeTestCase"]},
    ],
}


class Fixture(unittest.TestCase):

    def setUp(self):
        self._cat = build_errors.catalogue
        self._ann = build_errors.annotations
        build_errors.catalogue = lambda: CATALOGUE
        build_errors.annotations = lambda: {}

    def tearDown(self):
        build_errors.catalogue = self._cat
        build_errors.annotations = self._ann

    def build(self, bundle):
        return build_errors.build_bundle(build_errors.collect(bundle))


class CollectTest(Fixture):

    def test_one_row_per_unit_station_and_case(self):
        got = build_errors.collect(bundle([
            row("A1", mlt_case="OneCodeTestCase"),
            row("A2", htt_case="TwoCodeTestCase"),
        ]))
        self.assertEqual([("A1", "mlt", "OneCodeTestCase"),
                          ("A2", "htt", "TwoCodeTestCase")],
                         sorted((r["dut"], r["station"], r["case"])
                                for r in got))

    def test_two_cases_in_one_cell_become_two_rows(self):
        """The tracker puts a second failing case on a second line."""
        got = build_errors.collect(bundle([
            row("A1", mlt_case="OneCodeTestCase\nTwoCodeTestCase")]))
        self.assertEqual(["OneCodeTestCase", "TwoCodeTestCase"],
                         sorted(r["case"] for r in got))

    def test_a_passing_unit_contributes_nothing(self):
        self.assertEqual([], build_errors.collect(bundle([row("A1")])))

    def test_the_station_comes_from_the_results_column_above(self):
        """Derived, not a hard-coded map of column letters."""
        got = build_errors.collect(bundle([row("A1", htt_case="OneCodeTestCase")]))
        self.assertEqual("htt", got[0]["station"])

    def test_the_fi_link_is_carried(self):
        got = build_errors.collect(bundle([
            row("A1", mlt_case="OneCodeTestCase", mlt_link="http://pega3/x")]))
        self.assertEqual("http://pega3/x", got[0]["fi"])

    def test_l10_and_l11_blocks_are_read_too(self):
        outer = tab([row("A1", mlt_case="OneCodeTestCase")])
        outer["l10"] = {
            "day": "2026-08-20",
            "columns": [column("A", "Date"), column("B", "SN"),
                        column("D", "L10 FAT Results", "l10_fat"),
                        column("F", "L10 FAT Failure Test Case"),
                        column("G", "FI Test Link")],
            "rows": [[{"v": "2026-08-20"}, {"v": "C9"}, {"v": "Failed"},
                      {"v": "TwoCodeTestCase"}, {}]],
        }
        got = build_errors.collect({"tabs": [outer]})
        self.assertIn(("C9", "l10_fat"),
                      [(r["dut"], r["station"]) for r in got])


class JoinTest(Fixture):

    def test_one_code_is_named(self):
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        self.assertEqual(["TH-A-0001"], got["rows"][0]["codes"])

    def test_several_codes_are_all_listed(self):
        """Never one of them. Choosing would look like a diagnosis."""
        got = self.build(bundle([row("A1", mlt_case="TwoCodeTestCase")]))
        self.assertEqual(["TH-A-0001", "TH-A-0002"],
                         sorted(got["rows"][0]["codes"]))

    def test_an_uncatalogued_case_is_kept_and_counted(self):
        got = self.build(bundle([row("A1", mlt_case="NobodyKnowsTestCase")]))
        self.assertEqual(1, len(got["rows"]), "the row must not be dropped")
        self.assertEqual([], got["rows"][0]["codes"])
        self.assertEqual([{"case": "NobodyKnowsTestCase", "rows": 1}],
                         got["uncatalogued"])

    def test_only_the_codes_in_use_are_shipped(self):
        """The catalogue is 313 codes; a page needs the ones on screen."""
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        self.assertEqual(["TH-A-0001"], sorted(got["codes"]))

    def test_code_text_is_carried_once_not_per_row(self):
        got = self.build(bundle([row("A%d" % n, mlt_case="OneCodeTestCase")
                              for n in range(5)]))
        self.assertEqual(5, len(got["rows"]))
        for row_ in got["rows"]:
            self.assertNotIn("message", row_)
        self.assertEqual("one way it fails",
                         got["codes"]["TH-A-0001"]["message"])


class EstablishedTest(Fixture):
    """A root cause known for a whole test case, not for one failure of it."""

    def setUp(self):
        super().setUp()
        self._est = build_errors.established
        build_errors.established = lambda: {
            "OneCodeTestCase": {
                "rootCause": "setup",
                "why": "the harness, every time",
                "correctiveAction": "re-run once the proxy is up"}}

    def tearDown(self):
        build_errors.established = self._est
        super().tearDown()

    def test_the_known_cause_lands_on_every_row_of_that_case(self):
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase"),
                                 row("A2", mlt_case="OneCodeTestCase")]))
        for r in got["rows"]:
            self.assertEqual("setup", r["rootCause"])
            self.assertTrue(r["established"])
            self.assertEqual("the harness, every time", r["note"])

    def test_another_case_is_untouched(self):
        got = self.build(bundle([row("A1", mlt_case="TwoCodeTestCase")]))
        self.assertNotIn("rootCause", got["rows"][0])
        self.assertNotIn("established", got["rows"][0])

    def test_a_per_row_annotation_beats_the_established_cause(self):
        """A case with a known usual cause can still fail for another reason on
        one unit, and the person who looked at that unit outranks the table."""
        build_errors.annotations = lambda: {
            "2026-08-20|mlt|A1|OneCodeTestCase": {
                "rootCause": "dut", "by": "chuck"}}
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        self.assertEqual("dut", got["rows"][0]["rootCause"])
        self.assertEqual("chuck", got["rows"][0]["by"])

    def test_a_cause_outside_the_two_answers_is_ignored(self):
        build_errors.established = lambda: {
            "OneCodeTestCase": {"rootCause": "probably the harness"}}
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        self.assertNotIn("rootCause", got["rows"][0])

    def test_the_two_answers_are_named_in_the_bundle(self):
        """So the page, the CSV and the service spell them the same way."""
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        self.assertEqual({"setup", "dut"}, set(got["causes"]))


class ShippedCatalogueTest(unittest.TestCase):
    """The committed established.json, not a fixture."""

    def test_the_pcie_setup_family_is_established_as_a_setup_cause(self):
        got = build_errors.established()
        for case in ("PcieSetupTestCase", "CheckPcieTopology"):
            self.assertIn(case, got, "the known one must stay known")
            self.assertEqual("setup", got[case]["rootCause"])

    def test_every_established_cause_is_one_of_the_two_answers(self):
        for case, known in build_errors.established().items():
            with self.subTest(case=case):
                self.assertIn(known["rootCause"], build_errors.CAUSES)


class AnnotationTest(Fixture):

    def test_an_annotation_is_merged_onto_its_row(self):
        build_errors.annotations = lambda: {
            "2026-08-20|mlt|A1|OneCodeTestCase": {
                "rootCause": "dut", "note": "the real reason", "by": "eason"}}
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        self.assertEqual("dut", got["rows"][0]["rootCause"])
        self.assertEqual("the real reason", got["rows"][0]["note"])
        self.assertEqual("eason", got["rows"][0]["by"])

    def test_an_unannotated_row_carries_no_empty_fields(self):
        """Five empty strings per row is 1180 rows of nothing."""
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        for absent in ("rootCause", "correctiveAction", "note", "by", "at"):
            self.assertNotIn(absent, got["rows"][0])

    def test_the_key_the_page_rebuilds_matches_the_one_written(self):
        """The page has no `k` field; it joins on day|station|dut|case."""
        rows = build_errors.collect(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        got = self.build(bundle([row("A1", mlt_case="OneCodeTestCase")]))
        page_side = "|".join([got["rows"][0]["day"], got["rows"][0]["station"],
                              got["rows"][0]["dut"], got["rows"][0]["case"]])
        self.assertEqual(build_errors.entry_key(rows[0]), page_side)


if __name__ == "__main__":
    unittest.main()
