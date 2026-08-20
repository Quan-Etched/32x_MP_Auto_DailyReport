"""Which suite YAML each station runs, and how much each mapping is worth.

The whole value of the section is the evidence tier. "host/system_test/BUILD
deploys this file under the name the logs carry" and "the filename looked
right" are both mappings and they are not worth the same, so what is asserted
here is not only that the map comes out right but that each entry comes out at
the tier the fact behind it earns.

The normalisation is the other half. Every spelling stripped in these cases is
one seen on a real run — a release stamp, a dated cut, a variant number, the
6U infix that L10 dropped at release 220, a PROD_NN_ prefix a controller adds.
A rule that only handles today's spelling silently zeroes a station the next
time somebody renames one, which is exactly what happened to HTT before.
"""

import unittest

from factory import stations, suite_map


class NormaliseTest(unittest.TestCase):
    """The two systems' spellings have to meet in the middle."""

    def test_a_release_stamp_and_everything_after_it_goes(self):
        self.assertEqual(suite_map.normalise("mlt_2026.220.0-git2f1c2f23"), "mlt")
        self.assertEqual(
            suite_map.normalise("mlt_2026.230.0-gitdb090ec0-tpm-dry-run"), "mlt")

    def test_a_validation_or_debug_cut_reduces_to_its_stage(self):
        self.assertEqual(
            suite_map.normalise("mlt_validation_2026.225.0-gitb937ca2c"), "mlt")
        self.assertEqual(
            suite_map.normalise("debug_only_htt_2026.223.0-git78e6956e2"), "htt")
        self.assertEqual(
            suite_map.normalise("DRYRUN_mlt_2026.205.0-gitaca812f4"), "mlt")

    def test_the_6u_infix_l10_dropped_at_220_is_not_a_different_station(self):
        """L10_6U_FAT became L10_FAT around release 220. A mapping that only
        accepted the new spelling would zero every earlier run."""
        self.assertEqual(suite_map.normalise("L10_6U_FAT"),
                         suite_map.normalise("L10_FAT"))
        self.assertEqual(suite_map.normalise("L10_6U_SFT_207"),
                         suite_map.normalise("L10_SFT"))

    def test_2u_is_a_product_not_an_infix(self):
        """6U collapses because it is a spelling of one stage. 2U must not:
        it is a different chassis with its own suite and its own yield."""
        self.assertNotEqual(suite_map.normalise("L10_2U"),
                            suite_map.normalise("L10_FAT"))
        self.assertEqual(suite_map.normalise("L10_2U_tests"),
                         suite_map.normalise("L10_2U_TestSuite"))

    def test_a_controller_s_prod_prefix_is_not_part_of_the_name(self):
        self.assertEqual(
            suite_map.normalise("CHECK_vbb_setup_validate_token_PROD"),
            suite_map.normalise("vbb_setup_validate_token_PROD"))

    def test_a_dated_cut_reduces_to_its_stage(self):
        self.assertEqual(suite_map.normalise("mlt_20260622"), "mlt")
        self.assertEqual(suite_map.normalise("slt_20260604"), "slt")

    def test_nothing_reduces_to_empty(self):
        """A name that normalised away would match the first file with no
        identity at all, which is worse than not matching."""
        for name in ("mlt", "L10_FAT", "rdqs_sweep_training", "L11_tests"):
            self.assertTrue(suite_map.normalise(name), name)


class TierTest(unittest.TestCase):
    """The ladder, and that it is ordered by consequence."""

    def test_every_tier_the_matcher_can_emit_is_documented(self):
        """A tier with no entry in TIERS renders as a bare slug with no
        explanation, and the explanation is the point."""
        self.assertEqual(set(suite_map.TIER_ORDER),
                         {key for key, _label, _note in suite_map.TIERS})

    def test_read_from_sw_outranks_asserted_by_us(self):
        """A fact in the sw tree beats a mapping this repo asserts. The
        registry tier is ours, so it must never outrank BUILD."""
        order = suite_map.TIER_ORDER
        self.assertLess(order["deployed"], order["registry"])
        self.assertLess(order["pinned"], order["registry"])
        self.assertLess(order["declared"], order["filename"])
        self.assertLess(order["filename"], order["variant"])


