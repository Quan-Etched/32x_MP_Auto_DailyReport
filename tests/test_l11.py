"""The L11 daily tracker: rack provisioning and rack test from pega5."""

import unittest

from factory import build_dailyexcel, build_l11


class StageTest(unittest.TestCase):
    def test_the_rack_power_cycle_suites_are_the_test_stage(self):
        # The three spellings pega5 has used. A pattern matching only today's
        # name silently zeroes a station the next time the line renames one.
        for suite in ("L11_Rack_Power_Cycle_no_CDU",
                      "L11_Rack_Power_Cycle_AC_Cycle_fix",
                      "L11_Rack_Power_Cycle_no_CDU_All_SS_Continue"):
            self.assertEqual(build_l11.stage_of(suite), "test", suite)

    def test_provisioning_wins_over_the_l11_prefix(self):
        """kamil_L11_provisioning… contains L11 too. Order decides, and
        getting it wrong would file every provisioning run under Test."""
        self.assertEqual(
            build_l11.stage_of("kamil_L11_provisioning_rms_pdu_cdu"), "provision")
        self.assertEqual(build_l11.stage_of("L11_provisioning"), "provision")

    def test_an_engineers_name_does_not_drop_the_run(self):
        """Every provisioning run pega5 has is engineer-named. Dropping them
        would leave the stage permanently empty, which is a worse lie than
        counting them — so they are counted and flagged instead."""
        suite = "kamil_L11_provisioning_rms_pdu_cdu"
        self.assertIsNotNone(build_l11.stage_of(suite))
        self.assertTrue(build_dailyexcel.NON_RELEASE.search(suite))

    def test_the_flag_cannot_reach_a_module_suite(self):
        for suite in ("mlt_2026.220.0-git2f1c2f23", "htt_rdqs_sweep_training",
                      "L10_FAT", "L10_2U_tests"):
            self.assertFalse(build_dailyexcel.NON_RELEASE.search(suite), suite)

    def test_dev_suites_are_not_stages(self):
        for suite in ("DRY_RUN_L11_Rack_Power_Cycle", "L11_SMOKE",
                      "L11_Rack_out_dir", "test_L11_thing", "L11_etch33931"):
            self.assertIsNone(build_l11.stage_of(suite), suite)

    def test_an_unknown_suite_is_not_forced_into_a_stage(self):
        self.assertIsNone(build_l11.stage_of("something_new"))
        self.assertIsNone(build_l11.stage_of(None))
        self.assertIsNone(build_l11.stage_of("L10_FAT"))


class FailureTest(unittest.TestCase):
    def test_aborted_cases_are_not_listed_as_failures(self):
        """When a rack aborts, every case after the one that stopped it is
        also aborted. Listing them buries the single line that says what
        happened under five that say what never got a chance to."""
        detail = {"test_cases": [
            {"test_name": "RackPowerCycleWaitInfraOnline", "status": "failed",
             "start_time": "01"},
            {"test_name": "CduHealthCheckTestCase", "status": "aborted",
             "start_time": "02"},
            {"test_name": "PduHealthCheckTestCase", "status": "aborted",
             "start_time": "03"},
        ]}
        self.assertEqual(build_l11.unit_failures(detail),
                         "RackPowerCycleWaitInfraOnline")

    def test_skipped_is_not_a_failure_either(self):
        detail = {"test_cases": [
            {"test_name": "CduHealthCheckTestCase", "status": "skipped",
             "start_time": "01"},
            {"test_name": "PduHealthCheckTestCase", "status": "failed",
             "start_time": "02"},
        ]}
        self.assertEqual(build_l11.unit_failures(detail),
                         "PduHealthCheckTestCase")


class ColumnTest(unittest.TestCase):
    def test_four_columns_per_stage_after_the_rack(self):
        columns = build_l11._columns()
        titles = [c["title"] for c in columns]
        self.assertEqual(titles[:3], ["Date", "SN", "DUT PN"])
        self.assertEqual(len(titles), 3 + 2 * 4)
        self.assertEqual(titles[3], "L11 Provision Results")
        self.assertEqual(titles[7], "L11 Test Results")

    def test_each_result_column_names_its_station(self):
        stations = [c.get("station") for c in build_l11._columns()
                    if c["title"].endswith("Results")]
        self.assertEqual(stations, ["l11_provision", "l11_test"])

    def test_only_result_columns_are_tallied(self):
        columns = build_l11._columns()
        counts = build_l11._counts([[{} for _ in columns]], columns)
        self.assertEqual(sorted(counts), ["D", "H"])


class AbortTest(unittest.TestCase):
    """An aborted rack is not an un-run one, and the tally must not say so."""

    def test_abort_is_its_own_bucket(self):
        columns = build_l11._columns()
        rows = [
            [{}, {"v": "266447160001"}, {}, {"v": "Aborted", "t": "abort"},
             {"v": "L11_provisioning"}, {}, {}, {}, {}, {}, {}],
            [{}, {"v": "450968450698"}, {}, {"v": "Failed", "t": "fail"},
             {"v": "L11_provisioning"}, {}, {}, {}, {}, {}, {}],
        ]
        counts = build_l11._counts(rows, columns)["D"]
        self.assertEqual(counts["abort"], 1)
        self.assertEqual(counts["fail"], 1)
        # The one that matters: an abort must not land in "not run".
        self.assertEqual(counts["blank"], 0)

    def test_the_other_trackers_keep_an_empty_abort_bucket(self):
        """Shared arithmetic, so the key exists everywhere — it is just always
        zero where a station only ever reports pass or fail."""
        from factory import build_l10
        columns = build_l10._columns()
        rows = [[{}, {"v": "267694410002"}, {}, {"v": "Passed", "t": "pass"}]
                + [{}] * (len(columns) - 4)]
        self.assertEqual(build_l10._counts(rows, columns)["D"]["abort"], 0)


