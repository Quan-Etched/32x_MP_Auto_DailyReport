"""dashboard/weeklysummary.js: the denominator a weekly cell claims.

2026-W36 produced the question this pins. MLT read "40%" with "90 u" under it
and the rolled column read "—", and both were correct: first-pass yield counts
a unit only on its first ever run at a step, that week put 90 units through MLT
of which 10 were new, and 10 is under the twenty-unit floor the rolled product
needs. On the page the two facts were unreadable together — a solid-looking 40%
beside a dash that read as broken instrumentation.

So the module is run for real, under JavaScriptCore with the DOM stub, and
asserted on: the count under a yield is that yield's own denominator, the thin
mark follows it rather than the size of the week's window, and the dash carries
the counts it is waiting for. Skipped where ``jsc`` is absent, which is every
Linux box.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSC = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)


class WeeklySummaryJs(unittest.TestCase):
    def test_a_cell_says_what_its_yield_is_over(self):
        if not JSC.is_file():
            self.skipTest(f"JavaScriptCore not at {JSC} (macOS only)")
        proc = subprocess.run(
            [str(JSC), "-e", f"var ROOT={json.dumps(str(ROOT))};",
             str(ROOT / "tests" / "weeklysummary_dom_test.js")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        report = proc.stdout + proc.stderr
        self.assertNotIn("FAIL", report, "\n" + report)
        self.assertIn("weeklysummary.js: ok", report, "\n" + report)
        self.assertGreaterEqual(report.count("ok   "), 20, "\n" + report)


if __name__ == "__main__":
    unittest.main()
