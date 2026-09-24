"""The Update button's control endpoint: progress parsing, guards, ingest reuse.

The job itself shells out to tools/hourly_refresh.sh, which talks to the live
EOS API — so these tests drive the parts that decide what the browser is told,
with the subprocess replaced by a scripted stream.
"""

import tempfile
import unittest
from pathlib import Path

from factory import control, items


class StepParsingTest(unittest.TestCase):
    """The browser's progress list is only as honest as this parser."""

    def setUp(self):
        self.job = control.UpdateJob()

    def feed(self, *lines):
        for line in lines:
            self.job._consume(line)
        return {step["key"]: step["state"] for step in self.job.steps}

    def test_a_step_marker_starts_that_step(self):
        states = self.feed("::step collect Fetching runs from EOS")
        self.assertEqual(states["collect"], "running")
        self.assertEqual(states["build"], "pending")

    def test_reaching_a_later_step_completes_the_earlier_ones(self):
        # The pipeline never announces "collect finished" — arriving at build is
        # the only evidence collect is done, and the list must not stall on it.
        states = self.feed("::step collect Fetching", "::step build Rebuilding")
        self.assertEqual(states["collect"], "done")
        self.assertEqual(states["items"], "done")
        self.assertEqual(states["build"], "running")

    def test_a_skipped_step_is_not_marked_running(self):
        # FACTORY_REFRESH_ITEMS=0 omits the items marker entirely.
        states = self.feed("::step collect Fetching", "::step publish Publishing")
        self.assertEqual(states["items"], "done")
        self.assertEqual(states["publish"], "running")

    def test_step_markers_stay_out_of_the_log(self):
        self.feed("::step collect Fetching", "Bundled 1062 runs")
        self.assertEqual(list(self.job.log), ["Bundled 1062 runs"])

    def test_a_lock_conflict_is_reported_as_busy_not_success(self):
        # The script exits 0 when it defers to a running tick. Calling that a
        # success would tell the reader the data is fresh when no fetch ran.
        self.feed("SKIP another refresh is already running (/x/.refresh.lock)")
        self.assertEqual(self.job.state, "busy")
        self.assertIn("already running", self.job.message)

    def test_a_fetch_failure_surfaces_as_the_message(self):
        self.feed("Fetch FAILED: TLS handshake to eos.core.etched.com failed")
        self.assertIn("TLS handshake", self.job.message)

    def test_the_log_is_bounded(self):
        for i in range(control.MAX_LOG_LINES + 50):
            self.job._consume("line {}".format(i))
        self.assertEqual(len(self.job.log), control.MAX_LOG_LINES)
        self.assertEqual(self.job.log[-1], "line {}".format(control.MAX_LOG_LINES + 49))


class SnapshotTest(unittest.TestCase):
    def test_idle_job_reports_every_step_up_front(self):
        # The panel renders the whole plan greyed out, so the reader knows what
        # "full update" means before committing to it.
        snapshot = control.UpdateJob().snapshot()
        self.assertEqual(snapshot["state"], "idle")
        self.assertEqual([s["key"] for s in snapshot["steps"]],
                         ["collect", "items", "build", "publish"])
        self.assertTrue(all(s["state"] == "pending" for s in snapshot["steps"]))

    def test_snapshot_is_a_copy(self):
        job = control.UpdateJob()
        job.snapshot()["steps"][0]["state"] = "done"
        self.assertEqual(job.steps[0]["state"], "pending")


class NoCacheTest(unittest.TestCase):
    """Everything the dev server hands out is served no-cache.

    It was /data/ only — the bundles, on the reasoning that an update rewrites
    them under the browser's feet. The pages and their scripts are rewritten by
    editing them, which happens far more often, and both halves went wrong in
    one afternoon: a fixed customize.js the browser would not re-fetch, so the
    station picker stayed empty and read as unfixed; then a weekly page showing
    three June rows from a cached bundle while the file on disk had twelve
    weeks. Each cost far more to diagnose than caching a file on localhost
    saves.

    `no-cache`, not `no-store`: an unchanged 9 MB bundle still revalidates to a
    304 instead of being re-sent.
    """

    def headers_for(self, path):
        import factory.control as control

        sent = []

        class Fake(control.ControlHandler):
            def __init__(self):                       # no socket, no request
                self.path = path

            def send_header(self, key, value):
                sent.append((key, value))

        # SimpleHTTPRequestHandler.end_headers writes to the output buffer;
        # only this class's contribution is under test.
        original = control.http.server.SimpleHTTPRequestHandler.end_headers
        control.http.server.SimpleHTTPRequestHandler.end_headers = lambda self: None
        try:
            Fake().end_headers()
        finally:
            control.http.server.SimpleHTTPRequestHandler.end_headers = original
        return sent

    def test_a_data_bundle_is_not_cached(self):
        self.assertIn(("Cache-Control", "no-cache"),
                      self.headers_for("/data/weekly.js"))

    def test_a_page_script_is_not_cached_either(self):
        """The regression this exists for: customize.js and weeklysummary.js
        are edited far more often than the bundles are rebuilt."""
        for path in ("/customize.js", "/weeklysummary.js", "/dailysheet.js"):
            self.assertIn(("Cache-Control", "no-cache"),
                          self.headers_for(path), path)

    def test_nor_is_a_page(self):
        for path in ("/", "/weekly.html", "/customize.html"):
            self.assertIn(("Cache-Control", "no-cache"),
                          self.headers_for(path), path)

    def test_it_is_no_cache_and_not_no_store(self):
        """no-store would re-send the 9 MB run bundle on every reload."""
        values = [v for k, v in self.headers_for("/data/runs_pega.js")
                  if k == "Cache-Control"]
        self.assertEqual(values, ["no-cache"])


