"""The hand-kept sheet against this repo's reading of the same day.

Two things are asserted here above all. First, that a delta is *classified*
rather than just counted: "29 units differ" is not actionable and "29 units ran
after the sheet was cut" is, and the difference between those two sentences is
this module's whole job. Second, that neither side is corrected into the other —
the sheet and the controllers each know things the other does not, and a
comparison that quietly picked a winner would be worse than no comparison.

The parsing tests exist because the first version of this module walked every
tab whose name began with a date and produced confident wrong numbers: tabs with
their header on row 2 came out as every-unit-not-run, and a Retest tab's Date
column filed it under the day being retested. Both look exactly like a finding.
"""

import json
import unittest

from factory import build_delta


class SerialTest(unittest.TestCase):
    """Excel keeps DUT SN as a float; the line reads it as a serial."""

    def test_a_float_serial_comes_back_as_the_serial(self):
        self.assertEqual(build_delta._serial("2.68524700000105E14"),  # noqa: SLF001
                         "268524700000105")

    def test_a_text_serial_is_left_alone(self):
        self.assertEqual(build_delta._serial("268524700000105"),      # noqa: SLF001
                         "268524700000105")

    def test_a_trailing_point_zero_is_not_part_of_the_serial(self):
        self.assertEqual(build_delta._serial("268524700000105.0"),    # noqa: SLF001
                         "268524700000105")

    def test_nothing_stays_nothing(self):
        self.assertEqual(build_delta._serial(""), "")                 # noqa: SLF001


class VerdictTest(unittest.TestCase):
    """The two systems spell one verdict differently; neither is corrected."""

    def test_the_sheet_and_the_controller_spellings_meet(self):
        self.assertEqual(build_delta._verdict("PASS"),                # noqa: SLF001
                         build_delta._verdict("passed"))
        self.assertEqual(build_delta._verdict("FAIL"),                # noqa: SLF001
                         build_delta._verdict("Failed"))

    def test_an_empty_cell_is_blank_not_a_failure(self):
        """A unit that did not reach a stage has not failed it. Counting a
        blank as a fail would move a yield by the size of the backlog."""
        self.assertEqual(build_delta._verdict(""), "blank")           # noqa: SLF001
        self.assertEqual(build_delta._verdict("N/A"), "blank")        # noqa: SLF001

    def test_an_abort_is_not_a_fail(self):
        self.assertEqual(build_delta._verdict("aborted"), "abort")    # noqa: SLF001


class ClassifyTest(unittest.TestCase):
    """Why two failure lists differ — the part that makes a row actionable."""

    def classify(self, local, online, verdict="fail"):
        return build_delta._classify_cases(local, online, verdict)     # noqa: SLF001

    def test_identical_lists_are_not_a_delta(self):
        self.assertIsNone(self.classify(["SohuDmaTestCase"], ["SohuDmaTestCase"]))

    def test_a_failure_with_no_case_named_is_the_sheet_s_omission(self):
        """An empty failure cell beside "Failed" is the one thing that column
        must never say, and the controller has the name."""
        self.assertEqual(self.classify([], ["C2cLinkupTestCase"]), "case-missing")

    def test_a_blank_case_on_a_pass_is_not_an_omission(self):
        """Nothing failed, so naming nothing is correct. Only the online side
        having a case at all is worth a row."""
        self.assertEqual(self.classify([], ["C2cLinkupTestCase"], verdict="pass"),
                         "case-extra")

    def test_prose_is_told_apart_from_a_case_name(self):
        self.assertEqual(
            self.classify(["chip not enumerated by RPC proxy"],
                          ["SohuFlrTestCase"]), "case-prose")

    def test_a_wrapper_only_online_cell_is_the_dashboard_s_gap(self):
        """The controller recorded nothing but the nest for this slot, so the
        dashboard cell means "something failed here". The sheet's leaf is the
        more useful fact, and the class has to say so rather than blaming it."""
        self.assertEqual(
            self.classify(["SohuVfioPingTestCase"], ["SltModuleNestedTestCase"]),
            "case-nest-only")

    def test_the_sheet_recording_the_first_of_several_is_a_subset(self):
        self.assertEqual(
            self.classify(["SohuI2cTestCase"],
                          ["SohuI2cTestCase", "SohuVmTestCase"]), "case-subset")

    def test_no_case_in_common_is_a_conflict(self):
        self.assertEqual(
            self.classify(["SohuVrmTestCase"], ["SohuDmaTestCase"]),
            "case-conflict")

    def test_partly_agreeing_lists_are_neither_side_s_fault(self):
        self.assertEqual(
            self.classify(["A", "B"], ["B", "C"]), "case-overlap")


