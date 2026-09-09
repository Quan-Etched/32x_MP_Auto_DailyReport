"""The L10 daily tracker: FAT, SFT, RIN and 2U from pega4."""

import inspect
import unittest

from factory import build_dailyexcel, build_l10


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


class DayStripTest(unittest.TestCase):
    """The Test History strip runs to the end of the day the row is about.

    Reported from the 09-01 tab: 268645440002 had passed FAT that afternoon —
    http://pega4:3000/suite_run/L10_FAT_run_00559eb3 — and its row read
    "L10_FAT F2 F3 F4 F5 F6 F7 F8 F9  08-31" beside a verdict of Passed. Every
    mark in the strip was a failure, so the row read as a unit whose final test
    failed. Two separate causes, both fixed here: the strip stopped at the day
    before, and it was capped at the last eight attempts, which is why it also
    had no F1 to start from.
    """

    #: Two FAT runs on the row's own day: the 13:21 failure and the 15:26 pass.
    LISTING = [
        {"suite_run_id": "L10_FAT_run_9bf8d5a2", "suite_name": "L10_FAT",
         "dut_part_number": "81S15V000020",
         "start_time": "2026-09-01T13:21:29Z"},
        {"suite_run_id": "L10_FAT_run_00559eb3", "suite_name": "L10_FAT",
         "dut_part_number": "81S15V000020",
         "start_time": "2026-09-01T15:26:41Z"},
    ]
    DETAIL = {
        "L10_FAT_run_9bf8d5a2": {"status": "failed", "participating": None,
                                 "dut_sn": "268645440002", "slot_number": 2,
                                 "test_cases": []},
        "L10_FAT_run_00559eb3": {"status": "passed", "participating": None,
                                 "dut_sn": "268645440002", "slot_number": 2,
                                 "test_cases": []},
    }

    #: The nine failures behind it, the oldest on 08-20.
    PAST = [{"day": "2026-08-20" if i < 2 else "2026-08-31", "status": "fail",
             "url": "http://pega4:3000/suite_run/old%d" % i,
             "suite": "L10_FAT"} for i in range(9)]

    def setUp(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, pega, "suite_run", pega.suite_run)
        self.addCleanup(setattr, build_l10, "_seen_before",
                        build_l10._seen_before)
        pega.day_suite_runs = lambda day, host=None: list(self.LISTING)
        pega.suite_run = lambda run_id, host=None: self.DETAIL[run_id]
        build_l10._seen_before = lambda day, **kw: {
            "fat": {"268645440002": list(self.PAST)},
            "sft": {}, "rin": {}, "2u": {}}

    def strip(self):
        row = build_l10._day("2026-09-01")["rows"][0]
        return row[1], [("P" if a["status"] == "pass" else "F") + str(a["n"])
                        for a in row[1]["history"]["l10_fat"]]

    def test_the_strip_ends_on_the_days_verdict(self):
        _serial, marks = self.strip()
        self.assertEqual(marks[-1], "P11",
                         "the row says Passed; the strip has to say so too")

    def test_it_starts_at_the_units_first_attempt(self):
        _serial, marks = self.strip()
        self.assertEqual(marks[0], "F1")

    def test_the_days_own_earlier_failure_is_on_it(self):
        """13:21 failed, 15:26 passed. The row keeps the pass, and the failure
        used to appear nowhere on the page at all."""
        _serial, marks = self.strip()
        self.assertEqual(marks, ["F%d" % n for n in range(1, 11)] + ["P11"])

    def test_the_verdict_column_still_shows_the_last_attempt(self):
        row = build_l10._day("2026-09-01")["rows"][0]
        self.assertEqual(row[3], {"v": "Passed", "t": "pass"})

    def test_the_last_chip_links_to_the_run_it_names(self):
        row = build_l10._day("2026-09-01")["rows"][0]
        self.assertIn("L10_FAT_run_00559eb3",
                      row[1]["history"]["l10_fat"][-1]["url"])

    def test_seen_still_means_the_last_visit_before_today(self):
        """It decides new input, and the strip growing must not move it — a
        unit is fresh material or not by what it did before today."""
        serial, _marks = self.strip()
        self.assertEqual(serial["seen"]["l10_fat"], "2026-08-31")
        self.assertFalse(serial["new"])

    def test_a_first_visit_that_passed_first_time_has_no_strip(self):
        """One attempt and nothing behind it is not a history; the verdict
        column already says it."""
        from factory import pega
        build_l10._seen_before = lambda day, **kw: {
            "fat": {}, "sft": {}, "rin": {}, "2u": {}}
        pega.day_suite_runs = lambda day, host=None: [self.LISTING[1]]
        serial = build_l10._day("2026-09-01")["rows"][0][1]
        self.assertNotIn("history", serial)
        self.assertTrue(serial["new"])

    def test_a_first_visit_retried_the_same_day_does_get_one(self):
        build_l10._seen_before = lambda day, **kw: {
            "fat": {}, "sft": {}, "rin": {}, "2u": {}}
        serial = build_l10._day("2026-09-01")["rows"][0][1]
        self.assertEqual(
            [("P" if a["status"] == "pass" else "F") + str(a["n"])
             for a in serial["history"]["l10_fat"]], ["F1", "P2"])
        self.assertTrue(serial["new"],
                        "still fresh material — nothing before today")


