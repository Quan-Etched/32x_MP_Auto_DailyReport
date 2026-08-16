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
    "units": [{"dut": "268494130000067", "station": "mlt"}],
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


if __name__ == "__main__":
    unittest.main()