class HeaderTest(unittest.TestCase):
    """Columns are found by heading, because the line moves them."""

    class FakeCell:
        def __init__(self, column, value):
            self.column, self.value = column, value

    def header(self, titles):
        return [self.FakeCell(column, title)
                for column, title in titles]

    def test_columns_are_matched_on_their_heading(self):
        found = build_delta._header_map(self.header([               # noqa: SLF001
            ("A", "No"), ("B", "Date"), ("C", "DUT SN"),
            ("F", "MLT Results\nmlt_2026.231.0-tpm"),
            ("G", "MLT Failure Test Case\nmlt_2026.231.0-tpm"),
        ]))
        self.assertEqual(found["sn"], "C")
        self.assertEqual(found["mlt"], "F")
        self.assertEqual(found["mltCase"], "G")

    def test_the_two_link_columns_are_told_apart_by_order(self):
        """Both are headed "FI Test Link". Position is the only thing that
        distinguishes MLT's from HTT's, and swapping them would put a run link
        on the wrong stage."""
        found = build_delta._header_map(self.header([               # noqa: SLF001
            ("C", "DUT SN"),
            ("F", "MLT Results"), ("G", "MLT Failure Test Case"),
            ("H", "FI Test Link"),
            ("I", "HTT Results"), ("J", "HTT Failure Test Case"),
            ("K", "FI Test Link"),
        ]))
        self.assertEqual(found["mltLink"], "H")
        self.assertEqual(found["httLink"], "K")

    def test_a_heading_row_with_no_serial_column_is_a_parse_failure(self):
        """Not an empty day. Getting the header row wrong reports every unit as
        "not run", which reads as a catastrophic shift rather than a bug."""
        found = build_delta._header_map(self.header([               # noqa: SLF001
            ("A", "PV1 A03 Sohu Module"), ("B", ""),
        ]))
        self.assertNotIn("sn", found)


class DayTest(unittest.TestCase):
    def test_the_configured_day_wins(self):
        self.assertEqual(
            build_delta.tab_day("08-13 Retest", {"day": "2026-08-11"},
                                {"day": "2026-08-13"}),
            "2026-08-13")

    def test_the_tab_name_beats_the_date_column(self):
        """A Retest tab's Date column holds the date of the run being retested.
        Trusting it filed "08-13 Retest" under 08-11."""
        self.assertEqual(
            build_delta.tab_day("08-13 Retest", {"day": "2026-08-11"}, {}),
            "2026-08-13")

    def test_the_year_comes_from_the_sheet_not_the_name(self):
        self.assertEqual(
            build_delta.tab_day("08-20 MLT  HTT Run", {"day": "2025-08-20"}, {}),
            "2025-08-20")


class ReportedTest(unittest.TestCase):
    """The posted figures against the tab they were read off."""

    ROWS = [{"mlt": "pass", "htt": "pass"}] * 56 + \
           [{"mlt": "fail", "htt": "fail"}] * 22

    def test_agreement_means_the_tab_has_not_moved(self):
        out = build_delta._reported_delta(                          # noqa: SLF001
            {"mlt": {"pass": 56, "fail": 22}}, self.ROWS)
        self.assertTrue(out["mlt"]["agrees"])
        self.assertEqual(out["mlt"]["passDelta"], 0)

    def test_a_moved_tab_reports_by_how_much_per_station(self):
        """On 08-20 the HTT figures still matched the post exactly and MLT had
        gained eight rows, which dates the sheet's last edit better than its
        file timestamp does."""
        out = build_delta._reported_delta(                          # noqa: SLF001
            {"mlt": {"pass": 49, "fail": 21}}, self.ROWS)
        self.assertFalse(out["mlt"]["agrees"])
        self.assertEqual(out["mlt"]["passDelta"], 7)
        self.assertEqual(out["mlt"]["failDelta"], 1)

    def test_no_posted_figures_yields_nothing_rather_than_zeroes(self):
        self.assertEqual(build_delta._reported_delta({}, self.ROWS), {})  # noqa: SLF001


