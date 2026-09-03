"""dashboard/colfilter.js: the Excel-style column menu, driven for real.

The customize page's Result column replaced five tickboxes that decided which
rows were ever computed. The tickboxes were crude but they were also obvious;
a filter menu is neither, and everything it does happens inside event handlers
that no source-text assertion can reach. So the module is loaded under
JavaScriptCore with a DOM that *keeps* its listeners, and the test opens the
menu, unticks values, searches, sorts and presses Apply — the sequence a reader
performs.

Two behaviours are worth naming because they are the ones that look like bugs
when they break:

* a menu offers the values the OTHER columns leave reachable, so it can never
  offer one that would empty the table;
* ties keep the order the caller supplied, so sorting by a column with repeats
  does not shuffle rows the builder deliberately put in time order.

Skipped where ``jsc`` is absent, which is every Linux box — the same rule
tests/test_bigdata_js.py uses.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSC = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)


class ColFilterJs(unittest.TestCase):
    def test_the_menu_filters_sorts_and_searches(self):
        if not JSC.is_file():
            self.skipTest(f"JavaScriptCore not at {JSC} (macOS only)")
        proc = subprocess.run(
            [str(JSC), "-e", f"var ROOT={json.dumps(str(ROOT))};",
             str(ROOT / "tests" / "colfilter_dom_test.js")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        report = proc.stdout + proc.stderr
        self.assertNotIn("FAIL", report, "\n" + report)
        self.assertNotIn("Exception", report, "\n" + report)
        self.assertIn("colfilter.js: ok", report, "\n" + report)
        # A harness that silently stopped running assertions would still print
        # the ok line, so hold it to a count.
        self.assertGreaterEqual(report.count("ok   "), 25, "\n" + report)


if __name__ == "__main__":
    unittest.main()
