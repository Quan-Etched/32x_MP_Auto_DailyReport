"""dashboard/trace.js: a cached failure must not be permanent.

Reported 2026-09-03: "Could not load the genealogy for 268633790001: HTTP 404".
The file was there. It returned 200 to curl, it was byte-identical in shape to
the 743 others that worked, and a cross-check of the published index against
the files on disk found every indexed unit present and nothing missing. A
publish was run while polling the URL and produced no 404s either.

What was actually wrong is that both trace fetches asked for
``cache: 'force-cache'``. That is the right call for the happy path — the
bundle is 736 KB and immutable for the life of a snapshot. It also means a
stored *error* is reused with the same enthusiasm and never revalidated: one
404, from a moment before the trace bundle was published or a connection that
dropped mid-flight, and that one reader sees it for ever while everyone else
sees the file. Nothing on the page clears it; only a hard reload does, and
nobody guesses that.

So a failed fetch now retries once with ``cache: 'reload'``, which bypasses the
stored copy. A genuinely absent file fails twice and says so; a stale cached
failure heals itself silently.

Writing the test found a second fault behind the same symptom: ``ensureUnit``
had no in-flight guard, so two ticks landing together each fetched, and
whichever landed LAST decided what was drawn — a late failure painting an error
over a tree that had already loaded. That is the same report, from a different
cause, and it is why this is a behavioural test and not an assertion about the
source text.

Skipped where ``jsc`` is absent, which is every Linux box.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSC = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)


class TraceRetryJs(unittest.TestCase):
    def test_a_cached_404_heals_and_a_real_one_still_reports(self):
        if not JSC.is_file():
            self.skipTest(f"JavaScriptCore not at {JSC} (macOS only)")
        proc = subprocess.run(
            [str(JSC), "-e", f"var ROOT={json.dumps(str(ROOT))};",
             str(ROOT / "tests" / "trace_retry_test.js")],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        report = proc.stdout + proc.stderr
        self.assertNotIn("FAIL", report, "\n" + report)
        self.assertNotIn("Exception", report, "\n" + report)
        self.assertIn("trace-retry: ok", report, "\n" + report)
        self.assertGreaterEqual(report.count("ok   "), 8, "\n" + report)


if __name__ == "__main__":
    unittest.main()
