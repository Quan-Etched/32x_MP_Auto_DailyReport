"""dashboard/bigdata.js: the two-phase run bundle, run for real.

The page ships ~16 KB of controls and fetches the 8.6 MB of runs when a button
needs them. Two promises hold that together, and both are easy to break silently:

* the heavy arrays are filled **in place**, because customize.js and
  dutsearch.js each do ``var RUNS = DATA.runs || []`` at load and hold that
  reference forever. Replace the array instead of filling it and both views go
  quietly empty.
* the fill is **chunked**, because ``push.apply(arr, huge)`` spreads its argument
  into the call frame and overflows the stack well below the 135,476 test names
  a live build carries. That only fails at production size.

Both are asserted against the real module under JavaScriptCore with a DOM and
``fetch`` stub. Skipped where ``jsc`` is absent, which is every Linux box.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSC = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)


class BigDataJs(unittest.TestCase):
    def test_the_heavy_half_loads_on_demand_and_fills_in_place(self):
        if not JSC.is_file():
            self.skipTest(f"JavaScriptCore not at {JSC} (macOS only)")
        proc = subprocess.run(
            [str(JSC), "-e", f"var ROOT={json.dumps(str(ROOT))};",
             str(ROOT / "tests" / "bigdata_dom_test.js")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        report = proc.stdout + proc.stderr
        self.assertNotIn("FAIL", report, "\n" + report)
        self.assertIn("bigdata.js: ok", report, "\n" + report)
        self.assertGreaterEqual(report.count("ok   "), 12, "\n" + report)


if __name__ == "__main__":
    unittest.main()
