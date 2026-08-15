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

BUNDLE = {
    "window": {"from": "2026-08-09", "to": "2026-08-15", "days": 7},
    "historyDays": 30,
    "build": {"commit": "abc1234"},
    "source": {"label": "pega2 – pega5 (ESVM)"},
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
    "totals": {"rolledFpy": 0.281, "rolledOver": ["MLT"], "minCohort": 20,
               "excludedThin": [{"label": "L10 SFT", "units": 1, "newUnits": 0}],
               "units": 229, "runs": 285, "stations": 2},
}


def write_bundle(directory):
    path = Path(directory) / "fpy.js"
    path.write_text("window.__FACTORY_FPY__ = {};\n".format(json.dumps(BUNDLE)),
                    encoding="utf-8")
    return path


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = write_bundle(self.tmp.name)
        self.root = Path(self.tmp.name) / "weekly"

    def test_the_folder_is_named_for_the_window_not_for_today(self):
        """Named for the data, so the folder still means something when it is
        opened in November."""
        weekly.archive(bundle=self.bundle, root=self.root)
        self.assertTrue((self.root / "2026-08-15").is_dir())

    def test_the_bundle_is_stored_verbatim(self):
        weekly.archive(bundle=self.bundle, root=self.root)
        stored = json.loads((self.root / "2026-08-15" / "fpy.json").read_text())
        self.assertEqual(stored["totals"]["rolledFpy"], 0.281)
        self.assertEqual(stored["rows"][0]["units"], 228)

    def test_a_missing_bundle_says_what_to_run(self):
        with self.assertRaises(FileNotFoundError) as caught:
            weekly.archive(bundle=Path(self.tmp.name) / "nope.js", root=self.root)
        self.assertIn("make fpy", str(caught.exception))


class SummaryTest(unittest.TestCase):
    def summary(self):
        return weekly.summarise(BUNDLE)

    def test_it_reads_without_the_dashboard(self):
        text = self.summary()
        self.assertIn("2026-08-09 to 2026-08-15", text)
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


if __name__ == "__main__":
    unittest.main()