class DayTest(unittest.TestCase):
    LISTING = [
        {"suite_run_id": "kamil_L11_provisioning_rms_pdu_cdu_run_c8b8794f",
         "suite_name": "kamil_L11_provisioning_rms_pdu_cdu",
         "dut_part_number": "PN-001", "start_time": "2026-08-18T02:36:51Z"},
        {"suite_run_id": "kamil_L11_provisioning_rms_pdu_cdu_run_2e6d87fa",
         "suite_name": "kamil_L11_provisioning_rms_pdu_cdu",
         "dut_part_number": "PN-001", "start_time": "2026-08-18T03:06:07Z"},
        {"suite_run_id": "L11_Rack_Power_Cycle_no_CDU_run_d8f96b35",
         "suite_name": "L11_Rack_Power_Cycle_no_CDU",
         "dut_part_number": "PN-001", "start_time": "2026-08-18T04:00:00Z"},
        {"suite_run_id": "DRY_RUN_L11_Rack_run_ignored",
         "suite_name": "DRY_RUN_L11_Rack",
         "dut_part_number": "PN-001", "start_time": "2026-08-18T05:00:00Z"},
    ]
    DETAIL = {
        "kamil_L11_provisioning_rms_pdu_cdu_run_c8b8794f": {
            "status": "failed", "participating": None, "dut_sn": "266447170002",
            "test_cases": [{"test_name": "ProvisionPrimaryRms",
                            "status": "failed", "start_time": "01"}]},
        "kamil_L11_provisioning_rms_pdu_cdu_run_2e6d87fa": {
            "status": "passed", "participating": None, "dut_sn": "266447170002",
            "test_cases": []},
        "L11_Rack_Power_Cycle_no_CDU_run_d8f96b35": {
            "status": "aborted", "participating": None, "dut_sn": "266447170002",
            "test_cases": []},
        "DRY_RUN_L11_Rack_run_ignored": {
            "status": "passed", "participating": None, "dut_sn": "999",
            "test_cases": []},
    }

    def setUp(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, pega, "suite_run", pega.suite_run)
        pega.day_suite_runs = lambda day, host=None: (
            list(self.LISTING) if day == "2026-08-18" else [])
        pega.suite_run = lambda run_id, host=None: self.DETAIL[run_id]

    def test_one_row_per_rack_with_both_stages_on_it(self):
        tab = build_l11._day("2026-08-18")
        self.assertEqual(len(tab["rows"]), 1)
        row = tab["rows"][0]
        self.assertEqual(row[1]["v"], "266447170002")
        self.assertEqual(row[3]["v"], "Passed")          # last provision wins
        self.assertEqual(row[7]["v"], "Aborted")         # and it is shown

    def test_the_last_attempt_wins_but_the_count_is_kept(self):
        """Two provisioning attempts, the later one passing. Showing only the
        pass would make an afternoon of firefighting look like one quiet
        test."""
        row = build_l11._day("2026-08-18")["rows"][0]
        self.assertEqual(row[3]["tries"], 2)
        self.assertNotIn("tries", row[7])                # one attempt, no chip

    def test_the_suite_cell_stays_a_clean_suite_name(self):
        """It is what the release tally is matched against; an attempt count
        glued onto it would leak into that."""
        row = build_l11._day("2026-08-18")["rows"][0]
        self.assertEqual(row[4]["v"], "kamil_L11_provisioning_rms_pdu_cdu")

    def test_bring_up_runs_are_counted_and_held_out_of_the_release_figure(self):
        counts = build_l11._day("2026-08-18")["counts"]["D"]
        self.assertEqual(counts["pass"], 1)
        self.assertEqual(counts["release"], {"pass": 0, "fail": 0,
                                             "abort": 0, "blank": 0})
        self.assertEqual(counts["nonRelease"],
                         ["kamil_L11_provisioning_rms_pdu_cdu"])

    def test_dev_runs_never_reach_the_page(self):
        tab = build_l11._day("2026-08-18")
        self.assertEqual(tab["derivedFrom"]["runs"], 3)
        self.assertNotIn("999", [r[1].get("v") for r in tab["rows"]])

    def test_the_link_points_at_pega5(self):
        row = build_l11._day("2026-08-18")["rows"][0]
        self.assertIn("pega5:3000/suite_run/", row[6]["h"])

    def test_a_day_with_no_l11_runs_is_no_table(self):
        self.assertIsNone(build_l11._day("2026-08-17"))

    def test_an_unreachable_pega5_is_not_a_failed_build(self):
        from factory import pega

        def boom(day, host=None):
            raise pega.PegaUnavailable("no route")
        pega.day_suite_runs = boom
        self.assertIsNone(build_l11._day("2026-08-18"))


class AttachTest(unittest.TestCase):
    def test_l11_is_looked_for_on_every_published_day(self):
        """The floor was at 08-17, which kept the rack power-cycle campaign of
        08-11 to 08-14 off the only page it can be seen on. The table names
        pega5 as its source, so an early day cannot read as sheet data."""
        self.assertEqual(build_dailyexcel.L11_FROM, build_dailyexcel.L10_FROM)

    def test_an_l11_build_error_does_not_take_the_module_tab_with_it(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)

        def boom(day, host=None):
            raise ValueError("pega5 returned something unexpected")
        pega.day_suite_runs = boom
        self.assertIsNone(build_dailyexcel._l11_for("2026-08-18"))


if __name__ == "__main__":
    unittest.main()