class CandidateTest(unittest.TestCase):
    """What identities a file is recognised by, and at what tier."""

    FILES = {
        "chip/parallel/main.yaml": {
            "file": "chip/parallel/main.yaml",
            "suiteName": "chip_screening_parallel",
            "runName": "Parallel Chip Screening",
            "cases": ["SohuDmaTestCase"], "wrappers": [], "error": None},
        "chip/hbm/rdqs_sweep_training.yaml": {
            "file": "chip/hbm/rdqs_sweep_training.yaml",
            "suiteName": "rdqs_sweep_training", "runName": "RDQS Sweep Training",
            "cases": ["SohuSnapTestCase"], "wrappers": [], "error": None},
        "server/L10/L10_FAT.yaml": {
            "file": "server/L10/L10_FAT.yaml",
            "suiteName": None, "runName": "L10_FAT",
            "cases": ["BmcPowerCycle"], "wrappers": [], "error": None},
        "server/L10/L10_tests.yaml": {
            "file": "server/L10/L10_tests.yaml",
            "suiteName": None, "runName": "L10",
            "cases": ["BmcCheck"], "wrappers": [], "error": None},
        "server/L10/ci/L10_tests.yaml": {
            "file": "server/L10/ci/L10_tests.yaml",
            "suiteName": None, "runName": "L10",
            "cases": ["BmcCheck"], "wrappers": [], "error": None},
    }
    DEPLOYED = {
        "test_configs/suite_configs/server/L10/L10_FAT.yaml": {
            "suiteName": "L10_FAT",
            "bom": "test_configs/bom_configs/server/sohu_server_6u_bom.yaml"},
    }
    PINNED = [{
        "suiteName": "mlt",
        "path": ("host/system_test/test_configs/suite_configs/chip/parallel/"
                 "main.yaml"),
        "source": "host/system_test/scripts/make_esvm_config.py",
        "nameSource": "host/system_test/scripts/make_mlt_release.py",
        "why": "the release script names it"}]

    def index(self):
        return suite_map._candidates(                      # noqa: SLF001
            self.FILES, self.DEPLOYED, self.PINNED)

    def best(self, name):
        hits = self.index().get(suite_map.normalise(name)) or []
        return hits[0] if hits else None

    def test_a_release_script_s_pin_is_the_strongest_evidence(self):
        tier, path, _why = self.best("mlt_2026.225.0-gitb937ca2c")
        self.assertEqual((tier, path), ("pinned", "chip/parallel/main.yaml"))

    def test_a_deployed_suite_beats_its_own_run_name(self):
        """L10_FAT is reachable by both, and BUILD naming it is the better
        fact — the run_name is a label for an output folder."""
        tier, path, _why = self.best("L10_6U_FAT")
        self.assertEqual((tier, path), ("deployed", "server/L10/L10_FAT.yaml"))

    def test_a_declared_suite_name_carries_the_file(self):
        tier, path, _why = self.best("chip_screening_parallel")
        self.assertEqual((tier, path), ("declared", "chip/parallel/main.yaml"))

    def test_the_registry_closes_the_htt_gap(self):
        """The controller reports htt_<release> and the file declares
        rdqs_sweep_training. Nothing in sw connects them — grepping that
        repository for "htt" returns nothing — so the registry does."""
        tier, path, _why = self.best("htt_2026.226.0-gitfe7ab71c")
        self.assertEqual((tier, path),
                         ("registry", "chip/hbm/rdqs_sweep_training.yaml"))

    def test_the_registry_also_accepts_the_prefixed_spelling(self):
        tier, path, _why = self.best("htt_rdqs_sweep_training")
        self.assertEqual((tier, path),
                         ("registry", "chip/hbm/rdqs_sweep_training.yaml"))

    def test_a_ci_variant_does_not_win_over_the_suite_above_it(self):
        """Both files carry run_name L10 at the same tier. Alphabetical order
        would pick the ci/ one, and a factory run is not a CI run."""
        tier, path, _why = self.best("L10_tests")
        self.assertEqual((tier, path), ("run_name", "server/L10/L10_tests.yaml"))

    def test_a_station_with_several_candidate_files_gets_no_registry_key(self):
        """Nine VBB suites resolve to vbb_provision. "one of nine" is not
        evidence about which, so the bare station key must index nothing."""
        files = dict(self.FILES)
        for name in ("internal", "external"):
            files["chip/vbb_setup/vbb_setup_provisioning_%s.yaml" % name] = {
                "file": "chip/vbb_setup/vbb_setup_provisioning_%s.yaml" % name,
                "suiteName": None,
                "runName": "VbbCec173xProvisioning" + name.capitalize(),
                "cases": [], "wrappers": [], "error": None}
        index = suite_map._candidates(files, {}, [])       # noqa: SLF001
        tiers = [tier for tier, _path, _why
                 in index.get(suite_map.normalise("vbb_provision")) or []]
        self.assertNotIn("registry", tiers)

    def test_an_operator_s_suffix_falls_back_to_the_base_suite(self):
        found = suite_map._variant_of(                     # noqa: SLF001
            suite_map.normalise("L10_6U_FAT_debug_krish"), self.index())
        self.assertIsNotNone(found)
        self.assertEqual((found[0], found[1]),
                         ("variant", "server/L10/L10_FAT.yaml"))

    def test_a_short_identity_is_not_a_variant_stem(self):
        """`mlt` is three characters. Letting it match by prefix would drag
        every unrelated mlt_* name onto the chip screening suite."""
        self.assertIsNone(suite_map._variant_of(           # noqa: SLF001
            "mlt_something_entirely_else", self.index()))


