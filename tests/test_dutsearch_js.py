"""dashboard/dutsearch.js: a serial's history across two sources.

The serial search reads the runs bundle, which starts at the line's reporting
horizon. Chris asked on 2026-09-07 for a board's re-test history to reach its
first test; measured the next day against the published bundle,
268086800000021 had two runs in it, both dated 09-07, and four MLT attempts in
July that the page could not show.

Attempts from before that horizon now come from data/unit_history.js — thinner
rows, no duration and no per-test detail — and the two files do not overlap, so
they are joined rather than merged. The module is run for real under
JavaScriptCore with the DOM stub, because the properties that matter are ones a
reader would be misled by if they broke: an attempt number that counts from the
window rather than from the unit's first run, or a blank failure list on a row
whose failures were simply never collected. Skipped where ``jsc`` is absent,
which is every Linux box.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSC = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)


class DutSearchJs(unittest.TestCase):
    def test_a_serial_s_history_reaches_before_the_collected_window(self):
        if not JSC.is_file():
            self.skipTest(f"JavaScriptCore not at {JSC} (macOS only)")
        proc = subprocess.run(
            [str(JSC), "-e", f"var ROOT={json.dumps(str(ROOT))};",
             str(ROOT / "tests" / "dutsearch_dom_test.js")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        report = proc.stdout + proc.stderr
        self.assertNotIn("FAIL", report, "\n" + report)
        self.assertIn("dutsearch.js: ok", report, "\n" + report)
        self.assertGreaterEqual(report.count("ok   "), 15, "\n" + report)


if __name__ == "__main__":
    unittest.main()
