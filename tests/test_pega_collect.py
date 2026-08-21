"""Building the run table from the controllers instead of from EOS.

The point of this collector is that it produces the *same payload shape* the
EOS one does, so every metric and the whole page are reused untouched. Most of
what is worth pinning is therefore about the seams: which suite is which
station, what counts as one run, and whether anything upstream can silently
change a number.
"""

import unittest

from factory import pega_collect, stations


class StationOfTest(unittest.TestCase):
    def test_a_versioned_suite_resolves_to_its_station(self):
        # pega3 names the suite mlt_<version>; EOS reports the test class. Both
        # have to land on the same station or the two pages disagree about
        # which stage a run belongs to.
        self.assertEqual(pega_collect.station_of("pega3", "mlt_2026.220.0-git2f1c2f23"), "mlt")
        self.assertEqual(pega_collect.station_of("pega3", "htt_2026.224.0-gitf4cfee30"), "htt")

    def test_the_eos_spelling_still_resolves_too(self):
        self.assertEqual(stations.classify("module", "rdqs_sweep_training"), "htt")

    def test_a_validation_run_is_not_a_production_station(self):
        # The version is stripped before matching, and stripping it off
        # mlt_2026.220.0-git…_validation leaves "mlt" — which would put an
        # engineering run into the line's yield by an accident of string
        # handling. Engineering is checked on the whole name, first.
        self.assertIsNone(pega_collect.station_of(
            "pega3", "mlt_2026.220.0-git2f1c2f23_validation"))
        self.assertIsNone(pega_collect.station_of(
            "pega3", "htt_2026.217.0-git3940b759_validation"))

    def test_each_controller_maps_its_own_stages(self):
        self.assertEqual(pega_collect.station_of("pega4", "L10_6U_FAT_195"), "l10_fat")
        self.assertEqual(pega_collect.station_of("pega4", "L10_2U_tests"), "l10_2u")
        self.assertEqual(pega_collect.station_of("pega5", "L11_provisioning"), "l11_provision")
        self.assertEqual(pega_collect.station_of("pega5", "L11_rack_power_cycle"), "l11_test")
        self.assertEqual(pega_collect.station_of("pega2", "PROD_01_vbb_provisioning"),
                         "vbb_provision")
        self.assertEqual(pega_collect.station_of("pega2", "PROD_flash_and_lockdown_bootloader"),
                         "vbb_provision")

    def test_engineering_and_unknown_suites_are_dropped(self):
        for host, suite in (("pega4", "L10_6U_FAT_krish"),
                            ("pega2", "test_noBL_provision_internal"),
                            ("pega3", "something_nobody_named"),
                            ("pega3", "")):
            self.assertIsNone(pega_collect.station_of(host, suite), suite)