class GuardTest(unittest.TestCase):
    """POST is a real action: it publishes factory data to a shared URL."""

    class FakeHandler(control.ControlHandler):
        def __init__(self, headers):          # bypass BaseHTTPRequestHandler setup
            self.headers = headers
            self.path = "/api/update"

    def guard(self, headers):
        return self.FakeHandler(headers)._guard_ok()

    def test_a_local_post_with_the_header_is_allowed(self):
        self.assertTrue(self.guard({"Host": "127.0.0.1:8787", "X-Factory-Update": "1"}))
        self.assertTrue(self.guard({"Host": "localhost:8787", "X-Factory-Update": "1"}))

    def test_a_rebound_dns_name_is_refused(self):
        # evil.com resolving to 127.0.0.1 reaches the socket; the Host header is
        # what gives it away.
        self.assertFalse(self.guard({"Host": "evil.com:8787", "X-Factory-Update": "1"}))

    def test_a_form_post_without_the_header_is_refused(self):
        # A cross-origin form can hit the port but cannot set a custom header.
        self.assertFalse(self.guard({"Host": "127.0.0.1:8787"}))


class SftGuardTest(unittest.TestCase):
    class FakeHandler(control.ControlHandler):
        def __init__(self, headers):
            self.headers = headers
            self.path = "/api/sft-sync"

    def allowed(self, headers):
        return self.FakeHandler(headers)._sft_guard_ok()

    def test_the_review_host_names_are_allowed(self):
        header = {"X-Factory-Update": "1"}
        self.assertTrue(self.allowed(dict(header, Host="127.0.0.1:8080")))
        self.assertTrue(self.allowed(dict(
            header, Host="production-failure-analysis.i.etched.com")))
        self.assertTrue(self.allowed(dict(
            header, Host="production-failure-analysis.usw2.i.etched.com")))
        self.assertFalse(self.allowed(dict(header, Host="evil.com")))


class DaysParamTest(unittest.TestCase):
    class FakeHandler(control.ControlHandler):
        def __init__(self, path):
            self.path = path

    def days(self, path):
        return self.FakeHandler(path)._days_param()

    def test_absent_or_junk_falls_back_to_the_default(self):
        self.assertIsNone(self.days("/api/update"))
        self.assertIsNone(self.days("/api/update?days=lots"))

    def test_a_window_is_clamped_to_something_collectable(self):
        self.assertEqual(self.days("/api/update?days=30"), 30)
        self.assertEqual(self.days("/api/update?days=99999"), 365)
        self.assertEqual(self.days("/api/update?days=0"), 1)


class FakeClient:
    """Counts API calls so the incremental claim can be tested, not assumed."""

    def __init__(self):
        self.artifact_calls = 0

    def artifacts(self, level, dut_serial, run_id):
        self.artifact_calls += 1
        return [{"role": "event_stream", "relPath": "log.jsonl"}]

    def artifact_content(self, level, dut_serial, run_id, rel_path):
        return ('{"testStepArtifact": {"testStepId": "1", "measurement": '
                '{"name": "ber_0_0_1", "value": 1.5, "unit": "dB"}}}')


class IngestRunsTest(unittest.TestCase):
    """One ingest path shared by `cli items` and the refresh behind the button."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.conn = items.open_db(Path(self.dir.name) / "items.sqlite")
        self.runs = [
            {"runId": "r1", "level": "l10", "dutSerial": "D1", "stationKey": "l10_sft",
             "suite": "L10_6U_SFT", "release": "207", "status": "pass", "startTs": 1},
            {"runId": "r2", "level": "l10", "dutSerial": "D2", "stationKey": "l10_sft",
             "suite": "L10_6U_SFT", "release": "207", "status": "fail", "startTs": 2},
        ]

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def test_first_pass_ingests_every_run(self):
        client = FakeClient()
        stats = items.ingest_runs(self.conn, client, self.runs)
        self.assertEqual(stats["runs"], 2)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(client.artifact_calls, 2)

    def test_a_second_pass_costs_no_api_calls(self):
        # This is what makes the items stage cheap enough to sit inside an
        # hourly tick and behind a button.
        items.ingest_runs(self.conn, FakeClient(), self.runs)
        client = FakeClient()
        stats = items.ingest_runs(self.conn, client, self.runs)
        self.assertEqual(stats["skipped"], 2)
        self.assertEqual(stats["runs"], 0)
        self.assertEqual(client.artifact_calls, 0)

    def test_rebuild_reingests_everything(self):
        items.ingest_runs(self.conn, FakeClient(), self.runs)
        client = FakeClient()
        stats = items.ingest_runs(self.conn, client, self.runs, rebuild=True)
        self.assertEqual(stats["runs"], 2)
        self.assertEqual(client.artifact_calls, 2)

    def test_one_unreachable_run_does_not_abort_the_rest(self):
        from factory.eos_client import EOSError

        class Flaky(FakeClient):
            def artifacts(self, level, dut_serial, run_id):
                if run_id == "r1":
                    raise EOSError("404 artifact listing")
                return super().artifacts(level, dut_serial, run_id)

        seen = []
        stats = items.ingest_runs(self.conn, Flaky(), self.runs,
                                  on_error=lambda run_id, err: seen.append(run_id))
        self.assertEqual(stats["runs"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(seen, ["r1"])

    def test_progress_is_reported_with_a_total_to_measure_against(self):
        many = []
        for i in range(25):
            run = dict(self.runs[0])
            run["runId"] = "r{}".format(i)
            many.append(run)
        seen = []
        items.ingest_runs(self.conn, FakeClient(), many,
                          on_progress=lambda done, added, total: seen.append((done, total)))
        self.assertEqual(seen, [(10, 25), (20, 25)])


if __name__ == "__main__":
    unittest.main()