class CoverageTest(unittest.TestCase):
    """The YAML's cases against the case names the logs carry."""

    SUITES = [{"cases": ["A", "B", "C"]}, {"cases": ["C", "D"]}]

    def test_both_directions_are_reported(self):
        cover = suite_map._coverage(self.SUITES, ["B", "C", "Z"], True)  # noqa: SLF001
        self.assertEqual(cover["defined"], 4)
        self.assertEqual(cover["exercised"], 2)
        self.assertEqual(cover["dark"], ["A", "D"])
        self.assertEqual(cover["extra"], ["Z"])

    def test_a_station_with_no_readable_logs_is_not_reported_as_uncovered(self):
        """EOS cannot read L11 — an IAM denial. Calling all five of its cases
        unexercised would read as a finding about the line when it is one
        about our access."""
        cover = suite_map._coverage(self.SUITES, [], False)  # noqa: SLF001
        self.assertFalse(cover["comparable"])
        self.assertEqual(cover["defined"], 4)


class RunsTest(unittest.TestCase):
    def test_two_readings_of_one_run_are_never_added(self):
        """A run appears once from its controller and again from EOS, under two
        different suite names. Summing them doubles every count on the page."""
        merged = suite_map._merge_runs([                    # noqa: SLF001
            {"runs": {"eos": 275, "pega3": 175}},
            {"runs": {"eos": 25}}])
        self.assertEqual(merged, {"eos": 300, "pega3": 175})


class EngineeringTest(unittest.TestCase):
    def test_a_debug_build_is_kept_as_engineering_not_dropped(self):
        """It is still evidence about which file the station runs; it just must
        not land in the station's numbers."""
        self.assertEqual(
            suite_map._engineering_or_none("L10_6U_FAT_debug"),  # noqa: SLF001
            stations.ENGINEERING)

    def test_a_production_name_is_not_swept_into_engineering(self):
        self.assertIsNone(
            suite_map._engineering_or_none("L10_6U_FAT"))   # noqa: SLF001


class BuildParseTest(unittest.TestCase):
    """The topology read out of host/system_test/BUILD."""

    class FakeTree:
        def __init__(self, contents):
            self.contents = contents

        def read(self, path):
            return self.contents.get(path, "")

    BUILD = '''
validate_suite_configs(
    deploy_configs = [
        deploy_suite(
            bom = "test_configs/bom_configs/server/sohu_server_6u_bom.yaml",
            suite_config = "test_configs/suite_configs/server/L10/L10_FAT.yaml",
            suite_name = "L10_FAT",
        ),
    ],
    runner_by_suite_config_path = {
        "test_configs/suite_configs/server/L10/L10_FAT.yaml": ":L10_test_package",
        "test_configs/suite_configs/chip/parallel/main.yaml": ":single_chip_test_package",
    },
)
'''

    def tree(self):
        return self.FakeTree({suite_map.BUILD_FILE: self.BUILD})

    def test_a_deployed_suite_yields_its_file_name_and_bom(self):
        found = suite_map.deployed_suites(self.tree())
        entry = found["test_configs/suite_configs/server/L10/L10_FAT.yaml"]
        self.assertEqual(entry["suiteName"], "L10_FAT")
        self.assertIn("sohu_server_6u_bom", entry["bom"])

    def test_every_packaged_suite_is_read(self):
        found = suite_map.runner_packages(self.tree())
        self.assertEqual(
            found["test_configs/suite_configs/chip/parallel/main.yaml"],
            ":single_chip_test_package")

    def test_a_missing_build_file_yields_nothing_rather_than_raising(self):
        empty = self.FakeTree({})
        self.assertEqual(suite_map.deployed_suites(empty), {})
        self.assertEqual(suite_map.runner_packages(empty), {})

    def test_a_pin_that_stopped_resolving_is_reported_not_dropped(self):
        """The mechanism working: a renamed constant must surface as a named
        loss, not as an unexplained drop in confidence."""
        found, missing = suite_map.pins(self.FakeTree({}))
        self.assertEqual(found, [])
        self.assertEqual(len(missing), len(suite_map.PINS))
        self.assertTrue(all(entry["source"] for entry in missing))


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