class RecordTest(unittest.TestCase):
    ENTRY = {"suite_run_id": "mlt_2026.220.0-gitabc_run_4cb95b11",
             "suite_name": "mlt_2026.220.0-gitabc",
             "start_time": "2026-08-13T01:00:00Z", "end_time": "2026-08-13T02:00:00Z",
             "duration_seconds": 3600, "station_id": "pt2_module_station2"}
    DETAIL = {"participating": [
                  {"dut_sn": "268494130000045", "slot_number": 0, "status": "Failed"},
                  {"dut_sn": "268494130000044", "slot_number": 1, "status": "Passed"}],
              "test_cases": [
                  {"test_id": "x_run_4cb95b11_chip0_dma", "test_name": "SohuDmaTestCase",
                   "status": "failed"},
                  {"test_id": "x_run_4cb95b11_chip1_dma", "test_name": "SohuDmaTestCase",
                   "status": "passed"}]}

    def records(self, per_slot=True):
        return pega_collect._records_for(self.ENTRY, self.DETAIL, "pega3",
                                         "module", "mlt", per_slot)

    def test_a_fixture_run_becomes_one_record_per_unit(self):
        # This is the whole difference from the EOS page: eight slots are eight
        # results, not one.
        got = self.records()
        self.assertEqual([r["dutSerial"] for r in got],
                         ["268494130000045", "268494130000044"])
        self.assertEqual([r["status"] for r in got], ["fail", "pass"])

    def test_run_ids_stay_unique_across_slots(self):
        ids = [r["runId"] for r in self.records()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(ids[0].endswith("#slot0"), ids[0])

    def test_a_unit_only_gets_its_own_chip_s_tests(self):
        # Another chip's failures landing here would put one unit's problem in
        # another unit's Pareto.
        first, second = self.records()
        self.assertEqual([t["status"] for t in first["tests"]], ["fail"])
        self.assertEqual([t["status"] for t in second["tests"]], ["pass"])

    def test_failures_are_folded_the_same_way_the_eos_path_folds_them(self):
        first = self.records()[0]
        self.assertEqual(len(first["failures"]), 1)
        self.assertEqual(first["failures"][0]["display"], "SohuDmaTestCase")

    def test_the_controller_s_verdict_survives_the_fold(self):
        # summarize_tests derives a status when none was given; the slot's own
        # verdict is authoritative and must not be recomputed away.
        self.assertEqual(self.records()[0]["status"], "fail")

    def test_a_single_dut_run_is_one_record_with_every_test(self):
        detail = {"participating": None, "dut_sn": "267694410002", "slot_number": 1,
                  "status": "failed", "test_cases": self.DETAIL["test_cases"]}
        got = pega_collect._records_for(self.ENTRY, detail, "pega4", "l10",
                                        "l10_fat", False)
        self.assertEqual(len(got), 1)
        self.assertEqual(len(got[0]["tests"]), 2)
        self.assertEqual(got[0]["runId"], self.ENTRY["suite_run_id"])


class BakeRecordTest(unittest.TestCase):
    """pega6 puts the module serial where every other controller puts a part
    number, and its test ids carry no chip index.

    Both are easy to get wrong in the same direction — quietly. Read the
    participant list the way pega3's is read and every TIM result is filed
    under a coldplate serial, which then matches no MLT row and looks exactly
    like the controller missing data. Apply the slot filter to test cases that
    have no slot in their ids and the unit comes out with a verdict and nothing
    behind it.
    """

    ENTRY = {"suite_run_id": "baking_run_d931db42", "suite_name": "baking",
             "start_time": "2026-08-20T10:19:43Z",
             "end_time": "2026-08-20T11:03:09Z",
             "duration_seconds": 2605.88,
             "station_id": "pt2_baking_station2",
             # The module. On pega3 this field holds "1500027-B".
             "dut_part_number": "268524700000018"}
    DETAIL = {"participating": [
                  # The coldplate the module is bolted to, not the module.
                  {"dut_sn": "268563200097", "slot_number": 14,
                   "status": "failed"}],
              "test_cases": [
                  {"test_id": "baking_run_d931db42_read_coldplate",
                   "test_name": "read_modbus_temperature", "status": "passed"},
                  {"test_id": "baking_run_d931db42_validate_coldplate_temperature",
                   "test_name": "validate_coldplate_temperature",
                   "status": "failed"}]}

    def records(self, entry=None, detail=None):
        return pega_collect._records_for(          # noqa: SLF001
            entry or self.ENTRY, detail or self.DETAIL, "pega6", "module",
            "tim", True)

    def test_the_module_serial_wins_over_the_participant(self):
        got = self.records()
        self.assertEqual(got[0]["dutSerial"], "268524700000018")

    def test_the_carrier_is_kept_rather_than_thrown_away(self):
        """A coldplate is a real object somebody can go and find."""
        self.assertEqual(self.records()[0]["carrierSerial"], "268563200097")

    def test_test_cases_survive_when_no_id_carries_a_chip_index(self):
        """The slot filter has nothing to separate here, so it must not run."""
        got = self.records()
        self.assertEqual(len(got[0]["tests"]), 2)
        self.assertEqual([f["display"] for f in got[0]["failures"]],
                         ["validate_coldplate_temperature"])

    def test_a_six_character_lot_code_is_not_mistaken_for_a_serial(self):
        """Before 2026-08-20 the bake logged SW5VZ8 in that field. Falling back
        to the participant is right there — the run happened and it is about a
        coldplate — and treating the lot code as a module would be worse."""
        entry = dict(self.ENTRY, dut_part_number="SW5VZ8")
        got = self.records(entry=entry)
        self.assertEqual(got[0]["dutSerial"], "268563200097")
        self.assertIsNone(got[0]["carrierSerial"])

    def test_a_multi_participant_run_never_takes_the_entry_serial(self):
        """One entry-level serial cannot be shared out between several
        participants without putting one unit's bake on another's row."""
        detail = dict(self.DETAIL, participating=[
            {"dut_sn": "268563200097", "slot_number": 14, "status": "failed"},
            {"dut_sn": "268563200098", "slot_number": 15, "status": "passed"}])
        got = self.records(detail=detail)
        self.assertEqual([r["dutSerial"] for r in got],
                         ["268563200097", "268563200098"])

    def test_pega3_still_splits_its_cases_by_slot(self):
        """The new rule must not switch the chip filter off where it is needed —
        that would give all eight slots of a fixture every chip's failures."""
        got = pega_collect._records_for(           # noqa: SLF001
            RecordTest.ENTRY, RecordTest.DETAIL, "pega3", "module", "mlt", True)
        self.assertEqual([len(r["tests"]) for r in got], [1, 1])


class BakeStationTest(unittest.TestCase):
    def test_the_bake_suite_resolves_to_tim(self):
        self.assertEqual(pega_collect.station_of("pega6", "baking"), "tim")

    def test_a_renamed_suite_would_still_resolve(self):
        """The registry takes both spellings, so the day somebody renames the
        suite to `tim` does not zero the station."""
        self.assertEqual(pega_collect.station_of("pega6", "tim"), "tim")

    def test_pega6_is_collected(self):
        self.assertIn("pega6", [host for host, _level, _slots
                                in pega_collect.HOSTS])


class AttemptTest(unittest.TestCase):
    def test_attempts_are_numbered_per_station_not_per_level(self):
        # Four L10 stages share the level `l10`. Keying on the level would call
        # a unit's first SFT its second attempt because it had already been
        # through FAT, and first-pass yield would be wrong for three stages.
        records = [
            {"stationKey": "l10_fat", "dutSerial": "A", "level": "l10"},
            {"stationKey": "l10_sft", "dutSerial": "A", "level": "l10"},
            {"stationKey": "l10_fat", "dutSerial": "A", "level": "l10"},
        ]
        pega_collect._mark_attempts(records)
        self.assertEqual([r["attempt"] for r in records], [1, 1, 2])


class FetchStateTest(unittest.TestCase):
    PAYLOAD = {"generatedAt": "2026-08-14T17:00:00+00:00", "runs": [
        {"stationKey": "mlt", "startTs": 1786000000},
        {"stationKey": "mlt", "startTs": 1786100000},
        {"stationKey": "htt", "startTs": 1786050000}]}

    def test_a_live_source_reports_the_build_as_the_fetch(self):
        # Reporting the EOS shape unfilled made the page say "never" under three
        # headings while showing a thousand runs.
        state = pega_collect.fetch_state(self.PAYLOAD)
        self.assertEqual(state["lastFetchAttemptAt"], self.PAYLOAD["generatedAt"])
        self.assertEqual(state["lastFetchStatus"], "ok")

    def test_per_station_counts_use_the_field_the_header_reads(self):
        # `runs`, not `runCount` — a near-miss shows up as "0 runs across all
        # stations" beside a thousand of them.
        state = pega_collect.fetch_state(self.PAYLOAD)
        self.assertEqual(state["stations"]["mlt"]["runs"], 2)
        self.assertEqual(sum(s["runs"] for s in state["stations"].values()), 3)

    def test_the_newest_run_per_station_is_reported(self):
        state = pega_collect.fetch_state(self.PAYLOAD)
        self.assertTrue(state["stations"]["mlt"]["lastUpdateAt"] >
                        state["stations"]["htt"]["lastUpdateAt"])

    def test_no_history_is_invented(self):
        self.assertEqual(pega_collect.fetch_state(self.PAYLOAD)["history"], [])


if __name__ == "__main__":
    unittest.main()
