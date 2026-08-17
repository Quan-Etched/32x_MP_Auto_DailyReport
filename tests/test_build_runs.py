"""The run-level drill-down bundle, and the OCP link templates.

The point of these tests is that the drill-down agrees with the tiles it is
reached from: the same run population, the same day boundaries, the same release
numbering. A table that quietly disagrees with the number clicked would send
someone to the floor chasing a run that was never in the count.
"""

import json
import unittest

from factory import build_runs, daily, links, stations


def run(run_id, status="pass", ts=1786000000, station="l10_sft", attempt=1,
        version="2026.220.0-git13b172eb", dut="D1", tests=None, level="l10",
        suite="L10_SFT", duration=61.4):
    return {
        "runId": run_id, "level": level, "dutSerial": dut, "suite": suite,
        "version": version, "startTs": ts,
        "endTs": (ts + 60) if ts else None,
        "durationSec": duration, "status": status, "attempt": attempt,
        "stationKey": station, "tests": tests if tests is not None else [],
    }


def payload(runs, tz="America/Los_Angeles"):
    return {
        "runs": runs, "timezone": tz, "generatedAt": "2026-08-12T00:00:00+00:00",
        "window": {"from": "2026-07-13T07:00:00Z", "to": "2026-08-12T00:59:59Z"},
        "source": "eos-api",
    }


class BundleTest(unittest.TestCase):
    def test_row_carries_the_fields_the_table_shows(self):
        bundle = build_runs.build_bundle(payload([run("R1")]))
        row = bundle["runs"][0]
        self.assertEqual(row["i"], "R1")
        self.assertEqual(row["d"], "D1")
        self.assertEqual(row["k"], "l10_sft")
        self.assertEqual(row["s"], "pass")
        self.assertEqual(row["a"], 1)
        self.assertEqual(row["r"], "220")          # release, not full version
        self.assertEqual(row["u"], 61)             # seconds, rounded

    def test_release_matches_the_station_pages_numbering(self):
        bundle = build_runs.build_bundle(payload([run("R1", version="2026.207.0-gitabc")]))
        self.assertEqual(bundle["runs"][0]["r"],
                         stations.release_of("2026.207.0-gitabc"))

    def test_day_matches_the_daily_bucket(self):
        # A run at 00:30 UTC belongs to the *previous* Los Angeles day, which is
        # the bucket the day chart puts it in. Precomputing it here is the whole
        # reason the browser does not do timezone math.
        ts = 1786407600          # 2026-08-11T00:20:00Z -> 2026-08-10 17:20 in LA
        bundle = build_runs.build_bundle(payload([run("R1", ts=ts)]))
        self.assertEqual(bundle["runs"][0]["day"], daily.day_key(ts, "America/Los_Angeles"))
        self.assertEqual(bundle["runs"][0]["day"], "2026-08-10")

    def test_newest_run_is_first(self):
        bundle = build_runs.build_bundle(payload([
            run("old", ts=1785000000), run("new", ts=1786000000),
        ]))
        self.assertEqual([r["i"] for r in bundle["runs"]], ["new", "old"])

    def test_unclassified_runs_are_kept_with_their_bucket(self):
        bundle = build_runs.build_bundle(payload([run("R1", station=None)]))
        self.assertEqual(bundle["runs"][0]["k"], stations.UNCLASSIFIED)

    def test_missing_timestamp_does_not_crash_the_row(self):
        rows = build_runs.build_bundle(payload([run("R1", ts=None)]))["runs"]
        self.assertIsNone(rows[0]["day"])
        self.assertIsNone(rows[0]["t"])


class TestCaseInterningTest(unittest.TestCase):
    def test_names_are_interned_once_and_referenced_by_index(self):
        tests = [
            {"name": "CHK_BIOS", "status": "pass", "durationSec": 3.2},
            {"name": "CHK_MEM", "status": "FAILED", "durationSec": None},
        ]
        bundle = build_runs.build_bundle(payload([
            run("R1", tests=tests), run("R2", tests=tests),
        ]))
        # Two runs of the same suite must not duplicate the name table — that
        # collapse is what keeps the bundle at ~1.5 MB instead of ~6 MB.
        self.assertEqual(bundle["testNames"], ["CHK_BIOS", "CHK_MEM"])
        first = bundle["runs"][0]["T"]
        self.assertEqual(first[0], [0, build_runs.TEST_STATUSES.index("pass"), 3])
        self.assertEqual(bundle["runs"][1]["T"], first)

    def test_unrecognised_test_status_becomes_unknown_not_dropped(self):
        bundle = build_runs.build_bundle(payload([
            run("R1", tests=[{"name": "T", "status": "WEDGED", "durationSec": 1}]),
        ]))
        code = bundle["runs"][0]["T"][0][1]
        self.assertEqual(build_runs.TEST_STATUSES[code], "unknown")
        self.assertEqual(len(bundle["runs"][0]["T"]), 1)

    def test_container_entries_are_flagged_by_name_index(self):
        # `chip1` fails only because a leaf under it failed; the First fail
        # column has to skip it or every MLT failure reads as "chip1".
        bundle = build_runs.build_bundle(payload([run("R1", tests=[
            {"name": "chip1", "displayName": "SltModuleNestedTestCase",
             "status": "fail", "durationSec": 30},
            {"name": "chip1_dma", "displayName": "SohuDmaTestCase",
             "status": "fail", "durationSec": 5},
        ])]))
        names = bundle["testNames"]
        containers = [names[i] for i in bundle["containerNames"]]
        self.assertEqual(containers, ["chip1"])
        # Both rows are kept — a container is real data, just not a signature.
        self.assertEqual(len(bundle["runs"][0]["T"]), 2)

    def test_a_leaf_test_is_not_flagged_as_a_container(self):
        bundle = build_runs.build_bundle(payload([run("R1", tests=[
            {"name": "CHK_BIOS", "displayName": "CheckBiosBootOrder",
             "status": "fail", "durationSec": 1},
        ])]))
        self.assertEqual(bundle["containerNames"], [])

    def test_unnamed_test_still_gets_a_row(self):
        bundle = build_runs.build_bundle(payload([
            run("R1", tests=[{"status": "pass", "durationSec": 1}]),
        ]))
        self.assertEqual(bundle["testNames"], ["(unnamed)"])


