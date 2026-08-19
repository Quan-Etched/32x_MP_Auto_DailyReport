"""The L10 daily tracker: FAT, SFT, RIN and 2U from pega4."""

import unittest

from factory import build_l10


class StageTest(unittest.TestCase):
    def test_release_suffixed_names_still_land_on_their_stage(self):
        # pega4 has run FAT as L10_FAT, L10_6U_FAT and L10_6U_FAT_195..207.
        # The trailing number is a release, not a different stage — a pattern
        # matching only today's spelling silently zeroes the station.
        for suite in ("L10_FAT", "L10_6U_FAT", "L10_6U_FAT_195", "L10_6U_FAT_207"):
            self.assertEqual(build_l10.stage_of(suite), "fat", suite)
        for suite in ("L10_SFT", "L10_6U_SFT_204"):
            self.assertEqual(build_l10.stage_of(suite), "sft", suite)
        self.assertEqual(build_l10.stage_of("L10_RIN"), "rin")

    def test_2u_accepts_pega4_s_spelling(self):
        # EOS calls it L10_2U, pega4 L10_2U_tests. Same production part number
        # and the same chassis serials FAT uses.
        self.assertEqual(build_l10.stage_of("L10_2U"), "2u")
        self.assertEqual(build_l10.stage_of("L10_2U_tests"), "2u")

    def test_engineering_suites_are_not_stages(self):
        for suite in ("L10_6U_FAT_krish", "L10_6U_FAT_debug_krish", "L10_tests",
                      "L10_2U_SMOKE", "L10_FAT_195_out_dir", "L10_6U_FAT_SAM",
                      "DRY_RUN_L10_6U_SFT_204", "L10_6U_MEM_etch33931"):
            self.assertIsNone(build_l10.stage_of(suite), suite)

    def test_an_unknown_suite_is_not_forced_into_a_stage(self):
        self.assertIsNone(build_l10.stage_of("something_new"))
        self.assertIsNone(build_l10.stage_of(None))


class FailureTest(unittest.TestCase):
    def test_every_failure_in_the_run_belongs_to_the_chassis(self):
        # No slot filtering: an L10 run is one chassis, so filtering by chip
        # index — which the module tracker must do — would drop everything.
        detail = {"test_cases": [
            {"test_name": "CheckSystemLogStates", "status": "failed", "start_time": "02"},
            {"test_name": "RunInStress", "status": "failed", "start_time": "03"},
            {"test_name": "CheckPcie", "status": "passed", "start_time": "01"},
        ]}
        self.assertEqual(build_l10.unit_failures(detail),
                         "CheckSystemLogStates\nRunInStress")

    def test_containers_are_skipped(self):
        detail = {"test_cases": [
            {"test_name": "ServerNestedTestCase", "status": "failed", "start_time": "01"},
            {"test_name": "CheckSystemLogStates", "status": "failed", "start_time": "02"},
        ]}
        self.assertEqual(build_l10.unit_failures(detail), "CheckSystemLogStates")

    def test_a_passing_run_names_nothing(self):
        self.assertEqual(build_l10.unit_failures({"test_cases": [
            {"test_name": "CheckPcie", "status": "passed"}]}), "")


