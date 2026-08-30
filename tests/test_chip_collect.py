"""Wafer sort and final test: the two mistakes worth guarding.

The first is a mis-read column. FT's verdict is the soft bin; ``ft_status`` is
the HBM repair state — Clean / Repairable / Non-repairable. Reading the latter
as the verdict gave 0% pass over 318 dies, which is how it announced itself, but
a subtler mapping error would not have.

The second is the one that matters. These CSVs are somebody's analysis subsets:
the right dies for the question that person was asking, and the wrong dies for
"what is the line yielding". A subset is not a smaller version of the whole. The
module must refuse to present them as the published yield, and refuse for a
reason it can show.
"""

import json
import unittest

from factory import chip_collect


def die(**kw):
    row = {"wafer": "U8G375-W06", "lot": "U8G375", "wafer_num": "06",
           "x": "1", "y": "2", "hard_bin": "1", "soft_bin": "1",
           "pass_fail": "PASS", "failing_blocks": ""}
    row.update(kw)
    return row


def ft_row(**kw):
    row = {"die": "U8G386_W01_X6_Y6", "lot": "U8G386",
           "serial": "JE60703103202602090204", "ft_sbin": "1",
           "ft_sbin_name": "PASS", "ft_status": "Clean",
           "ft_insertions": "1", "slt_verdict_type": "PASS"}
    row.update(kw)
    return row


class VerdictTest(unittest.TestCase):
    """The soft bin is the verdict, not the repair state."""

    def summarise(self, rows, station="ft"):
        # Through the module's own mapping, not a copy of it. The first version
        # of this helper re-implemented ft_die() and so verified itself: a
        # module that marked every die as passing still passed the test.
        made = [d for d in (chip_collect.ft_die(r) for r in rows)
                if d is not None]
        return chip_collect.summarise({
            "station": station, "source": "test", "sourceKind": "snapshot",
            "hasClock": False, "dies": made})

    def test_bin_one_is_the_clean_pass(self):
        got = self.summarise([ft_row(), ft_row(ft_sbin="12",
                                              ft_sbin_name="SA_FUNC")])
        self.assertEqual(0.5, got["yield"])

    def test_a_repair_state_of_clean_is_not_a_pass_by_itself(self):
        """ft_status="Clean" with a failing bin is a die that failed for a
        reason unrelated to HBM. Reading the repair state as the verdict is what
        produced 0% over 318 dies."""
        got = self.summarise([ft_row(ft_sbin="12", ft_sbin_name="SA_FUNC",
                                     ft_status="Clean")])
        self.assertEqual(0.0, got["yield"])

    def test_repairs_are_counted_apart_from_the_yield(self):
        """Whether a repaired die is FT output is the owner's call, so the
        module reports both numbers and decides neither."""
        got = self.summarise([ft_row(),
                              ft_row(ft_sbin="13", ft_sbin_name="HBM_REP")])
        self.assertEqual(0.5, got["yield"], "repairs stay out of yield")
        self.assertEqual(1, got["repaired"])
        self.assertEqual(1.0, got["yieldWithRepairs"])

    def test_the_bin_pareto_is_ranked(self):
        got = self.summarise([ft_row(ft_sbin="12", ft_sbin_name="SA_FUNC"),
                              ft_row(ft_sbin="12", ft_sbin_name="SA_FUNC"),
                              ft_row()])
        self.assertEqual(["SA_FUNC", "PASS"],
                         [b["bin"] for b in got["bins"]])


class PopulationTest(unittest.TestCase):
    """A subset must not be published as the whole."""

    def judged(self, ours, theirs, dies=100, lots=("U8G999",)):
        computed = {"yield": ours, "dies": dies, "lots": list(lots)}
        chip_collect._judge("wst", computed,                  # noqa: SLF001
                            {"wst": {"yield": theirs, "asOf": "2026-08-21"}})
        return computed

    def test_a_figure_far_from_the_reported_one_is_refused(self):
        got = self.judged(0.411, 0.325)
        self.assertFalse(got["publishable"])
        self.assertIn("9 points apart", got["whyNotPublishable"])
        self.assertIn("U8G999", got["whyNotPublishable"],
                      "the reason must name the population it measured")

    def test_a_figure_close_to_the_reported_one_is_allowed(self):
        self.assertTrue(self.judged(0.330, 0.325)["publishable"])

    def test_nothing_to_compare_against_is_not_publishable(self):
        got = self.judged(0.411, None)
        self.assertFalse(got["publishable"])
        self.assertIn("nothing to compare", got["whyNotPublishable"])

    def test_the_gap_is_recorded_so_the_verdict_can_be_checked(self):
        self.assertAlmostEqual(0.086, self.judged(0.411, 0.325)["gapToReported"],
                               places=3)


