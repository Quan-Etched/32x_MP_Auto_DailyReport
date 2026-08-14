"""Station registry, release numbering and root-cause bucketing."""

import unittest

from factory import rootcause, stations


class ClassifyTest(unittest.TestCase):
    def test_live_suite_names_land_on_the_right_station(self):
        cases = [
            ("module", "mlt", "mlt"),
            # The same suite also lands under slt (from 2026-08-11). Matching
            # only `module` left 32 real MLT runs in the unclassified bucket.
            ("slt", "mlt", "mlt"),
            ("l10", "L10_6U_FAT", "l10_fat"),
            ("l10", "L10_6U_SFT", "l10_sft"),
            ("l10", "L10_6U_RIN", "l10_rin"),
            # Release 220 (2026-08-10) dropped the 6U_ infix. Both spellings
            # have to land, or the rename zeroes the station.
            ("l10", "L10_FAT", "l10_fat"),
            ("l10", "L10_SFT", "l10_sft"),
            ("l10", "L10_RIN", "l10_rin"),
            ("l10", "L10_2U", "l10_2u"),
            # HTT's suite name says nothing about HTT; the mapping comes from
            # the OCP Logs family column, and the htt_ prefix is a rename that
            # started appearing 2026-08-12.
            ("module", "rdqs_sweep_training", "htt"),
            ("module", "htt_rdqs_sweep_training", "htt"),
            ("slt", "slt", "slt"),
            ("slt", "Sohu_SLT", "slt"),
            ("slt", "chip_screening_parallel", "chip_screening"),
            ("module", "chip_screening_parallel", "chip_screening"),
        ]
        for level, suite, expected in cases:
            self.assertEqual(stations.classify(level, suite), expected,
                             "{}/{}".format(level, suite))

    def test_debug_variants_are_excluded_from_production_yield(self):
        # L10_6U_FAT_krish is an engineering run; folding it into FAT would move
        # the number the line reports. They land in ENGINEERING rather than
        # UNCLASSIFIED: both are kept out of line-wide yield, but only one of
        # them is an open question for somebody.
        for suite in ("L10_6U_FAT_krish", "L10_6U_FAT_debug_krish",
                      "L10_6U_MEM_etch33931",
                      # 22 of 23 runs error out — a dev suite, not a stage.
                      "L10_tests",
                      # 2 test cases against L10_2U's 26.
                      "L10_2U_SMOKE"):
            self.assertEqual(stations.classify("l10", suite), stations.ENGINEERING, suite)

    def test_engineering_and_unclassified_are_different_answers(self):
        # "we know what this is and it is not production" vs "nobody has worked
        # out what this is". Collapsing them buried the second in the first.
        self.assertEqual(stations.classify("module", "selfheal_repro_a"),
                         stations.ENGINEERING)
        self.assertEqual(stations.classify("l10", "something_nobody_named"),
                         stations.UNCLASSIFIED)

    def test_vbb_provisioning_is_a_station(self):
        # 289 runs — the largest single group EOS returns — sat unclassified
        # until pega2 showed a dedicated station (pt2_l6_vbb1) with its own part
        # number driving them.
        for suite in ("VbbCec173xProvisioningInternal", "VbbFlashAndLockBootloader",
                      "VbbValidateProductionProvisioning",
                      "VbbCec173xProvisioningExternalProd"):
            self.assertEqual(stations.classify("l6", suite), "vbb_provision", suite)

    def test_vbb_patterns_accept_pega2_s_own_spelling(self):
        # EOS reports the test-class name, pega2 the suite it ran under; the
        # same stage is spelled differently in the two systems.
        for suite in ("PROD_01_vbb_provisioning",
                      "PROD_02_vbb_validate_production_provisioning",
                      "CHECK_vbb_setup_validate_token_PROD"):
            self.assertEqual(stations.classify("l6", suite), "vbb_provision", suite)

    def test_a_station_records_which_controller_drives_it(self):
        by_key = {s.key: s for s in stations.STATIONS}
        self.assertEqual(by_key["mlt"].controller, "pega3")
        self.assertEqual(by_key["l10_fat"].controller, "pega4")
        self.assertEqual(by_key["l11_provision"].controller, "pega5")
        self.assertEqual(by_key["vbb_provision"].controller, "pega2")

    def test_level_is_part_of_the_match(self):
        self.assertEqual(stations.classify("module", "L10_6U_FAT"), stations.UNCLASSIFIED)

    def test_blocked_stations_never_capture_runs(self):
        # L11's patterns exist but are unverified guesses, so they must not
        # swallow live suites from the levels we can actually read.
        for suite in ("mlt", "slt", "L10_6U_FAT", "chip_screening_parallel",
                      "rdqs_sweep_training"):
            key = stations.classify("l10", suite)
            self.assertNotIn(key, ("l11_provision", "l11_test"), suite)

    def test_htt_does_not_poach_the_other_module_suites(self):
        # HTT and MLT share the module level, so its pattern has to be anchored.
        for suite in ("mlt", "chip_screening_parallel", "selfheal_repro_a"):
            self.assertNotEqual(stations.classify("module", suite), "htt", suite)

    def test_registry_is_complete_and_ordered(self):
        keys = [s["key"] for s in stations.registry()]
        for expected in ("mlt", "htt", "l10_fat", "l10_sft", "l10_rin", "l10_2u",
                         "l11_provision", "l11_test", "slt", "chip_screening"):
            self.assertIn(expected, keys)
        orders = [s["order"] for s in stations.registry()]
        self.assertEqual(orders, sorted(orders))

    def test_levels_to_collect_excludes_blocked_and_unmapped(self):
        levels = stations.levels_to_collect()
        self.assertIn("l10", levels)
        self.assertIn("module", levels)
        self.assertNotIn("l11", levels)
        self.assertEqual(stations.blocked_levels(), ["l11"])


