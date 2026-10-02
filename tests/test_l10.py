"""The L10 daily tracker: FAT, SFT, RIN and 2U from pega4."""

import inspect
import unittest
from unittest import mock

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


class SyncDaysTest(unittest.TestCase):
    def test_open_days_cover_utc_and_pacific(self):
        from datetime import datetime, timezone
        # 09-24 07:00 UTC is still 09-23 in Pacific, so both dates stay open.
        moment = datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)
        self.assertEqual(build_l10.open_sync_days(moment),
                         ["2026-09-23", "2026-09-24"])

    def test_merge_adds_a_day_the_snapshot_did_not_have(self):
        bundle = {"tabs": [{"day": "2026-09-23", "columns": [{"key": "A"}],
                            "rows": [{"v": "old"}]}]}
        l10 = {"day": "2026-09-24", "sftReport": {"tested": 1}, "rows": []}
        info = build_l10.merge_l10_into_bundle(bundle, {"2026-09-24": l10})
        self.assertEqual(info["added"], ["2026-09-24"])
        self.assertEqual([tab["day"] for tab in bundle["tabs"]],
                         ["2026-09-23", "2026-09-24"])
        self.assertEqual(bundle["tabs"][1]["l10"]["sftReport"]["tested"], 1)


class CoverageStageTest(unittest.TestCase):
    def test_column_c_groups_c2c_llama_and_connectivity_apart(self):
        self.assertEqual(
            build_l10.stage_of_test("C2cLinkupMultiChipTestCase"), "Sohu C2C")
        self.assertEqual(
            build_l10.stage_of_test("C2cLinkupTestCase"), "Sohu C2C")
        self.assertEqual(
            build_l10.stage_of_test("C2cLinkStabilityTestCase"), "Sohu C2C")
        self.assertEqual(
            build_l10.stage_of_test("SohuPingTestCase"), "Sohu C2C")
        self.assertEqual(
            build_l10.stage_of_test("SohuLlama70bForwardIteratedTestCase"),
            "Model Registry & Inference")
        self.assertEqual(
            build_l10.stage_of_test("SohuLlamaTp8InferenceMaxTestCase"),
            "InferenceMAX Run-in")
        self.assertEqual(
            build_l10.stage_of_test("CheckInterfaceLinkStatus"), "Connectivity")
        self.assertEqual(
            build_l10.stage_of_test("LoopbackTopologyTest"), "Network Bandwidth")
        self.assertEqual(build_l10.stage_of_test("FanTest"), "FanTest")
        self.assertEqual(build_l10.stage_of_test("BmcCheck"), "BMC")
        self.assertEqual(
            build_l10.stage_of_test("StageHuggingFaceToShmTestCase"),
            "Model Registry & Inference")


class ErrorTypeTest(unittest.TestCase):
    def test_coverage_sheet_is_hardware_or_software(self):
        self.assertEqual(
            build_l10.error_type_of_test("C2cLinkupMultiChipTestCase"),
            "hardware")
        self.assertEqual(
            build_l10.error_type_of_test("SohuLlama70bForwardIteratedTestCase"),
            "software")
        self.assertEqual(
            build_l10.error_type_of_test("CheckSystemLogStates"), "hardware")
        self.assertEqual(build_l10.error_type_of_test("RunInStress"), "hardware")
        self.assertEqual(build_l10.error_type_of_test("FanTest"), "hardware")
        self.assertEqual(build_l10.error_type_of_test("BmcCheck"), "hardware")
        self.assertEqual(
            build_l10.error_type_of_test("StageHuggingFaceToShmTestCase"),
            "software")
        self.assertEqual(
            build_l10.as_error_type("Sohu C2C", "C2cLinkupMultiChipTestCase"),
            "hardware")
        self.assertEqual(build_l10.default_dri("hardware"), "Eason Chuang")
        self.assertEqual(build_l10.default_dri("software"), "Software team")
        self.assertEqual(build_l10.as_dri("MTE", "hardware"), "Eason Chuang")
        self.assertEqual(
            build_l10.as_dri("Jonathan Wang", "hardware"), "Jonathan Wang")


