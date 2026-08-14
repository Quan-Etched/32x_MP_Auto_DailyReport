"""Measuring the gap between the two station pages.

This exists to be pointed at when a number is challenged, so what matters is
that it cannot quietly overstate agreement: a station only one source has must
show up, and a rate nobody measured must not read as zero.
"""

import unittest

from factory import compare


def bundle(stations, views, source):
    return {"stations": stations, "views": views, "generatedAt": "2026-08-14T17:00:00+00:00",
            "dataSource": source}


EOS = bundle(
    [{"key": "__all__", "label": "All stations"},
     {"key": "mlt", "label": "MLT"},
     {"key": "slt", "label": "SLT"},
     {"key": "l11_test", "label": "L11 Test"},
     {"key": "engineering", "label": "Engineering"}],
    {"__all__": {"summary": {"runs": 100, "passRate": 0.40},
                 "units": {"yield": 0.57}},
     "mlt": {"summary": {"runs": 20, "passRate": 0.30}},
     "slt": {"summary": {"runs": 30, "passRate": 0.61}},
     "l11_test": {"summary": {"runs": 0, "passRate": None}},
     "engineering": {"summary": {"runs": 9, "passRate": 0.1}}},
    {"label": "OCP Logs"})

PEGA = bundle(
    [{"key": "__all__", "label": "All stations"},
     {"key": "mlt", "label": "MLT"},
     {"key": "slt", "label": "SLT"},
     {"key": "l11_test", "label": "L11 Test"}],
    {"__all__": {"summary": {"runs": 160, "passRate": 0.49}},
     "mlt": {"summary": {"runs": 160, "passRate": 0.51}},
     "slt": {"summary": {"runs": 0, "passRate": None}},
     "l11_test": {"summary": {"runs": 24, "passRate": 0.04}}},
    {"label": "pega2 - pega5"})


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.result = compare.build(EOS, PEGA)
        self.rows = {row["key"]: row for row in self.result["rows"]}

    def test_both_sides_of_each_station_are_reported(self):
        mlt = self.rows["mlt"]
        self.assertEqual((mlt["eosRuns"], mlt["pegaRuns"]), (20, 160))
        self.assertEqual((mlt["eosRate"], mlt["pegaRate"]), (0.30, 0.51))

    def test_the_expansion_factor_explains_the_difference_in_one_number(self):
        # 160 unit records for 20 fixture runs: eight slots, near enough.
        self.assertEqual(self.rows["mlt"]["expansion"], 8.0)

    def test_a_station_only_one_source_has_is_still_listed(self):
        # These rows are the point of the table as much as the differing rates:
        # each page is missing something, and hiding that would be the exact
        # overstatement this section exists to prevent.
        self.assertEqual(self.rows["slt"]["pegaRuns"], 0)
        self.assertEqual(self.rows["l11_test"]["eosRuns"], 0)

    def test_an_unmeasured_rate_is_none_not_zero(self):
        # 0% is a claim about a station that ran; None means nobody measured it.
        self.assertIsNone(self.rows["slt"]["pegaRate"])
        self.assertIsNone(self.rows["l11_test"]["eosRate"])

    def test_no_expansion_is_reported_when_one_side_is_empty(self):
        # A ratio against zero is not information.
        self.assertIsNone(self.rows["slt"]["expansion"])
        self.assertIsNone(self.rows["l11_test"]["expansion"])

    def test_engineering_and_unclassified_are_left_out(self):
        # Neither is a line stage, and neither page counts them in yield.
        self.assertNotIn("engineering", self.rows)
        self.assertNotIn("unclassified", self.rows)

    def test_the_derived_unit_yield_is_carried_for_cross_checking(self):
        # The EOS page derives a unit-level figure from chip names; the direct
        # page measures one. Agreement between them is the check that both
        # describe the same thing, so the section quotes it.
        self.assertEqual(self.result["totals"]["eosUnitYield"], 0.57)

    def test_totals_come_from_the_all_stations_view(self):
        totals = self.result["totals"]
        self.assertEqual((totals["eosRuns"], totals["pegaRuns"]), (100, 160))

    def test_a_station_missing_from_one_registry_still_appears(self):
        thin = bundle([{"key": "__all__", "label": "All"}],
                      {"__all__": {"summary": {"runs": 1, "passRate": 1.0}}}, {})
        rows = {r["key"] for r in compare.build(thin, PEGA)["rows"]}
        self.assertIn("mlt", rows)

    def test_both_source_labels_are_carried(self):
        self.assertEqual(self.result["sources"]["eos"]["label"], "OCP Logs")
        self.assertEqual(self.result["sources"]["pega"]["label"], "pega2 - pega5")


if __name__ == "__main__":
    unittest.main()
