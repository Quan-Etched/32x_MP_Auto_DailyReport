"""What "Other" was, and why it stopped being the biggest bar.

The Pareto's whole job is to say where to look. "Other" was a third of every
failure on it — the largest bar on the chart, naming nothing and pointing at
nobody, so the one number a reader most wanted to act on was the one that could
not be acted on.

It was not a mystery. The rules were written against EOS class names
(``SohuWeightLoadTestCase`` squashes to ``weightloadtestcase`` and matches
``weightload``), and the controllers emit the *test id* instead —
``weight_load``, ``chip_bin``, ``all_attn_tests``. No rule mentioned those, so
they fell through. These are the signatures that were actually in there.
"""

import unittest

from factory import daily, rootcause, stations


class SignatureTest(unittest.TestCase):
    def test_the_per_run_prefix_is_not_part_of_the_signature(self):
        """4cce7997_chip5_sram_memory and 162b9d25_chip1_sram_memory are one
        test failing on two runs. Counting them apart turns one signature with
        a hundred failures into a hundred signatures with one."""
        for raw in ("4cce7997_chip5_sram_memory", "162b9d25_chip1_sram_memory",
                    "d6e4c797_sohu_sram_memory"):
            with self.subTest(raw=raw):
                self.assertIn("sram_memory", rootcause.signature(raw))
                self.assertFalse(rootcause.signature(raw).startswith("4cce"))

    def test_a_plain_name_is_left_alone(self):
        self.assertEqual(rootcause.signature("all_attn_tests"), "all_attn_tests")

    def test_it_falls_back_through_the_signals(self):
        self.assertEqual(rootcause.signature(None, "", "kv_flush_tests"),
                         "kv_flush_tests")


class BucketingTest(unittest.TestCase):
    #: Signature -> the area it must land in. Every one of these was in "Other"
    #: and is listed here in the order it appeared, most failures first.
    EXPECTED = [
        ("weight_load", "Weight Load"),
        ("chip_bin", "Chip ID / eFuse / Bin"),
        ("chip_id", "Chip ID / eFuse / Bin"),
        ("efuse_test", "Chip ID / eFuse / Bin"),
        ("all_attn_tests", "Attention / KV Flush"),
        ("all_attn_hbm_bypass_tests", "Attention / KV Flush"),
        ("kv_flush_tests", "Attention / KV Flush"),
        ("kv_flush_and_attention_interleaved", "Attention / KV Flush"),
        ("sau_pll_phase_alignment", "SAU PLL / Clocking"),
        ("sa_column_screen_soldered", "SA Screening"),
        ("detect_board_dvfs_profile", "DVFS / Board Profile"),
        ("gpio_test", "GPIO"),
        ("pcie_lane_margin", "PCIe Lane Margin"),
        ("hbm_device_id", "HBM Device ID"),
        ("sram_memory", "SRAM"),
        ("clear_flash_init_config", "Flash / Init Config"),
        ("INSTALL_LINUX_PACKAGES", "OS / Packages"),
        ("BMC_PWR_CYCLE", "BMC / Power Cycle"),
        ("UPDATE_PLX_DAEMON_FW", "Firmware / BIOS Update"),
        ("CHK_PSU_FW_VER", "PSU"),
        ("VBB_UPDATE", "Firmware / BIOS Update"),
        ("CHK_DISK", "Disk"),
        ("CHK_CPU", "CPU / Stress"),
        ("CHK_LOM_NIC_MAC", "NIC / Link"),
        ("CHK_PCIE_TOPOLOGY", "PCIe Setup"),
    ]

    def test_every_signature_that_was_in_other_now_has_an_area(self):
        for signature, area in self.EXPECTED:
            with self.subTest(signature=signature):
                self.assertEqual(rootcause.area(signature), area)

    def test_the_run_prefix_does_not_stop_a_match(self):
        """area() matches on substrings and does not care about the prefix —
        pinned so nobody 'fixes' it by stripping first and changing behaviour."""
        self.assertEqual(rootcause.area("4cce7997_chip5_sram_memory"), "SRAM")

    def test_the_existing_eos_class_names_still_bucket_the_same_way(self):
        """The rules are shared with test-daily. Adding the controllers' ids
        must not move an EOS signature to a different area."""
        for signature, area in (("SohuPmbistTestCase", "PMBIST"),
                                ("C2cLinkupTestCase", "C2C"),
                                ("SohuPowerVirusTestCase", "Power Virus / Thermal"),
                                ("SohuRdqsSweepTrainingTestCase", "RDQS Training")):
            with self.subTest(signature=signature):
                self.assertEqual(rootcause.area(signature), area)

    def test_an_unknown_signature_still_falls_to_other(self):
        """Other has to keep existing — a bucket that catches everything is
        useless, and so is one that catches nothing."""
        self.assertEqual(rootcause.area("something_nobody_has_seen"), "Other")


class ParetoDetailTest(unittest.TestCase):
    """A bar is a question, so the answer travels with it."""

    def runs(self):
        def run(station, dut, tests):
            return {"stationKey": station, "dutSerial": dut, "status": "fail",
                    "failures": [{"test": t, "display": t} for t in tests]}
        return [
            # Real run stamps: eight hex, then the chip index.
            run("mlt", "SN1", ["4cce7997_chip0_sram_memory",
                               "4cce7997_chip1_sram_memory"]),
            run("mlt", "SN2", ["162b9d25_chip0_sram_memory"]),
            run("l10_fat", "SN3", ["CHK_DISK"]),
        ]

    def rows(self):
        return {r["area"]: r for r in daily.top_yield_hits(self.runs())}

    def test_it_says_where_the_failure_happened(self):
        """The tooltip named one test out of thirty and never said which
        station — which is the thing that decides who owns the fix."""
        sram = self.rows()["SRAM"]
        self.assertEqual([s["station"] for s in sram["byStation"]], ["mlt"])
        self.assertEqual(sram["byStation"][0]["label"], "MLT")
        self.assertEqual(sram["byStation"][0]["fails"], 3)
        self.assertEqual(sram["byStation"][0]["duts"], 2)

    def test_tests_are_grouped_on_the_signature_not_the_run(self):
        """Three raw ids, one test. Ungrouped this reads as three problems."""
        sram = self.rows()["SRAM"]
        self.assertEqual(sram["byTest"], [{"test": "sram_memory", "fails": 3}])
        self.assertEqual(sram["testCount"], 1)

    def test_it_names_the_units(self):
        sram = self.rows()["SRAM"]
        self.assertEqual(sram["topDuts"],
                         [{"dut": "SN1", "fails": 2}, {"dut": "SN2", "fails": 1}])

    def test_each_area_carries_only_its_own(self):
        disk = self.rows()["Disk"]
        self.assertEqual([s["station"] for s in disk["byStation"]], ["l10_fat"])
        self.assertEqual(disk["topDuts"], [{"dut": "SN3", "fails": 1}])


class StationLabelTest(unittest.TestCase):
    def test_a_key_becomes_the_lines_own_name(self):
        self.assertEqual(stations.label_of("l10_fat"), "L10 FAT")
        self.assertEqual(stations.label_of("mlt"), "MLT")

    def test_an_unknown_key_is_kept_rather_than_blanked(self):
        """A breakdown row that cannot say where a failure happened should say
        that, not say nothing."""
        self.assertEqual(stations.label_of("brand_new"), "brand_new")
        self.assertEqual(stations.label_of(None), stations.UNCLASSIFIED)


if __name__ == "__main__":
    unittest.main()
