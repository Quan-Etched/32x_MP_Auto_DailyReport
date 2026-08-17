"""Retests, split from new builds.

The daily tracker keeps one row per unit with the latest attempt winning, so a
unit that failed in the morning and passed in the afternoon is one pass there.
That is right for "what is the state of the line" and wrong for "how did the
fresh units do" — and averaging the two populations describes neither. These
tests pin the split and the first/last pairing the page is built on.
"""

import unittest

from factory import build_retest


def attempt(status, day, started, suite="mlt_2026.220.0-gitabc", failures=""):
    return {"day": day, "started": started, "status": status, "suite": suite,
            "failures": failures, "url": "http://pega3:3000/x", "short": "abc"}


def collected(units, days=("2026-08-11", "2026-08-17")):
    return {"window": list(days), "attempts": units, "parts": {},
            "runs": sum(len(v) for u in units.values() for v in u.values())}


class SplitTest(unittest.TestCase):
    def split(self, units):
        return build_retest.build_bundle(collected(units))["split"]

    def test_first_pass_counts_the_first_attempt_not_the_best(self):
        """The unit passed in the end; it did not pass first time, and a
        first-pass yield that says otherwise is the whole problem."""
        units = {"A": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("pass", "2026-08-12", "T2")]}}
        mlt = self.split(units)["mlt"]
        self.assertEqual(mlt["units"], 1)
        self.assertEqual(mlt["firstPass"], 0)
        self.assertEqual(mlt["firstPassRate"], 0.0)

    def test_retested_and_recovered_are_different_numbers(self):
        units = {
            "A": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                          attempt("pass", "2026-08-12", "T2")]},   # recovered
            "B": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                          attempt("fail", "2026-08-12", "T2")]},   # still bad
            "C": {"mlt": [attempt("pass", "2026-08-11", "T1")]},   # fine first go
        }
        mlt = self.split(units)["mlt"]
        self.assertEqual((mlt["units"], mlt["retested"]), (3, 2))
        self.assertEqual(mlt["recovered"], 1)
        self.assertEqual(mlt["retestPassed"], 1)
        self.assertAlmostEqual(mlt["retestRate"], 2 / 3)

    def test_a_unit_that_passed_twice_is_retested_but_not_recovered(self):
        """Re-running a passing unit is capacity spent; calling it a recovery
        would credit the retest with a save it did not make."""
        units = {"A": {"mlt": [attempt("pass", "2026-08-11", "T1"),
                               attempt("pass", "2026-08-12", "T2")]}}
        mlt = self.split(units)["mlt"]
        self.assertEqual(mlt["retested"], 1)
        self.assertEqual(mlt["recovered"], 0)

    def test_stations_are_counted_separately(self):
        units = {"A": {"mlt": [attempt("pass", "2026-08-11", "T1")],
                       "htt": [attempt("fail", "2026-08-11", "T2"),
                               attempt("pass", "2026-08-12", "T3")]}}
        split = self.split(units)
        self.assertEqual(split["mlt"]["retested"], 0)
        self.assertEqual(split["htt"]["retested"], 1)

    def test_ungraded_attempts_do_not_make_a_retest(self):
        units = {"A": {"mlt": [attempt("pass", "2026-08-11", "T1"),
                               attempt("skip", "2026-08-12", "T2")]}}
        self.assertEqual(self.split(units)["mlt"]["retested"], 0)


class RowTest(unittest.TestCase):
    def rows(self, units):
        return build_retest.build_bundle(collected(units))["rows"]

    def test_only_units_that_came_back_are_listed(self):
        units = {"A": {"mlt": [attempt("pass", "2026-08-11", "T1")]},
                 "B": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("pass", "2026-08-12", "T2")]}}
        self.assertEqual([r["dut"] for r in self.rows(units)], ["B"])

    def test_the_row_pairs_the_first_attempt_with_the_last(self):
        """The workbook's Retest tab puts the original on the left and the
        retest on the right; a middle attempt belongs to neither column."""
        units = {"B": {"mlt": [attempt("fail", "2026-08-11", "T1", failures="X"),
                               attempt("fail", "2026-08-12", "T2", failures="Y"),
                               attempt("pass", "2026-08-13", "T3")]}}
        row = self.rows(units)[0]["attempts"]["mlt"]
        self.assertEqual(row["count"], 3)
        self.assertEqual(row["first"]["failures"], "X")
        self.assertEqual(row["last"]["status"], "pass")
        self.assertTrue(row["recovered"])
        self.assertFalse(row["stillFailing"])

    def test_a_station_run_once_is_not_given_a_retest_column(self):
        """A unit re-run three times at HTT must not appear to have been
        re-run at MLT."""
        units = {"B": {"mlt": [attempt("pass", "2026-08-11", "T1")],
                       "htt": [attempt("fail", "2026-08-11", "T2"),
                               attempt("fail", "2026-08-12", "T3")]}}
        row = self.rows(units)[0]
        self.assertEqual(row["retested"], ["htt"])
        self.assertEqual(row["attempts"]["mlt"]["count"], 1)

    def test_rows_are_dated_by_the_first_attempt(self):
        units = {"B": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("pass", "2026-08-14", "T2")]}}
        self.assertEqual(self.rows(units)[0]["day"], "2026-08-11")


if __name__ == "__main__":
    unittest.main()
