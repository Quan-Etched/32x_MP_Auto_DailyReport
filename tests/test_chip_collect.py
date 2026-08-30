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
