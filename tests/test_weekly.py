"""Packing a week out.

The dashboard always shows the current seven days, so on 22 August it will have
replaced the numbers Monday's meeting was run on. These files are the only
thing a later week has to compare against.
"""

import json
import tempfile
import unittest
from pathlib import Path

from factory import weekly

WEEK = {
    "week": "2026-W33",
    "from": "2026-08-10",
    "to": "2026-08-15",
    "endsOn": "2026-08-16",
    "partial": True,
    "hasDetail": True,
    "units": [{"day": "2026-08-10", "station": "mlt",
               "dut": "268494130000067", "release": "mlt_2026.220.0-gitabc",
               "attempt": 1, "status": "fail",
               "failures": ["SohuPowerVirusTestCase"],
               "url": "http://pega3:3000/suite_run/x?slot_number=0",
               "controller": "pega3"}],
    "rows": [
        {"key": "mlt", "label": "MLT", "units": 228, "runs": 279,
         "newUnits": 174, "fpy": 0.655, "finalYield": 0.746,
         "retestRatio": 0.197,
         "topFailures": [{"name": "SohuPowerVirusTestCase", "runs": 140}]},
        {"key": "l10_sft", "label": "L10 SFT", "units": 1, "runs": 6,
         "newUnits": 0, "fpy": None, "finalYield": 0.0, "retestRatio": 1.0,
         "topFailures": []},
    ],
    "external": [
        {"key": "wst", "label": "WST", "yield": 0.353, "asOf": "2026-08-14",
         "source": "Sigurd", "measured": False},
    ],
    "totals": {"rolledFpy": 0.356, "rolledOver": ["MLT"], "minCohort": 20,
               "excludedThin": [{"label": "L10 SFT", "units": 1, "newUnits": 0}],
               "units": 229, "runs": 285, "stations": 2},
}

BUNDLE = {
    "minCohort": 20,
    "excluded": ["vbb_provision"],
    "historyDays": 30,
    "build": {"commit": "abc1234"},
    "source": {"label": "pega2 – pega5 (ESVM)"},
    "generatedAt": "2026-08-16T00:00:00+00:00",
    "weeks": [WEEK],
}


def write_bundle(directory):
    path = Path(directory) / "weekly.js"
    path.write_text("window.__FACTORY_WEEKLY__ = {};\n".format(json.dumps(BUNDLE)),
                    encoding="utf-8")
    return path


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = write_bundle(self.tmp.name)
        self.root = Path(self.tmp.name) / "weekly"

    def test_the_folder_is_named_for_the_iso_week(self):
        """So the folder, the deck and the page's address all say 2026-W33."""
        weekly.archive(bundle=self.bundle, root=self.root)
        self.assertTrue((self.root / "2026-W33").is_dir())

    def test_the_week_is_stored_verbatim(self):
        weekly.archive(bundle=self.bundle, root=self.root)
        stored = json.loads((self.root / "2026-W33" / "week.json").read_text())
        self.assertEqual(stored["totals"]["rolledFpy"], 0.356)
        self.assertEqual(stored["rows"][0]["units"], 228)

    def test_the_context_needed_to_read_it_later_is_stored_too(self):
        """A yield table without its cohort floor or its exclusions cannot be
        interpreted in November."""
        weekly.archive(bundle=self.bundle, root=self.root)
        stored = json.loads((self.root / "2026-W33" / "week.json").read_text())
        self.assertEqual(stored["context"]["minCohort"], 20)
        self.assertEqual(stored["context"]["excluded"], ["vbb_provision"])

    def test_a_missing_bundle_says_what_to_run(self):
        with self.assertRaises(FileNotFoundError) as caught:
            weekly.archive(bundle=Path(self.tmp.name) / "nope.js", root=self.root)
        self.assertIn("make weekly", str(caught.exception))


