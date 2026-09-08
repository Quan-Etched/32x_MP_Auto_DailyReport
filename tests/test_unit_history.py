"""dashboard/data/unit_history.js: a board's attempts from before the window.

Chris asked on 2026-09-07 for the re-test history to reach a board's first
test. The daily tracker's answer landed the next day; the serial search on
customize.html reads the runs bundle, which starts at the line's reporting
horizon, so 268086800000021 still showed two runs both dated 09-07 with four
July attempts missing.

What this pins is the join. The file must stop exactly where the runs bundle
starts — one attempt on either side of that line and the page has either a
duplicate row or a hole — and it must name stations the way the runs bundle
names them, or one board's history renders as two different stages.
"""

import json
import unittest
from datetime import datetime, timezone

from factory import build_dailyexcel, build_unit_history, pega


def listing(day, run_id, suite, host):
    return [{"suite_run_id": run_id, "suite_name": suite,
             "start_time": day + "T09:00:00Z"}]


class UnitHistoryTest(unittest.TestCase):
    """One MLT board, two July attempts and one in August."""

    DUT = "268086800000021"
    JULY = {"2026-07-24": ("mlt_2026.205.0-gitaca812f4_run_80db8ef7", "failed"),
            "2026-07-28": ("mlt_2026.205.0-gitaca812f4_run_a7c5f1f8", "passed")}
    AUGUST = {"2026-08-04": ("mlt_2026.231.0-gitabc_run_ccc", "passed")}

    def setUp(self):
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, pega, "suite_run", pega.suite_run)
        self.addCleanup(build_dailyexcel.forget_spans)
        build_dailyexcel.forget_spans()

        runs = dict(self.JULY)
        runs.update(self.AUGUST)
        self.runs = runs

        def day_listing(day, host=None):
            if host != "pega3" or day not in runs:
                return []
            run_id, _status = runs[day]
            return listing(day, run_id, run_id.split("_run_")[0], host)

        def detail(run_id, host=None):
            status = next(s for r, s in runs.values() if r == run_id)
            return {"status": status, "test_cases": [],
                    "participating": [{"dut_sn": self.DUT, "slot_number": 3,
                                       "status": "Passed" if status == "passed"
                                                 else "Failed"}]}

        pega.day_suite_runs = day_listing
        pega.suite_run = detail

    def bundle(self):
        return build_unit_history.build_bundle(
            history_from="2026-05-21", window_from="2026-08-01")

    def rows(self):
        return self.bundle()["units"][self.DUT]["mlt"]

    def test_the_july_attempts_are_carried(self):
        self.assertEqual([row[0] for row in self.rows()],
                         ["2026-07-24", "2026-07-28"])
        self.assertEqual([row[2] for row in self.rows()], ["fail", "pass"])

    def test_the_august_attempt_is_not(self):
        """The runs bundle owns it, with its duration and its per-test detail.
        A second, thinner copy here is a row the page would have to choose
        between — so this file stops the day that one starts."""
        for row in self.rows():
            self.assertLess(row[0], "2026-08-01")

    def test_a_row_carries_the_clock_and_the_link(self):
        """Day alone would not sort against the runs bundle, whose rows have a
        timestamp; and a history row with no way through to the run is a claim
        the reader cannot check."""
        first = self.rows()[0]
        self.assertEqual(
            first[1],
            int(datetime(2026, 7, 24, 9, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(first[3], self.JULY["2026-07-24"][0])
        self.assertEqual(first[4], 3, "the slot, so the link opens on the unit")
        self.assertEqual(first[5], "mlt_2026.205.0-gitaca812f4")

    def test_the_join_is_stated_rather_than_implied(self):
        got = self.bundle()
        self.assertEqual(got["window"]["from"], "2026-08-01")
        self.assertEqual(got["historyFrom"], "2026-05-21")
        self.assertEqual(got["counts"], {"units": 1, "attempts": 2})

    def test_the_station_is_named_the_way_the_runs_bundle_names_it(self):
        """`mlt` here and `mlt` there. The L10 and L11 cases are the ones that
        bite — see StationKeyTest."""
        self.assertEqual(list(self.bundle()["units"][self.DUT]), ["mlt"])
        self.assertEqual(self.bundle()["controllers"]["mlt"], "pega3")

    def test_a_july_suite_with_no_release_stamp_still_counts(self):
        """July's HTT runs were named htt_20260724, not htt_2026.205.0-git….

        Worth a test because the obvious implementation loses them: asking
        `pega_collect.station_of` to classify the suite string misses that
        spelling, returns nothing, and drops every July HTT attempt — the exact
        history this file exists to carry. The station comes from the index,
        which has already decided.
        """
        self.runs.clear()
        self.runs["2026-07-28"] = ("htt_20260724_run_ef7ddc2f", "passed")
        build_dailyexcel.forget_spans()
        got = self.bundle()["units"][self.DUT]
        self.assertEqual(list(got), ["htt"])
        self.assertEqual(got["htt"][0][5], "htt_20260724")

    def test_the_bundle_is_a_loadable_page_script(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = build_unit_history.write_bundle(
                self.bundle(), Path(tmp) / "unit_history.js")
            text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("window.__FACTORY_UNIT_HISTORY__ = {"))
        body = json.loads(text[text.index("{"):text.rindex("}") + 1])
        self.assertIn(self.DUT, body["units"])


class StationKeyTest(unittest.TestCase):
    """Stage keys and station keys, which are not the same strings.

    build_l10 keys its index by stage — "fat" — and the runs bundle keys by
    station — "l10_fat". Translate with the wrong table and a chassis's July
    FAT attempt renders as a different stage from its August one: one unit, two
    histories, nothing saying they are the same board.
    """

    def test_l10_and_l11_stages_become_station_keys(self):
        self.assertEqual(build_unit_history.station_key("pega4", "fat"),
                         "l10_fat")
        self.assertEqual(build_unit_history.station_key("pega5", "provision"),
                         "l11_provision")

    def test_the_module_keys_pass_straight_through(self):
        self.assertEqual(build_unit_history.station_key("pega3", "mlt"), "mlt")
        self.assertEqual(build_unit_history.station_key("pega3", "htt"), "htt")

    def test_it_is_the_collector_s_own_table(self):
        """Not a copy of it. Two tables would drift, and the drift is silent."""
        from factory import pega_collect
        self.assertEqual(
            pega_collect.STAGE_STATIONS["pega4"]["sft"],
            build_unit_history.station_key("pega4", "sft"))
        self.assertEqual(pega_collect.station_of("pega4", "L10_FAT"), "l10_fat")


if __name__ == "__main__":
    unittest.main()
