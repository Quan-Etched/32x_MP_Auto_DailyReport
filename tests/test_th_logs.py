"""TH error codes read out of a run's log.jsonl files."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from factory import th_logs


def _step(step_id, unique_id, uri):
    return {
        "testStepArtifact": {
            "testStepId": step_id,
            "file": {
                "description": "Log file for Test Case: Case [{}]".format(unique_id),
                "uri": uri,
            },
        }
    }


def _diagnosis(step_id, verdict):
    return {
        "testStepArtifact": {
            "testStepId": step_id,
            "diagnosis": {"type": "FAIL", "verdict": verdict},
        }
    }


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n",
                    encoding="utf-8")


class ParseTest(unittest.TestCase):
    def test_two_diagnoses_on_one_step_are_both_kept(self):
        text = "\n".join(json.dumps(row) for row in (
            _step("1", "lane_repair", "lane.log"),
            _diagnosis("1", "TH-HBM-0006-S2Q9 no passing repair"),
            _diagnosis("1", "later TH-HBM-0008-S4Q9 sweep did not finish"),
        ))
        index = th_logs.parse_log(text)
        self.assertEqual(
            [code for diag in index.diagnoses for code in diag.codes],
            ["TH-HBM-0006-S2Q9", "TH-HBM-0008-S4Q9"])

    def test_a_nested_row_reads_its_own_log_not_the_other_chips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "log.jsonl", [
                _step("2", "chip0", "artifacts/chip0/chip.log"),
                _diagnosis("2", "TH-HBM-0006-S2Q9 chip0 rollup"),
                _diagnosis("2", "TH-HBM-0008-S4Q9 chip0 again"),
                _step("3", "chip1", "artifacts/chip1/chip.log"),
                _diagnosis("3", "TH-HAR-9998-S3Q0 chip1"),
            ])
            _write(root / "artifacts" / "chip0" / "run" / "log.jsonl", [
                _step("21", "lane_repair", "lane.log"),
                _diagnosis("21", "TH-HBM-0006-S2Q9 detail"),
                _diagnosis("21", "TH-C2C-0001-S2Q9 also this"),
            ])
            self.assertEqual(th_logs.codes_under(root, "chip0"), [
                "TH-HBM-0006-S2Q9", "TH-HBM-0008-S4Q9",
            ])
            self.assertEqual(th_logs.codes_under(root, "chip0_lane_repair"), [
                "TH-HBM-0006-S2Q9", "TH-C2C-0001-S2Q9",
            ])
            self.assertEqual(th_logs.codes_under(root, "chip1"),
                             ["TH-HAR-9998-S3Q0"])

    def test_a_cached_run_is_not_downloaded_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "codes.json").write_text(json.dumps({
                "lane_repair": ["TH-HBM-0006-S2Q9", "TH-HBM-0008-S4Q9"],
            }), encoding="utf-8")
            original_dir = th_logs._run_dir
            original_download = th_logs._download_tree
            downloaded = []

            def _dir(run_id, host):
                return root

            def _download(*_args):
                downloaded.append(True)
                return False

            th_logs._run_dir = _dir
            th_logs._download_tree = _download
            previous = os.environ.get("FACTORY_PEGA")
            os.environ["FACTORY_PEGA"] = "1"
            try:
                got = th_logs.codes_for_run("run_1", host="pega4")
            finally:
                th_logs._run_dir = original_dir
                th_logs._download_tree = original_download
                if previous is None:
                    os.environ.pop("FACTORY_PEGA", None)
                else:
                    os.environ["FACTORY_PEGA"] = previous
            self.assertEqual(got["lane_repair"],
                             ["TH-HBM-0006-S2Q9", "TH-HBM-0008-S4Q9"])
            self.assertEqual(downloaded, [])

    def test_a_day_before_the_cutoff_is_not_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_dir = th_logs._run_dir
            original_download = th_logs._download_tree
            downloaded = []

            def _dir(run_id, host):
                return root

            def _download(*_args):
                downloaded.append(True)
                return False

            th_logs._run_dir = _dir
            th_logs._download_tree = _download
            previous = os.environ.get("FACTORY_PEGA")
            os.environ["FACTORY_PEGA"] = "1"
            try:
                got = th_logs.codes_for_run("run_old", host="pega4",
                                           day="2026-09-24")
            finally:
                th_logs._run_dir = original_dir
                th_logs._download_tree = original_download
                if previous is None:
                    os.environ.pop("FACTORY_PEGA", None)
                else:
                    os.environ["FACTORY_PEGA"] = previous
            self.assertEqual(got, {})
            self.assertEqual(downloaded, [])


if __name__ == "__main__":
    unittest.main()