class CompareTest(unittest.TestCase):
    """Every unit on either side, and what the two say about it."""

    def unit(self, sn, mlt="pass", mltCase=(), htt="blank", httCase=(), row=2):
        return {"sn": sn, "row": row, "mlt": mlt, "mltCase": list(mltCase),
                "htt": htt, "httCase": list(httCase),
                "mltLink": "", "httLink": ""}

    def test_a_unit_on_one_side_only_is_a_population_delta(self):
        out = build_delta.compare([self.unit("1")], [], adjudicate=False)
        kinds = [d["kind"] for d in out["units"][0]["deltas"]]
        self.assertEqual(kinds, ["population"])
        self.assertEqual(out["units"][0]["where"], "local")

    def test_a_unit_only_the_dashboard_has_is_marked_as_such(self):
        out = build_delta.compare([], [self.unit("1")], adjudicate=False)
        self.assertEqual(out["units"][0]["where"], "online")

    def test_agreeing_units_carry_no_deltas_but_are_still_listed(self):
        """A reader checking one serial has to find it here whether or not it
        is a problem."""
        out = build_delta.compare([self.unit("1")], [self.unit("1")],
                                  adjudicate=False)
        self.assertEqual(out["units"][0]["deltas"], [])
        self.assertEqual(len(out["units"]), 1)

    def test_a_verdict_disagreement_is_reported_per_station(self):
        out = build_delta.compare([self.unit("1", htt="blank")],
                                  [self.unit("1", htt="pass")],
                                  adjudicate=False)
        deltas = out["units"][0]["deltas"]
        self.assertEqual([d["kind"] for d in deltas], ["status"])
        self.assertEqual(deltas[0]["station"], "htt")
        self.assertEqual((deltas[0]["local"], deltas[0]["online"]),
                         ("blank", "pass"))

    def test_both_sides_values_survive_onto_the_row(self):
        """Neither is corrected into the other — the page shows both and says
        which is which."""
        out = build_delta.compare(
            [self.unit("1", mlt="fail", mltCase=["A"])],
            [self.unit("1", mlt="fail", mltCase=["B"])], adjudicate=False)
        entry = out["units"][0]["mlt"]
        self.assertEqual(entry["localCase"], ["A"])
        self.assertEqual(entry["onlineCase"], ["B"])

    def test_units_come_out_in_serial_order(self):
        out = build_delta.compare(
            [self.unit("2"), self.unit("1")], [], adjudicate=False)
        self.assertEqual([u["sn"] for u in out["units"]], ["1", "2"])


class FreshTest(unittest.TestCase):
    """Fresh material or a unit that has been here before, per stage.

    Taken from the tracker rather than recomputed: it already has to work this
    out so its Count new mode can drop returning units from a day's yield, and a
    second implementation of the same question would disagree within a week.
    """

    def tab(self, sn_cell):
        return {
            "columns": [{"key": "B", "title": "SN"},
                        {"key": "E", "title": "MLT Results"},
                        {"key": "H", "title": "HTT Results"}],
            "rows": [[sn_cell, {"v": "Passed"}, {"v": "Failed"}]],
        }

    def test_a_first_visit_is_fresh_at_every_stage(self):
        row = build_delta.published_rows(self.tab({"v": "1", "new": True}))[0]
        self.assertTrue(row["mltFresh"])
        self.assertTrue(row["httFresh"])
        self.assertEqual(row["mltAttempts"], 0)

    def test_a_returning_unit_is_only_stale_at_the_stage_it_returned_to(self):
        """A unit back for a second MLT has still only seen HTT once. Marking it
        stale everywhere would put it in the wrong bucket on the other table."""
        row = build_delta.published_rows(self.tab({
            "v": "1", "seen": {"mlt": "2026-08-19"},
            "history": {"mlt": [1, 2, 3]}}))[0]
        self.assertFalse(row["mltFresh"])
        self.assertTrue(row["httFresh"])
        self.assertEqual(row["mltAttempts"], 3)
        self.assertEqual(row["mltSeen"], "2026-08-19")

    def test_the_flag_reaches_the_compared_unit(self):
        local = [{"sn": "1", "row": 2, "mlt": "pass", "mltCase": [],
                  "htt": "blank", "httCase": [], "mltLink": "", "httLink": ""}]
        online = build_delta.published_rows(self.tab({
            "v": "1", "seen": {"mlt": "2026-08-19"}, "history": {"mlt": [1, 2]}}))
        out = build_delta.compare(local, online, adjudicate=False)
        self.assertFalse(out["units"][0]["mlt"]["fresh"])
        self.assertEqual(out["units"][0]["mlt"]["attempts"], 2)

    def test_a_unit_only_the_sheet_has_defaults_to_fresh(self):
        """Only the controllers can answer this, so a unit they do not have gets
        the benign default rather than being called a retest on no evidence."""
        local = [{"sn": "1", "row": 2, "mlt": "pass", "mltCase": [],
                  "htt": "blank", "httCase": [], "mltLink": "", "httLink": ""}]
        out = build_delta.compare(local, [], adjudicate=False)
        self.assertTrue(out["units"][0]["mlt"]["fresh"])


class BundleTest(unittest.TestCase):
    def test_the_tab_to_gid_map_is_config_not_code(self):
        """A gid cannot be derived from a tab name, and a row link without one
        lands at the top of a hundred-row sheet."""
        found = build_delta.settings()
        if not found:
            self.skipTest("no diff/delta.json in this checkout")
        self.assertIn("sheetUrl", found)
        for name, tab in (found.get("tabs") or {}).items():
            with self.subTest(tab=name):
                self.assertTrue(tab.get("day"), "every tab needs its day")

    def test_a_missing_workbook_says_what_to_do(self):
        with self.assertRaises(build_delta.NoWorkbook) as caught:
            build_delta.workbook_path("/nonexistent/nope.xlsx")
        self.assertIn("nope.xlsx", str(caught.exception))


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