class SivalTest(unittest.TestCase):
    """SiVal is the system built for this, so reading it correctly matters.

    sival/ is a Flask + Postgres dashboard for wafer sort, final test and SLT —
    the answer to "is there already a backend counting this" is yes. Its
    lot_phase_stats carries per-phase die counts and its session_test_result
    carries start_ts, which is everything daily and hourly need.
    """

    def setUp(self):
        self.calls = []
        self._real = chip_collect.sival
        chip_collect.sival = self.fake

    def tearDown(self):
        chip_collect.sival = self._real

    def fake(self, path):
        self.calls.append(path)
        if "project_yield_stats" in path:
            return self.stats
        if "lot_trend" in path:
            return self.lots
        return []

    def test_a_phase_that_tested_nothing_is_untested_not_zero(self):
        """The bug this pins shipped for one run of the collector.

        test_phase_breakdown divides by `total_dies` — every die in the lot,
        touched by that phase or not — so FinalTest came out as "0.0% over
        19863 dies" when it had tested none of them. 0% and "not measured" are
        opposite claims about a station and the first one was on its way to a
        page.
        """
        self.stats = {"wafersort_tested": 100, "wafersort_passed": 40,
                      "finaltest_tested": 0, "finaltest_passed": 0,
                      "slt_tested": 0, "slt_passed": 0}
        self.lots = []
        got = chip_collect.sival_stations()
        self.assertEqual(0.4, got["wst"]["yield"])
        self.assertIsNone(got["ft"]["yield"], "0/0 is unknown, not zero")
        self.assertEqual(0, got["ft"]["dies"])
        self.assertIn("tested no dies", got["ft"]["note"])

    def test_the_phase_names_map_to_our_station_keys(self):
        """SiVal speaks STDF — Wafersort / FinalTest / SLT."""
        self.assertEqual({"Wafersort": "wst", "FinalTest": "ft", "SLT": "slt"},
                         chip_collect.SIVAL_PHASE)

    def test_per_lot_rows_come_through(self):
        self.stats = {"wafersort_tested": 100, "wafersort_passed": 40}
        self.lots = [{"lot_name": "U8G384", "ws_tested": 60, "ws_passed": 30,
                      "ft_tested": 0, "ft_passed": 0}]
        got = chip_collect.sival_stations()
        self.assertEqual([{"wafer": "U8G384", "dies": 60, "passed": 30,
                           "yield": 0.5}], got["wst"]["byWafer"])
        self.assertEqual(["U8G384"], got["wst"]["lots"])

    def test_a_database_source_says_it_has_a_clock(self):
        """Unlike the CSVs: session_test_result has start_ts, so daily and
        hourly are available from this source once it is reachable."""
        self.stats = {"wafersort_tested": 10, "wafersort_passed": 5}
        self.lots = []
        got = chip_collect.sival_stations()
        self.assertTrue(got["wst"]["hasClock"])
        self.assertEqual("database", got["wst"]["sourceKind"])

    def test_the_daily_endpoint_is_reported_unusable_with_the_reason(self):
        """yield_trend proves the clock exists and cannot be used as-is: it
        formats 'Mon DD' with no year and pools every session_type. Saying so
        beats parsing 'Jan 28' and guessing a year."""
        chip_collect.sival = lambda path: [{"test_date": "Jan 28",
                                            "total_tests": 103,
                                            "passed_tests": 0}]
        got = chip_collect.sival_daily()
        self.assertFalse(got["available"])
        self.assertIn("no year", got["why"])
        self.assertIn("session_type", got["why"])


