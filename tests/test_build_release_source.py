"""What a release contains, read from source rather than from logs.

The point of the page: a test case that was added and never reached, or removed
and so never seen again, leaves no trace in a test log. "It stopped failing" and
"it stopped running" look identical from the outside and only one is good news.
"""

import unittest

from factory import build_release_source as brs

SUITE = """
run_name: Parallel Chip Screening
suite_name: chip_screening_parallel
_anchors:
  common: &common
    timeout: 30
tests_to_run:
  - name: ServerSetup
    tests:
      - name: ServerNestedTestCase
        tests:
          - name: PcieSetupTestCase
            <<: *common
          - name: SohuDmaTestCase
  - name: Fanout
    tests:
      - name: SltModuleNestedTestCase
        tests:
          - name: SohuPowerVirusTestCase
          - name: SohuSramMemoryTestCase
"""


class ParseTest(unittest.TestCase):
    def walk(self, text=SUITE):
        try:
            import yaml
        except ImportError:                                # pragma: no cover
            self.skipTest("PyYAML not available")
        return brs._walk(yaml.safe_load(text))             # noqa: SLF001

    def test_leaf_test_cases_are_found_through_the_nesting(self):
        names = {c["name"] for c in self.walk()["cases"]}
        self.assertIn("PcieSetupTestCase", names)
        self.assertIn("SohuPowerVirusTestCase", names)
        self.assertIn("SohuSramMemoryTestCase", names)

    def test_group_names_are_not_test_cases(self):
        """"ServerSetup" and "Fanout" are structure. Counting them would
        inflate every release by its own shape."""
        names = {c["name"] for c in self.walk()["cases"]}
        self.assertNotIn("ServerSetup", names)
        self.assertNotIn("Fanout", names)

    def test_a_nesting_wrapper_is_structure_not_a_case(self):
        """ServerNestedTestCase with children is the shape of the suite. It
        appears in failure logs because a nest fails when a leaf under it
        does, but counting it would inflate every release by its own shape."""
        names = {c["name"] for c in self.walk()["cases"]}
        self.assertNotIn("ServerNestedTestCase", names)
        self.assertNotIn("SltModuleNestedTestCase", names)

    def test_a_wrapper_with_no_children_is_flagged_not_counted(self):
        """The real suites do this: the sub-suite is an alias defined
        elsewhere, so the wrapper reads as a leaf. It must not be counted as a
        test case, and the caller filters on the flag."""
        text = SUITE + """
  - name: Aliased
    tests:
      - name: ServerNestedTestCase
"""
        cases = {c["name"]: c for c in self.walk(text)["cases"]}
        self.assertTrue(cases["ServerNestedTestCase"]["wrapper"])
        self.assertFalse(cases["SohuDmaTestCase"]["wrapper"])

    def test_the_suite_name_comes_through(self):
        self.assertEqual(self.walk()["suiteName"], "chip_screening_parallel")

    def test_the_scanner_fallback_finds_the_same_cases(self):
        """Where PyYAML is absent the file is scanned instead; it must not
        quietly find a different set."""
        scanned = {c["name"] for c in brs._scan(SUITE)["cases"]}      # noqa: SLF001
        self.assertIn("SohuPowerVirusTestCase", scanned)
        self.assertIn("PcieSetupTestCase", scanned)


class CommitTest(unittest.TestCase):
    def test_a_suite_name_yields_its_commit(self):
        found = brs.COMMIT.search("mlt_2026.220.0-git2f1c2f23")
        self.assertEqual(found.group(1), "2f1c2f23")

    def test_a_validation_suite_yields_the_same_commit(self):
        found = brs.COMMIT.search("mlt_validation_2026.225.0-gitb937ca2c")
        self.assertEqual(found.group(1), "b937ca2c")

    def test_a_name_without_a_commit_is_not_profiled(self):
        self.assertIsNone(brs.COMMIT.search("L10_FAT"))


class DiffTest(unittest.TestCase):
    def rel(self, suite, cases, day, station="mlt"):
        return {"station": station, "suite": suite, "cases": cases,
                "caseCount": len(cases), "committedAt": day}

    def test_a_dropped_case_is_reported(self):
        diffs = brs._diffs([                                # noqa: SLF001
            self.rel("mlt_2026.220.0-gita", ["A", "B"], "2026-08-08"),
            self.rel("mlt_2026.225.0-gitb", ["A"], "2026-08-14"),
        ])
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["dropped"], ["B"])
        self.assertEqual(diffs[0]["added"], [])
        self.assertEqual(diffs[0]["unchanged"], 1)

    def test_an_identical_release_produces_no_diff(self):
        """A validation build and its production twin share a commit and so
        share a case list; reporting an empty change would be noise."""
        diffs = brs._diffs([                                # noqa: SLF001
            self.rel("mlt_2026.225.0-gitb", ["A"], "2026-08-14"),
            self.rel("mlt_validation_2026.225.0-gitb", ["A"], "2026-08-14"),
        ])
        self.assertEqual(diffs, [])

    def test_ordering_is_by_commit_date_not_release_number(self):
        """226 can be cut before 225 reaches the floor."""
        diffs = brs._diffs([                                # noqa: SLF001
            self.rel("mlt_2026.226.0-gitc", ["A", "C"], "2026-08-10"),
            self.rel("mlt_2026.225.0-gitb", ["A"], "2026-08-14"),
        ])
        self.assertEqual(diffs[0]["from"], "mlt_2026.226.0-gitc")

    def test_stations_do_not_diff_against_each_other(self):
        diffs = brs._diffs([                                # noqa: SLF001
            self.rel("mlt_2026.220.0-gita", ["A"], "2026-08-08"),
            self.rel("htt_2026.217.0-gitx", ["Z"], "2026-08-09", station="htt"),
        ])
        self.assertEqual(diffs, [])


class RepoTest(unittest.TestCase):
    def test_a_missing_clone_says_what_to_do(self):
        """The dashboard host will never have one, so this is the normal
        outcome there and must not read as a failure."""
        with self.assertRaises(brs.RepoUnavailable) as caught:
            brs.repo_path("/nonexistent/sw")
        self.assertIn("FACTORY_SW_REPO", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
