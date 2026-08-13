"""Per-chip grading inside a fixture run.

The numbers pinned here are from a real run,
``mlt_2026.220.0-git2f1c2f23_20260812_013949``: 492 tests, run status ``fail``,
four good chips and four bad. That run is also the one visible in the OCP Logs
screenshot that prompted the work, so the fixture below is a faithful miniature
of it rather than an invented shape.
"""

import unittest

from factory import chips


def test(name, status, display=None):
    return {"name": name, "status": status, "displayName": display or name}


#: One fixture run: a passing chip, a chip failing a leaf, a chip whose only
#: failure is the container, and a fixture-level failure that belongs to none.
RUN = {
    "runId": "mlt_2026.220.0-git2f1c2f23_20260812_013949",
    "status": "fail",
    "tests": [
        test("server_setup", "fail", "ServerNestedTestCase"),
        test("rig_power_check", "fail", "RigPowerTestCase"),
        test("server_setup_bootloader_result_chip0", "pass", "BootloaderResultTestCase"),
        test("server_setup_bootloader_result_chip4", "fail", "BootloaderResultTestCase"),
        test("chip1", "fail", "SltModuleNestedTestCase"),
        test("chip1_mtc_stress", "error", "SohuMtcStressTestCase"),
        test("chip3", "fail", "SltModuleNestedTestCase"),
        test("chip3_run_kv_flush_tests", "fail", "RunKvFlushTestsSingleChipTestCase"),
        test("chip5_llama70b_tp1_forward_iterated", "pass", "SohuLlamaForwardIteratedTestCase"),
        test("chip6_skipped_thing", "skip", "SohuThingTestCase"),
    ],
}


class ChipIndexTest(unittest.TestCase):
    def test_both_spellings_and_bare_names_parse(self):
        self.assertEqual(chips.chip_of("server_setup_bootloader_result_chip4"), 4)
        self.assertEqual(chips.chip_of("chip6_llama70b_tp1_forward_iterated"), 6)
        self.assertEqual(chips.chip_of("chip3"), 3)
        self.assertEqual(chips.chip_of("vbb_dependent_tests_i2c_chip12"), 12)

    def test_a_fixture_level_name_has_no_chip(self):
        self.assertIsNone(chips.chip_of("server_setup"))
        self.assertIsNone(chips.chip_of("vbb_dependent_tests"))
        self.assertIsNone(chips.chip_of(""))
        self.assertIsNone(chips.chip_of(None))

    def test_a_number_that_is_not_a_chip_index_is_ignored(self):
        self.assertIsNone(chips.chip_of("llama70b_tp1_forward"))
        self.assertIsNone(chips.chip_of("hbm2_ch0_pc0"))


class GradeTest(unittest.TestCase):
    def setUp(self):
        self.graded = chips.grade(RUN)
        self.chips = self.graded["chips"]

    def test_a_failing_leaf_fails_only_its_own_chip(self):
        self.assertEqual(self.chips[4]["status"], "fail")
        self.assertEqual(self.chips[0]["status"], "pass")

    def test_the_failure_reported_is_the_class_the_line_writes_down(self):
        # Not 'server_setup_bootloader_result_chip4' — the tracker's column
        # says BootloaderResultTestCase, and that is the shared signature.
        self.assertEqual(self.chips[4]["firstFail"], "BootloaderResultTestCase")
        self.assertEqual(self.chips[1]["firstFail"], "SohuMtcStressTestCase")
        self.assertEqual(self.chips[3]["firstFail"], "RunKvFlushTestsSingleChipTestCase")

    def test_a_fixture_level_container_is_not_a_fixture_failure_either(self):
        # server_setup is a nest: it "failed" only because the chip4 leaf under
        # it did, and that leaf is already charged to chip4. Counting the
        # parent as well would report the same failure twice.
        self.assertEqual(self.graded["fixture"]["count"], 1)

    def test_containers_are_excluded_so_they_never_become_the_signature(self):
        # chip1 and chip3 are SltModuleNestedTestCase parents; the useful name
        # is always the leaf underneath.
        for entry in self.chips.values():
            self.assertNotEqual(entry["firstFail"], "SltModuleNestedTestCase")

    def test_an_error_counts_as_a_failure(self):
        self.assertEqual(self.chips[1]["status"], "fail")

    def test_a_chip_with_only_skips_is_not_graded_as_passing(self):
        self.assertEqual(self.chips[6]["status"], "skip")

    def test_a_fixture_failure_is_not_charged_to_any_chip(self):
        # A leaf failure with no chip index is the rig, the server or the
        # harness. Blaming a slot for it would be a guess.
        self.assertTrue(self.graded["fixture"]["failed"])
        self.assertEqual(self.graded["fixture"]["firstFail"], "rig_power_check")
        # chip5's only test passed; the rig's failure must not taint it.
        self.assertEqual(self.chips[5]["status"], "pass")

    def test_the_run_level_verdict_and_the_chip_verdicts_disagree_on_purpose(self):
        # This is the whole point: EOS says one thing, the line says eight.
        self.assertEqual(RUN["status"], "fail")
        self.assertEqual(
            sorted(entry["status"] for entry in self.chips.values()),
            ["fail", "fail", "fail", "pass", "pass", "skip"],
        )


class SummarizeTest(unittest.TestCase):
    def test_units_are_counted_not_runs(self):
        summary = chips.summarize([RUN])
        self.assertEqual(summary["runs"], 1)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 3)
        self.assertEqual(summary["ungraded"], 1)      # the skip-only chip

    def test_yield_excludes_ungraded_chips_from_the_denominator(self):
        summary = chips.summarize([RUN])
        self.assertAlmostEqual(summary["yield"], 2 / 5)

    def test_a_run_with_no_chip_tests_is_skipped_not_counted_as_zero(self):
        plain = {"status": "pass", "tests": [test("server_setup", "pass")]}
        summary = chips.summarize([plain])
        self.assertEqual(summary["runs"], 0)
        self.assertIsNone(summary["yield"])

    def test_no_runs_yields_none_rather_than_dividing_by_zero(self):
        self.assertIsNone(chips.summarize([])["yield"])


if __name__ == "__main__":
    unittest.main()
