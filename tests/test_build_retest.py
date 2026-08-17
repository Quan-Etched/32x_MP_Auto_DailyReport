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

    def test_a_trace_keeps_every_attempt_not_just_the_ends(self):
        """First-and-last was the workbook's shape and it cannot show four
        attempts across three builds — which is most of this page. The middle
        attempt is where the build changed."""
        units = {"B": {"mlt": [attempt("fail", "2026-08-11", "T1", failures="X"),
                               attempt("fail", "2026-08-12", "T2",
                                       suite="mlt_2026.225.0-gitx", failures="Y"),
                               attempt("pass", "2026-08-13", "T3",
                                       suite="mlt_2026.225.0-gitx")]}}
        row = self.rows(units)[0]
        self.assertEqual(row["count"], 3)
        self.assertEqual([a["status"] for a in row["attempts"]],
                         ["fail", "fail", "pass"])
        self.assertTrue(row["recovered"])
        self.assertTrue(row["crossedBuild"])
        self.assertEqual(len(row["builds"]), 2)

    def test_one_row_per_unit_per_station(self):
        """A unit re-run three times at HTT must not appear to have been
        re-run at MLT."""
        units = {"B": {"mlt": [attempt("pass", "2026-08-11", "T1")],
                       "htt": [attempt("fail", "2026-08-11", "T2"),
                               attempt("fail", "2026-08-12", "T3")]}}
        rows = self.rows(units)
        self.assertEqual([r["station"] for r in rows], ["htt"])
        self.assertEqual(rows[0]["count"], 2)

    def test_a_retest_on_the_same_build_is_marked_as_such(self):
        """Re-run against a different build is a fix being tried; re-run
        against the same one is a flake being chased."""
        units = {"B": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("fail", "2026-08-12", "T2")]}}
        self.assertFalse(self.rows(units)[0]["crossedBuild"])

    def test_rows_are_dated_by_the_first_attempt(self):
        units = {"B": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("pass", "2026-08-14", "T2")]}}
        self.assertEqual(self.rows(units)[0]["day"], "2026-08-11")


if __name__ == "__main__":
    unittest.main()


class DiagramInputTest(unittest.TestCase):
    """What the Sankey is drawn from.

    The diagram is aggregated in the page so it can follow the filter, so what
    is worth pinning here is the per-row material it aggregates: which build
    the unit started on, which it ended on, and how it finished.
    """

    def rows(self, units):
        return build_retest.build_bundle(collected(units))["rows"]

    def test_a_row_names_the_build_it_started_and_ended_on(self):
        units = {"A": {"mlt": [attempt("fail", "2026-08-11", "T1",
                                       suite="mlt_2026.220.0-gitabc"),
                               attempt("pass", "2026-08-12", "T2",
                                       suite="mlt_2026.225.0-gitxyz")]}}
        row = self.rows(units)[0]
        self.assertEqual(row["firstBuildShort"], "220")
        self.assertEqual(row["lastBuildShort"], "225")
        self.assertTrue(row["crossedBuild"])

    def test_the_outcome_is_on_the_row(self):
        cases = [
            (["fail", "pass"], "Recovered"),
            (["fail", "fail"], "Still failing"),
            (["pass", "pass"], "Passed throughout"),
        ]
        for statuses, expected in cases:
            units = {"A": {"mlt": [attempt(s, "2026-08-1%d" % (i + 1),
                                           "T%d" % i)
                                   for i, s in enumerate(statuses)]}}
            with self.subTest(statuses=statuses):
                self.assertEqual(self.rows(units)[0]["outcome"], expected)

    def test_a_trace_is_one_unit_however_many_attempts(self):
        """Three attempts is one unit's journey, not three."""
        units = {"A": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("fail", "2026-08-12", "T2"),
                               attempt("fail", "2026-08-13", "T3")]}}
        self.assertEqual(len(self.rows(units)), 1)


class SelectableLabelTest(unittest.TestCase):
    """Every diagram label has to name a selectable subset.

    The nodes and ribbons are the page's main controls now — clicking "Still
    failing 58" lists those 58. A row missing one of these fields produces a
    node that still counts it and cannot select it, which reads as a control
    that does nothing.
    """

    def rows(self, units):
        return build_retest.build_bundle(collected(units))["rows"]

    def test_every_row_carries_all_three_labels(self):
        units = {
            "A": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                          attempt("pass", "2026-08-12", "T2",
                                  suite="mlt_2026.225.0-gitx")]},
            "B": {"htt": [attempt("fail", "2026-08-11", "T1",
                                  suite="debug_only_htt_2026.223.0-gitq"),
                          attempt("fail", "2026-08-12", "T2",
                                  suite="htt_2026.226.0-gitz")]},
        }
        for row in self.rows(units):
            for field in ("firstBuildShort", "lastBuildShort", "outcome",
                          "stationLabel"):
                with self.subTest(dut=row["dut"], field=field):
                    self.assertTrue(row[field], field)

    def test_a_suite_with_no_release_number_still_labels(self):
        """An unparseable name must not become an empty node."""
        units = {"A": {"mlt": [attempt("fail", "2026-08-11", "T1",
                                       suite="mlt_experiment"),
                               attempt("fail", "2026-08-12", "T2",
                                       suite="mlt_experiment")]}}
        row = self.rows(units)[0]
        self.assertEqual(row["firstBuildShort"], "mlt_experiment")

    def test_the_three_outcomes_are_a_closed_set(self):
        """The page colours them by name; a fourth would render uncoloured."""
        units = {
            "A": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                          attempt("pass", "2026-08-12", "T2")]},
            "B": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                          attempt("fail", "2026-08-12", "T2")]},
            "C": {"mlt": [attempt("pass", "2026-08-11", "T1"),
                          attempt("pass", "2026-08-12", "T2")]},
        }
        seen = {row["outcome"] for row in self.rows(units)}
        self.assertEqual(seen, {"Recovered", "Still failing",
                                "Passed throughout"})


class BuildLabelTest(unittest.TestCase):
    def test_a_release_reduces_to_its_number(self):
        self.assertEqual(build_retest.short_build("mlt_2026.220.0-git2f1c2f23"),
                         "220")

    def test_a_validation_build_says_so(self):
        """Nine characters of commit hash on a diagram node say nothing; that
        it is a validation build is the whole distinction."""
        self.assertEqual(
            build_retest.short_build("mlt_validation_2026.225.0-gitb937ca2c"),
            "225 validation")

    def test_a_debug_bundle_says_so(self):
        self.assertEqual(
            build_retest.short_build("debug_only_htt_2026.223.0-git78e6956e2"),
            "223 debug")