class SftReportTest(unittest.TestCase):
    def units(self):
        # SN-A fails, then passes: it counts as a pass, and the failed case
        # is still in the CSV. SN-B fails twice: one failed chassis, two rows.
        return {
            "SN-A": {"sft:attempts": [
                {"status": "fail", "started": "2026-09-24T01:00:00Z",
                 "url": "http://pega4/a1",
                 "failures": [{"test": "FanTest", "caseId": "case-a1",
                               "code": "NA", "at": "2026-09-24T01:01:00Z"}]},
                {"status": "pass", "started": "2026-09-24T03:00:00Z",
                 "url": "http://pega4/a2", "failures": []},
            ]},
            "SN-B": {"sft:attempts": [
                {"status": "fail", "started": "2026-09-24T02:00:00Z",
                 "url": "http://pega4/b1",
                 "failures": [{"test": "FanTest", "caseId": "case-b1",
                               "code": "TH-X", "at": "2026-09-24T02:01:00Z"}]},
                {"status": "fail", "started": "2026-09-24T04:00:00Z",
                 "url": "http://pega4/b2",
                 "failures": [{"test": "FanTest", "caseId": "case-b2",
                               "code": "TH-X", "at": "2026-09-24T04:01:00Z"}]},
            ]},
        }

    def test_retest_pass_is_a_pass_and_a_repeat_fail_counts_once(self):
        report = build_l10.summarize_sft(self.units(), "2026-09-24")
        self.assertEqual(report["tested"], 2)
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["failedSns"], ["SN-B"])
        self.assertAlmostEqual(report["yield"], 0.5)
        by_sn = {}
        for row in report["rows"]:
            by_sn.setdefault(row["sn"], []).append(row)
        self.assertEqual(len(by_sn["SN-A"]), 1)
        self.assertEqual(by_sn["SN-A"][0]["status"], "pass")
        self.assertEqual(by_sn["SN-A"][0]["errorType"], "Passed")
        self.assertEqual(by_sn["SN-A"][0]["url"], "http://pega4/a2")
        self.assertEqual(by_sn["SN-A"][0]["at"], "2026-09-24T03:00:00Z")
        self.assertEqual(by_sn["SN-A"][0]["dri"], "")
        self.assertEqual([row["url"] for row in by_sn["SN-B"]],
                         ["http://pega4/b2"])
        self.assertEqual(report["kinds"][0]["caseIds"], ["case-b2"])
        self.assertEqual(report["kinds"][0]["sns"], ["SN-B"])

    def test_a_later_fail_keeps_the_earlier_pass_time(self):
        units = {
            "SN-D": {"sft:attempts": [
                {"status": "pass", "started": "2026-09-24T01:00:00Z",
                 "url": "http://pega4/d1", "failures": []},
                {"status": "fail", "started": "2026-09-24T04:00:00Z",
                 "url": "http://pega4/d2",
                 "failures": [{"test": "FanTest", "caseId": "d-fail",
                               "code": "NA", "at": "2026-09-24T04:01:00Z"}]},
            ]},
        }
        row = build_l10.summarize_sft(units, "2026-09-24")["rows"][0]
        self.assertEqual(row["status"], "fail")
        self.assertEqual(row["passAt"], "2026-09-24T01:00:00Z")
        self.assertEqual(row["url"], "http://pega4/d2")

    def test_one_run_is_one_table_row_per_failing_leaf(self):
        units = {
            "SN-C": {"sft:attempts": [
                {"status": "fail", "started": "2026-09-24T01:00:00Z",
                 "url": "http://pega4/c1",
                 "failures": [
                     {"test": "C2cLinkupMultiChipTestCase",
                      "caseId": "c-link", "code": "TH-C2C-0001"},
                     {"test": "C2cPrbsMultiChipTestCase",
                      "caseId": "c-prbs", "code": "NA"},
                 ]},
                {"status": "fail", "started": "2026-09-24T01:00:00Z",
                 "url": "http://pega4/c1",
                 "failures": [
                     {"test": "C2cLinkupMultiChipTestCase",
                      "caseId": "c-link", "code": "TH-C2C-0001"},
                 ]},
            ]},
        }
        report = build_l10.summarize_sft(units, "2026-09-24")
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual({row["test"] for row in report["rows"]}, {
            "C2cLinkupMultiChipTestCase", "C2cPrbsMultiChipTestCase",
        })
        self.assertTrue(all(row["url"] == "http://pega4/c1"
                            for row in report["rows"]))
        self.assertTrue(all(row["errorType"] == "hardware"
                            for row in report["rows"]))
        grouped = build_l10.group_fail_rows(report["rows"])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["tests"], [
            "C2cLinkupMultiChipTestCase", "C2cPrbsMultiChipTestCase",
        ])
        self.assertIn(", ", grouped[0]["test"])

    def test_a_missing_code_is_na(self):
        # Codes come only from log.jsonl. Catalogue and payload fields are not
        # a fallback — no log means NA.
        detail = {"test_cases": [
            {"test_name": "GhostTest", "test_id": "case-0", "status": "fail",
             "start_time": "2026-09-24T00:59:00Z",
             "error_message": "TH-GHOST-0001 from the payload"},
            {"test_name": "FanTest", "test_id": "case-1", "status": "fail",
             "start_time": "2026-09-24T01:00:00Z"},
            {"test_name": "KnownTest", "test_id": "case-2", "status": "fail",
             "start_time": "2026-09-24T01:02:00Z",
             "error_code": "TH-FAN-0001"},
        ]}
        rows = build_l10.failure_details(detail, {
            "KnownTest": [{"code": "TH-FAN-0001"}],
            "FanTest": [{"code": "TH-A"}, {"code": "TH-B"}],
        })
        by_id = {row["caseId"]: row["code"] for row in rows}
        self.assertEqual(by_id["case-0"], "NA")
        self.assertEqual(by_id["case-1"], "NA")
        self.assertEqual(by_id["case-2"], "NA")

    def test_a_stored_catalogue_code_is_na_without_a_log(self):
        report = {"rows": [{
            "sn": "SN", "test": "FanTest", "caseId": "case-1",
            "code": "TH-A", "errorType": "hardware",
            "url": "http://pega4/suite_run/L10_SFT_run_missinglog",
        }]}
        build_l10.restamp_fail_codes(report)
        self.assertEqual(report["rows"][0]["code"], "NA")

    @mock.patch("factory.th_logs.cached_codes_for_run",
                return_value={"case-1": ["TH-LOG-0001-S1Q1"]})
    def test_a_log_diagnosis_replaces_the_stored_code(self, _patched):
        report = {"rows": [{
            "sn": "SN", "test": "FanTest", "caseId": "case-1",
            "code": "TH-A", "errorType": "hardware",
            "url": "http://pega4/suite_run/L10_SFT_run_haslog",
        }]}
        build_l10.restamp_fail_codes(report)
        self.assertEqual(report["rows"][0]["code"], "TH-LOG-0001-S1Q1")

    def test_every_diagnosis_code_is_kept(self):
        detail = {"test_cases": [
            {"test_name": "SohuLaneRepairTestCase",
             "test_id": "run_1_chip0_lane_repair", "status": "failed",
             "start_time": "2026-09-24T01:00:00Z",
             "error_message": "TH-HBM-0006-S2Q9 only the preferred one"},
        ]}
        rows = build_l10.failure_details(detail, {}, {
            "chip0_lane_repair": ["TH-HBM-0006-S2Q9", "TH-HBM-0008-S4Q9"],
        }, "run_1")
        self.assertEqual(rows[0]["code"],
                         "TH-HBM-0006-S2Q9\nTH-HBM-0008-S4Q9")
        grouped = build_l10.group_fail_rows([{
            "sn": "SN", "errorType": "Lane Repair", "test": rows[0]["test"],
            "code": rows[0]["code"], "url": "http://pega4/x", "at": "",
        }])
        self.assertEqual(grouped[0]["codes"],
                         ["TH-HBM-0006-S2Q9", "TH-HBM-0008-S4Q9"])

    def test_csv_carries_the_pega_link_and_the_code(self):
        text = build_l10.sft_csv(build_l10.summarize_sft(
            self.units(), "2026-09-24"))
        self.assertIn("http://pega4/a2", text)
        self.assertNotIn("http://pega4/a1", text)
        self.assertIn("http://pega4/b2", text)
        self.assertIn("TH-X", text)
        self.assertIn("errorCode", text)
        self.assertIn("errorType", text.splitlines()[0])
        self.assertIn("pegaUrl", text.splitlines()[0])
        self.assertIn(",dri,", text.splitlines()[0])
        self.assertTrue(text.splitlines()[0].endswith(",jira"))
        self.assertIn("Eason Chuang", text)
        self.assertNotIn("MTE", text)
        self.assertNotIn("caseId", text.splitlines()[0])
        self.assertNotIn("case-b2", text)

    def test_fat_and_rin_use_the_same_shape(self):
        units = {
            "SN-F": {"fat:attempts": [
                {"status": "fail", "started": "2026-09-24T01:00:00Z",
                 "url": "http://pega4/f1",
                 "failures": [{"test": "CheckSystemLogStates",
                               "caseId": "fat-1", "code": "NA",
                               "at": "2026-09-24T01:01:00Z"}]},
            ],
             "rin:attempts": [
                {"status": "fail", "started": "2026-09-24T05:00:00Z",
                 "url": "http://pega4/r1",
                 "failures": [{"test": "RunInStress", "caseId": "rin-1",
                               "code": "TH-R",
                               "at": "2026-09-24T05:01:00Z"}]},
            ]},
        }
        fat = build_l10.summarize_stage(units, "2026-09-24", "fat")
        rin = build_l10.summarize_stage(units, "2026-09-24", "rin")
        self.assertEqual(fat["station"], "l10_fat")
        self.assertEqual(fat["rows"][0]["errorType"], "hardware")
        self.assertEqual(rin["station"], "l10_rin")
        self.assertEqual(rin["rows"][0]["errorType"], "hardware")
        self.assertEqual(rin["rows"][0]["code"], "TH-R")


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


