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


class SankeyTest(unittest.TestCase):
    """Where a re-run unit went, build to build.

    The question behind every "did 225 fix it": when the same unit comes back,
    which build does it come back on, and does changing the build change the
    outcome. A table cannot answer that without the reader adding up rows.
    """

    def sankey(self, units):
        return build_retest.build_bundle(collected(units))["sankey"]

    def test_a_unit_re_run_on_a_newer_build_crosses_between_nodes(self):
        units = {"A": {"mlt": [attempt("fail", "2026-08-11", "T1",
                                       suite="mlt_2026.220.0-gitabc"),
                               attempt("pass", "2026-08-12", "T2",
                                       suite="mlt_2026.225.0-gitxyz")]}}
        s = self.sankey(units)
        labels = {n["id"]: n["label"] for n in s["nodes"]}
        crossing = [l for l in s["links"] if labels[l["source"]] != labels[l["target"]]
                    and "Recovered" not in labels[l["target"]]]
        self.assertEqual(len(crossing), 1)
        self.assertEqual(labels[crossing[0]["source"]], "MLT 220")
        self.assertEqual(labels[crossing[0]["target"]], "MLT 225")

    def test_the_outcome_is_the_last_stage(self):
        units = {"A": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("pass", "2026-08-12", "T2")]}}
        s = self.sankey(units)
        ends = [n["label"] for n in s["nodes"] if n["stage"] == 2]
        self.assertEqual(ends, ["Recovered"])

    def test_units_are_counted_not_runs(self):
        """Three attempts is one unit's journey, not three."""
        units = {"A": {"mlt": [attempt("fail", "2026-08-11", "T1"),
                               attempt("fail", "2026-08-12", "T2"),
                               attempt("fail", "2026-08-13", "T3")]}}
        s = self.sankey(units)
        self.assertTrue(all(l["value"] == 1 for l in s["links"]))


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