class SummaryTest(unittest.TestCase):
    def summary(self):
        return weekly.summarise(dict(WEEK, context={
            "minCohort": 20, "excluded": ["vbb_provision"], "historyDays": 30,
            "build": {"commit": "abc1234"},
            "source": {"label": "pega2 – pega5 (ESVM)"}}))

    def test_it_reads_without_the_dashboard(self):
        text = self.summary()
        self.assertIn("2026-08-10 to 2026-08-16", text)
        self.assertIn("65.5%", text)
        self.assertIn("SohuPowerVirusTestCase", text)

    def test_a_reported_figure_is_labelled_as_one(self):
        """The whole point of keeping these: in three months nobody will
        remember which numbers came from a pipeline and which from Slack."""
        self.assertIn("WST *(reported 2026-08-14)*", self.summary())

    def test_the_thin_stages_are_named_with_their_volumes(self):
        text = self.summary()
        self.assertIn("L10 SFT (1 unit)", text)
        self.assertIn("fewer than 20", text)

    def test_the_commit_is_recorded(self):
        self.assertIn("abc1234", self.summary())

    def test_the_exclusion_is_recorded(self):
        """Without it the table looks like the whole flow, and VBB's absence
        reads as VBB having run nothing."""
        self.assertIn("vbb_provision", self.summary())

    def test_retest_is_called_a_rate(self):
        self.assertIn("Retest rate", self.summary())


class PickWeekTest(unittest.TestCase):
    """Which week the snapshot archives when nobody says.

    Load-bearing: the job runs Sunday night Pacific, which is Monday morning
    UTC. At that moment the ISO week has rolled over and "the current week" is
    a fresh empty one — archiving it would store nothing over the week everyone
    is about to discuss.
    """

    def weeks(self):
        return [dict(WEEK, week="2026-W34", partial=True),
                dict(WEEK, week="2026-W33", partial=False),
                dict(WEEK, week="2026-W32", partial=False)]

    def test_the_default_is_the_most_recent_completed_week(self):
        self.assertEqual(weekly.pick_week(self.weeks())["week"], "2026-W33")

    def test_current_takes_the_week_in_progress(self):
        self.assertEqual(
            weekly.pick_week(self.weeks(), current=True)["week"], "2026-W34")

    def test_a_label_wins_over_both(self):
        self.assertEqual(
            weekly.pick_week(self.weeks(), label="2026-W32")["week"], "2026-W32")

    def test_an_unknown_label_is_an_error_not_a_silent_fallback(self):
        with self.assertRaises(FileNotFoundError):
            weekly.pick_week(self.weeks(), label="2026-W01")

    def test_a_first_run_with_nothing_finished_still_archives_something(self):
        only = [dict(WEEK, week="2026-W34", partial=True)]
        self.assertEqual(weekly.pick_week(only)["week"], "2026-W34")


class StandaloneHtmlTest(unittest.TestCase):
    """The archived page has to work with nothing else around it.

    The live page moves on to the next week and eventually drops this one's
    unit rows; this file is the copy that still opens in November.
    """

    def html(self):
        return weekly.render_html(dict(WEEK, context={
            "minCohort": 20, "excluded": ["vbb_provision"], "historyDays": 30,
            "build": {"commit": "abc1234"},
            "source": {"label": "pega2 – pega5 (ESVM)"}}))

    def test_nothing_is_loaded_from_anywhere_else(self):
        import re
        page = self.html()
        self.assertIsNone(re.search(r'(src|href)="https?://', page))
        self.assertIn("<style>", page)

    def test_the_numbers_and_the_rows_are_both_on_it(self):
        page = self.html()
        self.assertIn("65.5%", page)                     # MLT first pass
        self.assertIn("268494130000067", page)           # a unit row
        self.assertIn("2026-W33", page)

    def test_it_says_when_it_was_archived_and_from_what(self):
        page = self.html()
        self.assertIn("archived", page)
        self.assertIn("abc1234", page)

    def test_a_row_missing_a_field_does_not_cost_the_week_its_archive(self):
        """It runs unattended from a timer; one odd row must not take the
        whole snapshot down."""
        week = dict(WEEK, units=[{"dut": "268494130000067"}])
        page = weekly.render_html(dict(week, context={"minCohort": 20}))
        self.assertIn("268494130000067", page)

    def test_values_are_escaped(self):
        """A suite name is a machine string; one angle bracket in it should not
        rewrite the page."""
        week = dict(WEEK, units=[{"day": "2026-08-10", "station": "mlt",
                                  "dut": "<script>x</script>", "release": "r&d",
                                  "attempt": 1, "status": "pass",
                                  "failures": [], "url": None}])
        page = weekly.render_html(dict(week, context={"minCohort": 20}))
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("r&amp;d", page)


if __name__ == "__main__":
    unittest.main()