class FaBundleTest(unittest.TestCase):
    def test_daily_fa_keeps_the_reports_and_drops_the_tables(self):
        sft = {"day": "2026-09-23", "tested": 2, "failed": 1, "rows": []}
        fat = {"day": "2026-09-23", "tested": 1, "failed": 1,
               "rows": [{"sn": "SN-F", "errorType": "BMC", "test": "BmcCheck",
                         "at": "", "code": "NA", "url": "http://pega4/f"}]}
        slim = build_dailyexcel.slim_fa_bundle({
            "generatedAt": "2026-09-24T00:00:00+00:00",
            "build": {"commit": "abc"},
            "tabs": [{
                "day": "2026-09-23",
                "label": "09-23",
                "rows": [{}, {}, {}],
                "l10": {"fatReport": fat, "sftReport": sft, "rows": ["heavy"]},
                "columns": ["heavy"],
            }],
        })
        tab = slim["tabs"][0]
        self.assertEqual(tab["day"], "2026-09-23")
        self.assertEqual(tab["units"], 3)
        self.assertEqual(tab["l10"]["sftReport"]["tested"], 2)
        self.assertEqual(tab["l10"]["fatReport"]["rows"][0]["test"], "BmcCheck")
        self.assertNotIn("rows", tab)
        self.assertNotIn("columns", tab)
        self.assertNotIn("rows", tab["l10"])
        self.assertIn("SohuPingTestCase", slim.get("flowStages") or {})

    def test_a_missing_fat_report_is_derived_from_the_l10_table(self):
        columns = build_l10._columns()
        result_at = next(i for i, column in enumerate(columns)
                         if column.get("station") == "l10_fat"
                         and "Results" in column["title"])
        fail_at = result_at + 2
        link_at = result_at + 3
        row = [{} for _ in columns]
        row[1] = {"v": "SN-F"}
        row[result_at] = {"v": "Failed", "t": "fail"}
        row[fail_at] = {"v": "CheckSystemLogStates"}
        row[link_at] = {"v": "short", "h": "http://pega4/f1"}
        slim = build_dailyexcel.slim_fa_bundle({
            "tabs": [{
                "day": "2026-09-23",
                "label": "09-23",
                "l10": {"day": "2026-09-23", "columns": columns, "rows": [row]},
            }],
        })
        fat = slim["tabs"][0]["l10"]["fatReport"]
        self.assertEqual(fat["failed"], 1)
        self.assertEqual(fat["rows"][0]["sn"], "SN-F")
        self.assertEqual(fat["rows"][0]["test"], "CheckSystemLogStates")
        self.assertEqual(fat["rows"][0]["errorType"], "hardware")
        self.assertEqual(fat["rows"][0]["url"], "http://pega4/f1")
        self.assertIn("CheckSystemLogStates", slim.get("errorTypes") or {})
        self.assertEqual(slim["driOptions"],
                         ["Eason Chuang", "Jonathan Wang", "Software team"])

    def test_l6_mlt_and_htt_yields_come_from_the_module_table(self):
        columns = [
            {"key": "A", "title": "Date"},
            {"key": "B", "title": "SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
            {"key": "Ev", "title": "MLT Version", "kind": "version"},
            {"key": "F", "title": "MLT Failure Test Case"},
            {"key": "G", "title": "FI Test Link"},
            {"key": "H", "title": "HTT Results", "station": "htt"},
            {"key": "Hv", "title": "HTT Version", "kind": "version"},
            {"key": "I", "title": "HTT Failure Test Case"},
            {"key": "J", "title": "FI Test Link"},
        ]

        def row(sn, mlt, htt):
            cells = [{} for _ in columns]
            cells[1] = {"v": sn}
            cells[2] = {"v": "Passed" if mlt == "pass" else "Failed", "t": mlt}
            if mlt == "fail":
                cells[4] = {"v": "CheckMlt"}
                cells[5] = {"h": "http://pega3/" + sn}
            if htt in ("pass", "fail"):
                cells[6] = {
                    "v": "Passed" if htt == "pass" else "Failed", "t": htt}
                if htt == "fail":
                    cells[8] = {"v": "CheckHtt"}
                    cells[9] = {"h": "http://pega3/h-" + sn}
            return cells

        slim = build_dailyexcel.slim_fa_bundle({
            "tabs": [{
                "day": "2026-09-23",
                "label": "09-23",
                "columns": columns,
                "rows": [
                    row("SN-A", "pass", "pass"),
                    row("SN-B", "pass", "fail"),
                    row("SN-C", "fail", ""),
                    row("SN-D", "pass", ""),
                ],
            }],
        })
        tab = slim["tabs"][0]
        l6 = tab["l6"]
        self.assertEqual(l6["mltReport"]["tested"], 4)
        self.assertEqual(l6["mltReport"]["passed"], 3)
        self.assertEqual(l6["mltReport"]["yield"], 0.75)
        self.assertEqual(l6["httReport"]["tested"], 2)
        self.assertEqual(l6["httReport"]["passed"], 1)
        self.assertEqual(l6["httReport"]["yield"], 0.5)
        self.assertEqual(l6["combined"]["tested"], 4)
        self.assertEqual(l6["combined"]["passed"], 1)
        self.assertEqual(l6["combined"]["noHtt"], 1)
        self.assertEqual(l6["combined"]["yield"], 0.25)
        failed = [item for item in l6["mltReport"]["rows"]
                  if item.get("status") == "fail"]
        self.assertEqual(failed[0]["sn"], "SN-C")
        self.assertEqual(failed[0]["test"], "CheckMlt")
        self.assertNotIn("rows", tab)
        self.assertNotIn("columns", tab)

    def test_a_blank_result_cell_is_not_counted_from_history(self):
        columns = [
            {"key": "B", "title": "SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
            {"key": "F", "title": "MLT Failure Test Case"},
            {"key": "G", "title": "FI Test Link"},
            {"key": "H", "title": "HTT Results", "station": "htt"},
            {"key": "I", "title": "HTT Failure Test Case"},
            {"key": "J", "title": "FI Test Link"},
        ]
        row = [
            {"v": "SN-H", "history": {"mlt": [
                {"day": "2026-10-01", "status": "pass"}]}},
            {},
            {},
            {},
            {"v": "Passed", "t": "pass"},
            {},
            {"h": "http://pega3/h"},
        ]
        got = build_l10.l6_from_tab({
            "day": "2026-10-01", "columns": columns, "rows": [row],
        })
        self.assertIsNone(got["mltReport"])
        self.assertEqual(got["httReport"]["tested"], 1)
        self.assertEqual(got["httReport"]["passed"], 1)
        self.assertIsNone(got["combined"])

    def test_an_l6_failure_takes_its_test_time_from_the_cached_run(self):
        columns = [
            {"key": "B", "title": "SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
            {"key": "F", "title": "MLT Failure Test Case"},
            {"key": "G", "title": "FI Test Link"},
        ]
        row = [
            {"v": "SN-T"},
            {"v": "Failed", "t": "fail"},
            {"v": "CheckMlt"},
            {"h": "http://pega3:3000/suite_run/mlt_run_abc?slot_number=1"},
        ]
        cached = {
            "start_time": "2026-09-30T16:37:41",
            "test_cases": [{
                "test_name": "CheckMlt",
                "status": "fail",
                "start_time": "2026-09-30T16:40:02",
            }],
        }
        with mock.patch("factory.build_l10.pega._read_cache",
                        return_value=cached) as read:
            report = build_l10.report_from_verdicts({
                "day": "2026-09-30", "columns": columns, "rows": [row],
            }, "mlt")
        read.assert_called_once()
        self.assertEqual(read.call_args[0][0],
                         "/api/test_suite_run/mlt_run_abc")
        self.assertEqual(read.call_args[0][1], "pega3")
        failed = [item for item in report["rows"] if item.get("status") == "fail"]
        self.assertEqual(failed[0]["at"], "2026-09-30T16:40:02")

    def test_an_l6_failure_keeps_the_jira_already_on_the_tracker(self):
        columns = [
            {"key": "B", "title": "SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
            {"key": "F", "title": "MLT Failure Test Case"},
            {"key": "G", "title": "FI Test Link"},
            {"key": "K", "title": "Jira"},
        ]
        row = [
            {"v": "SN-J"},
            {"v": "Failed", "t": "fail"},
            {"v": "CheckMlt"},
            {"h": "http://pega3:3000/suite_run/mlt_run_jira"},
            {"v": "ETCH-38567: CheckMlt", "j": ["ETCH-38567"]},
        ]
        with mock.patch("factory.build_l10.pega._read_cache", return_value={}):
            report = build_l10.report_from_verdicts({
                "day": "2026-09-30", "columns": columns, "rows": [row],
            }, "mlt")
        failed = [item for item in report["rows"] if item.get("status") == "fail"]
        self.assertTrue(failed[0]["jira"].endswith("/ETCH-38567"))


if __name__ == "__main__":
    unittest.main()