class ProvenanceTest(unittest.TestCase):
    """What the bundle has to say about itself."""

    def test_a_source_with_no_dates_says_it_has_no_clock(self):
        """Otherwise somebody draws it on a daily axis and every day gets the
        same number — a measurement per day that nobody made."""
        got = chip_collect.summarise({
            "station": "wst", "source": "test", "sourceKind": "snapshot",
            "hasClock": False, "dies": [
                {"pass": True, "wafer": "W1", "lot": "L"},
                {"pass": False, "wafer": "W1", "lot": "L"}]})
        self.assertFalse(got["hasClock"])
        self.assertEqual("snapshot", got["sourceKind"])
        self.assertEqual(0.5, got["yield"])

    def test_per_wafer_is_broken_out(self):
        """A lot-wide percentage hides a bad wafer inside a good lot."""
        got = chip_collect.summarise({
            "station": "wst", "source": "test", "sourceKind": "snapshot",
            "hasClock": False, "dies": [
                {"pass": True, "wafer": "W1", "lot": "L"},
                {"pass": False, "wafer": "W2", "lot": "L"}]})
        self.assertEqual([{"wafer": "W1", "dies": 1, "passed": 1, "yield": 1.0},
                          {"wafer": "W2", "dies": 1, "passed": 0, "yield": 0.0}],
                         got["byWafer"])

    def test_the_blockers_are_named_in_the_bundle(self):
        """A reader asking why these two stations have no daily buckets should
        find the answer in the data, not in a commit message.

        Asserted against collect()'s source rather than by calling it, so the
        test does not need the factory network to check that the vocabulary is
        still there."""
        import inspect
        source = inspect.getsource(chip_collect.collect)
        for blocker in ("eos", "bringup", "clock", "splm"):
            with self.subTest(blocker=blocker):
                self.assertIn('"{}"'.format(blocker), source)


if __name__ == "__main__":
    unittest.main()


class PassRuleTest(unittest.TestCase):
    """Why SiVal's number is 28 points below the reported one.

    Traced on U8G590 wafer 1: 62 dies, exactly 2 with wafer_sort_complete true,
    exactly 2 with zero failing functional tests, and ws_pass = 2. So SiVal's
    passed_dies means "every one of ~3940 tests passed". On U8G621 no die
    clears that — each has 3 to 38 failures — so the lot reads 0 of 1426.

    Wafer sort yield is the bin-1 rate, and binning tolerates non-gating
    failures. The gap is a definition, not missing data, and this test exists so
    nobody closes it by relabelling SiVal's count as a yield.
    """

    def setUp(self):
        self._real = chip_collect.sival
        chip_collect.sival = lambda path: (
            [{"lot_id": 1, "lot_name": "U8G621", "ws_tested": 1426,
              "ws_passed": 0},
             {"lot_id": 2, "lot_name": "U8G590", "ws_tested": 1178,
              "ws_passed": 48}]
            if "lot_trend" in path else {})

    def tearDown(self):
        chip_collect.sival = self._real

    def test_the_count_is_named_clean_sweep_not_yield(self):
        got = chip_collect.sival_activity()
        for row in got:
            with self.subTest(lot=row["lot"]):
                self.assertIn("cleanSweepDies", row)
                self.assertNotIn("yield", row,
                                 "calling this a yield is the error the whole "
                                 "docstring is about")
                self.assertIn("not the bin", row["passRule"])

    def test_lots_and_die_counts_come_through(self):
        """The part that is correct today: which lots ran and how big they are.
        This is what Helen answered by hand."""
        got = {row["lot"]: row["diesTested"] for row
               in chip_collect.sival_activity()}
        self.assertEqual({"U8G621": 1426, "U8G590": 1178}, got)

    def test_lots_with_nothing_tested_are_left_out(self):
        chip_collect.sival = lambda path: (
            [{"lot_id": 9, "lot_name": "TSMC Internal", "ws_tested": 0,
              "ws_passed": 0}] if "lot_trend" in path else {})
        self.assertEqual([], chip_collect.sival_activity())

    def test_the_gap_is_explained_in_the_blockers(self):
        """A reader seeing 4.84% next to 32.5% should find the reason in the
        bundle, not have to re-derive it."""
        import inspect
        source = inspect.getsource(chip_collect.collect)
        self.assertIn("sivalPassRule", source)
        self.assertIn("bin", source)