class ColumnTest(unittest.TestCase):
    def test_four_columns_per_stage_after_the_chassis(self):
        """Result, version, failure, link — the module tracker's shape, so the
        two pages share a renderer and a tally rather than drifting.

        Just "SN". It read "Chassis SN", then "DUT SN"; the three daily tables
        are read together and each naming its own subject in the column head
        made one column at three levels look like three different things. The
        heading over the table still says L10 and still counts chassis."""
        columns = build_l10._columns()
        titles = [c["title"] for c in columns]
        self.assertEqual(titles[:3], ["Date", "SN", "DUT PN"])
        self.assertEqual(len(titles), 3 + 4 * 4)
        self.assertEqual(titles[3], "L10 FAT Results")
        self.assertEqual(titles[4], "L10 FAT Version")
        self.assertEqual(titles[5], "L10 FAT Failure Test Case")
        self.assertEqual(titles[6], "FI Test Link")

    def test_each_result_column_names_its_station(self):
        """The tally is header-driven now: a result column with no station is
        a column the tiles cannot count."""
        stations = [c.get("station") for c in build_l10._columns()
                    if c["title"].endswith("Results")]
        self.assertEqual(stations, ["l10_fat", "l10_sft", "l10_rin", "l10_2u"])

    def test_only_result_columns_are_tallied(self):
        """A version column names its station so its result column can find
        it; tallying it too produced four phantom tiles."""
        columns = build_l10._columns()
        rows = [[{} for _ in columns]]
        counts = build_l10._counts(rows, columns)
        self.assertEqual(sorted(counts), ["D", "H", "L", "P"])

    def test_there_is_no_jira_column(self):
        # Its keys come from the module line's sheet; L10 has none, and an
        # always-empty column is worse than an absent one.
        self.assertNotIn("Jira", [c["title"] for c in build_l10._columns()])


class DayTest(unittest.TestCase):
    LISTING = [
        {"suite_run_id": "L10_FAT_run_00a5c0b4", "suite_name": "L10_FAT",
         "dut_part_number": "81S15V000050", "start_time": "2026-08-13T01:00:00Z"},
        {"suite_run_id": "L10_SFT_run_deadbeef", "suite_name": "L10_SFT",
         "dut_part_number": "81S15V000050", "start_time": "2026-08-13T02:00:00Z"},
        {"suite_run_id": "L10_tests_run_ignored", "suite_name": "L10_tests",
         "dut_part_number": "81S15V000050", "start_time": "2026-08-13T03:00:00Z"},
    ]
    DETAIL = {
        "L10_FAT_run_00a5c0b4": {"status": "failed", "participating": None,
                                 "dut_sn": "267694410002", "slot_number": 1,
                                 "test_cases": [{"test_name": "CheckSystemLogStates",
                                                 "status": "failed", "start_time": "01"}]},
        "L10_SFT_run_deadbeef": {"status": "passed", "participating": None,
                                 "dut_sn": "267694410002", "slot_number": 1,
                                 "test_cases": []},
        "L10_tests_run_ignored": {"status": "failed", "participating": None,
                                  "dut_sn": "999", "slot_number": 1, "test_cases": []},
    }

    def setUp(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, pega, "suite_run", pega.suite_run)
        pega.day_suite_runs = lambda day, host=None: list(self.LISTING)
        pega.suite_run = lambda run_id, host=None: self.DETAIL[run_id]

    def test_one_row_per_chassis_with_every_stage_on_it(self):
        tab = build_l10._day("2026-08-13")
        self.assertEqual(len(tab["rows"]), 1)
        row = tab["rows"][0]
        self.assertEqual(row[1]["v"], "267694410002")
        self.assertEqual(row[3], {"v": "Failed", "t": "fail"})     # FAT
        self.assertEqual(row[5]["v"], "CheckSystemLogStates")      # FAT failure
        self.assertEqual(row[7], {"v": "Passed", "t": "pass"})     # SFT

    def test_engineering_runs_never_reach_the_page(self):
        tab = build_l10._day("2026-08-13")
        self.assertEqual(tab["derivedFrom"]["runs"], 2)
        self.assertNotIn("999", [r[1].get("v") for r in tab["rows"]])

    def test_the_link_points_at_pega4(self):
        row = build_l10._day("2026-08-13")["rows"][0]
        self.assertIn("pega4:3000/suite_run/L10_FAT_run_00a5c0b4", row[6]["h"])

    def test_a_day_with_no_l10_runs_is_no_tab(self):
        from factory import pega
        pega.day_suite_runs = lambda day, host=None: []
        self.assertIsNone(build_l10._day("2026-08-13"))

    def test_an_unreachable_pega4_is_not_a_failed_build(self):
        from factory import pega
        def boom(day, host=None):
            raise pega.PegaUnavailable("no route")
        pega.day_suite_runs = boom
        self.assertIsNone(build_l10._day("2026-08-13"))


if __name__ == "__main__":
    unittest.main()