class FilterPopulationTest(unittest.TestCase):
    """The populations runs.html filters to, checked against daily.py.

    These mirror runtable.js's `statusMatches`. If the two ever disagree, the
    drill-down stops reconciling with the tile.
    """

    RUNS = [
        run("p1", status="pass", attempt=1),
        run("f1", status="fail", attempt=1),
        run("e1", status="error", attempt=1),
        run("s1", status="skip", attempt=1),
        run("p2", status="pass", attempt=2),
    ]

    def test_abort_means_error(self):
        aborts = [r for r in self.RUNS if r["status"] == "error"]
        self.assertEqual(len(aborts), daily.station_summary(self.RUNS)["abort"])

    def test_graded_is_the_pass_fail_error_triple(self):
        graded = [r for r in self.RUNS if r["status"] in daily.GRADED]
        self.assertEqual(len(graded), daily.station_summary(self.RUNS)["graded"])
        self.assertNotIn("s1", [r["runId"] for r in graded])

    def test_first_attempt_and_graded_is_the_fpy_denominator(self):
        firsts = [r for r in self.RUNS
                  if r["attempt"] == 1 and r["status"] in daily.GRADED]
        self.assertEqual(len(firsts), daily.station_summary(self.RUNS)["fpyTotal"])


class LinkTest(unittest.TestCase):
    def test_no_run_template_is_reported_as_unresolved(self):
        described = links.describe()
        self.assertFalse(described["runLinksResolve"])
        self.assertIsNone(described["runTemplate"])
        self.assertTrue(described["base"].startswith("https://"))

    def test_template_from_the_environment_is_expanded(self):
        row = {"i": "L10_RIN_2026.220.0-git13b172eb_20260810_234450", "l": "l10",
               "d": "267694410002", "su": "L10_RIN", "v": "2026.220.0", "r": "220",
               "day": "2026-08-10"}
        url = links.expand("{base}/run/{runId}?level={level}&dut={dut}", row)
        self.assertEqual(
            url,
            "https://ocplogs.core.etched.com/run/"
            "L10_RIN_2026.220.0-git13b172eb_20260810_234450?level=l10&dut=267694410002")

    def test_empty_template_expands_to_nothing(self):
        self.assertEqual(links.expand("", {"i": "R1"}), "")


class WriteBundleTest(unittest.TestCase):
    def test_bundle_is_loadable_javascript_with_one_global(self):
        import tempfile
        from pathlib import Path

        bundle = build_runs.build_bundle(payload([run("R1")]))
        with tempfile.TemporaryDirectory() as tmp:
            target = build_runs.write_bundle(bundle, Path(tmp) / "runs.js")
            text = target.read_text(encoding="utf-8")
        self.assertIn("window.__FACTORY_RUNS__ = ", text)
        body = text.split("= ", 1)[1].rstrip().rstrip(";")
        self.assertEqual(json.loads(body)["runs"][0]["i"], "R1")


if __name__ == "__main__":
    unittest.main()


class ControllerLinkTest(unittest.TestCase):
    """A run from the controllers has a real address; OCP Logs has none.

    Sending a reader from the controller-sourced page to OCP's search box made
    them look up by hand a run whose URL the bundle already holds.
    """

    def bundle(self, source):
        payload = {
            "runs": [{"runId": "mlt_2026.220.0-gitabc_run_dead#slot5",
                      "dutSerial": "268494130000067", "stationKey": "mlt",
                      "level": "module", "suite": "mlt_2026.220.0-gitabc",
                      "version": "2026.220.0-gitabc", "status": "fail",
                      "startTs": 1786000000, "attempt": 1, "tests": []}],
            "source": source, "timezone": "UTC",
            "stations": [{"key": "mlt", "label": "MLT", "levels": ["module"]}],
        }
        return build_runs.build_bundle(payload, {})

    def test_controller_data_carries_a_url_template_and_host_map(self):
        links = self.bundle("pega")["links"]["pega"]
        self.assertIn("suite_run", links["urlTemplate"])
        self.assertEqual(links["hosts"]["mlt"], "pega3")
        self.assertEqual(links["hosts"]["l10_fat"], "pega4")
        self.assertEqual(links["hosts"]["l11_test"], "pega5")

    def test_eos_data_carries_none(self):
        """EOS has no per-run route; offering one would be a broken link."""
        self.assertNotIn("pega", self.bundle("eos")["links"])

    def test_the_run_id_still_carries_its_slot(self):
        """The slot is the half of the address that says which of the eight
        modules in the fixture this row is."""
        row = self.bundle("pega")["runs"][0]
        self.assertTrue(str(row["i"]).endswith("#slot5"))