class ReleaseTest(unittest.TestCase):
    def test_release_is_the_middle_component(self):
        self.assertEqual(stations.release_of("2026.207.0-gitd45c8636"), "207")
        self.assertEqual(stations.release_of("2026.190.11-git120599a7"), "190")

    def test_unparseable_versions_keep_their_string(self):
        self.assertEqual(stations.release_of("nightly"), "nightly")
        self.assertIsNone(stations.release_of(None))

    def test_releases_sort_numerically(self):
        got = sorted(["10", "9", "203", None, "nightly"], key=stations.release_sort_key)
        self.assertEqual(got[:3], ["9", "10", "203"])
        self.assertIsNone(got[-1])


class RootCauseTest(unittest.TestCase):
    def test_camelcase_class_names_match(self):
        self.assertEqual(rootcause.area(None, "SohuServerBiosUpdate"),
                         "Firmware / BIOS Update")

    def test_snake_case_ids_match_after_separators_are_stripped(self):
        # The rules were written against CamelCase; without the squashed pass
        # every EOS identifier falls through to Other.
        self.assertEqual(rootcause.area("chip1_hot_reload_firmware_update"),
                         "Firmware / BIOS Update")
        self.assertEqual(rootcause.area("chip1_c2c_integrity"), "C2C")
        self.assertEqual(rootcause.area("server_setup_thermal_diode_chip1"),
                         "Power Virus / Thermal")

    def test_first_matching_rule_wins(self):
        # C2C is listed before the firmware family, so a name carrying both
        # keeps the earlier bucket.
        self.assertEqual(rootcause.area("c2c_firmware_update"), "C2C")

    def test_unknown_signature_is_other(self):
        self.assertEqual(rootcause.area("chip1"), rootcause.OTHER)
        self.assertEqual(rootcause.area(None, None), rootcause.OTHER)

    def test_nested_containers_are_recognised(self):
        # These are parent nodes; counting them double-counts every failure.
        self.assertTrue(rootcause.is_container("SltModuleNestedTestCase"))
        self.assertTrue(rootcause.is_container("ServerNestedTestCase"))
        self.assertFalse(rootcause.is_container("SohuVrmTestCase"))
        self.assertFalse(rootcause.is_container(None))


if __name__ == "__main__":
    unittest.main()