class SharedIndexTest(unittest.TestCase):
    """The span is read once for the build and sliced per tab.

    Walking the history per tab was affordable while it reached 30 days and the
    tracker began in August. Over the controllers' full retention it measured
    15s per L10 tab, 7s per L11 tab and 22s per module tab, warm — about 78
    minutes for one build of the ~100 tabs the tracker now publishes.

    The parameter is called `history_index` and not `index` on purpose: `_day`
    already binds `index` to its column-position map, and the first version of
    this took that name. The map silently replaced the span, `slice_before` was
    handed a dict of ints, and every history strip on the page would have been
    wrong — the sort of thing that reads as a typo and costs a day.
    """

    def setUp(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, pega, "suite_run", pega.suite_run)
        pega.day_suite_runs = lambda day, host=None: (
            [{"suite_run_id": "L10_FAT_run_old", "suite_name": "L10_FAT",
              "dut_part_number": "81S15V000020",
              "start_time": day + "T04:00:00Z"}]
            if day == "2026-06-15" else
            [{"suite_run_id": "L10_FAT_run_now", "suite_name": "L10_FAT",
              "dut_part_number": "81S15V000020",
              "start_time": day + "T09:00:00Z"}]
            if day == "2026-09-01" else [])
        pega.suite_run = lambda run_id, host=None: {
            "status": "failed" if run_id.endswith("old") else "passed",
            "participating": None, "dut_sn": "268645440002",
            "slot_number": 2, "test_cases": []}
        # This class is about the span being read once and sliced per tab, not
        # about how far back the line currently reports. Pin both ends of the
        # reach so moving pega.CONTROLLER_FROM — 05-01 to 08-01 on 2026-09-03,
        # and it will move again — cannot empty the fixture's June attempt out
        # of the strip and fail a test that is measuring something else.
        self.addCleanup(setattr, pega, "CONTROLLER_FROM", pega.CONTROLLER_FROM)
        self.addCleanup(setattr, build_dailyexcel, "NEW_INPUT_LOOKBACK",
                        build_dailyexcel.NEW_INPUT_LOOKBACK)
        pega.CONTROLLER_FROM = "2026-05-01"
        build_dailyexcel.NEW_INPUT_LOOKBACK = 200

    def index(self):
        return build_l10.stage_index("2026-05-01", "2026-09-01")

    def test_the_index_spans_the_whole_range(self):
        got = self.index()
        self.assertEqual([a["day"] for a in got["fat"]["268645440002"]],
                         ["2026-06-15", "2026-09-01"])

    def test_a_slice_stops_before_the_day_it_is_for(self):
        history = build_dailyexcel.slice_before(self.index(), "2026-09-01", 200)
        self.assertEqual([a["day"] for a in history["fat"]["268645440002"]],
                         ["2026-06-15"],
                         "the row's own day is the row, not its history")

    def test_a_slice_respects_the_lookback(self):
        history = build_dailyexcel.slice_before(self.index(), "2026-09-01", 30)
        self.assertNotIn("268645440002", history["fat"],
                         "June is outside a 30-day reach")

    def test_the_shared_index_and_the_standalone_walk_agree(self):
        """Two ways in, one answer — otherwise a tab built inside a bundle
        would differ from the same tab built on its own."""
        shared = build_l10._day("2026-09-01", self.index())["rows"][0][1]
        alone = build_l10._day("2026-09-01")["rows"][0][1]
        self.assertEqual(shared.get("history"), alone.get("history"))
        self.assertEqual(shared.get("seen"), alone.get("seen"))

    def test_the_column_map_is_not_mistaken_for_the_span(self):
        """`_day` binds `index` to its column-position map. If the span shares
        that name the map overwrites it, and slice_before gets ints."""
        source = inspect.getsource(build_l10._day)
        self.assertIn("history_index", source)
        self.assertIn('index = {column["key"]: position', source)
        head = source.split("\n\n", 1)[0]
        self.assertNotIn("index: Optional", head.replace("history_index", ""))
        # And prove it end to end: the tab builds and the strip is right.
        serial = build_l10._day("2026-09-01", self.index())["rows"][0][1]
        self.assertEqual(
            [("P" if a["status"] == "pass" else "F") + str(a["n"])
             for a in serial["history"]["l10_fat"]], ["F1", "P2"])


if __name__ == "__main__":
    unittest.main()
