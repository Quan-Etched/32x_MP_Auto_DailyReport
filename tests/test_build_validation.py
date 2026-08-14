"""One suite's validation run, and the reconciliation that explains the count.

The page exists because two people counted the same validation and got 24 and
39. The properties worth pinning are the ones that would put it back to two
numbers with no explanation: which units belong to the suite, which of them had
been through the station before, and whether the day's other suites are
reported as the difference rather than folded into it.
"""

import unittest
from datetime import datetime, timezone

from factory import build_validation

SUITE = "mlt_validation_2026.225.0-gitb937ca2c"
OTHER = "mlt_2026.220.0-git2f1c2f23"
DAY = "2026-08-14"
TS = 1786726800           # 2026-08-14T17:00Z, inside DAY


def collected(units, siblings=(), day_total=None):
    """The shape ``collect()`` returns, without going near the network."""
    rows = {
        dut: {"dut": dut, "slot": slot, "status": status, "failures": list(fails),
              "run": "abc123", "url": "http://pega3:3000/suite_run/x?slot_number=%d" % slot,
              "day": DAY, "partNumber": "81S1..."}
        for dut, slot, status, fails in units
    }
    sibs = [{"suite": name, "runs": 1, "units": count, "overlap": overlap, "only": []}
            for name, count, overlap in siblings]
    total = day_total if day_total is not None else len(rows) + sum(
        s["units"] - s["overlap"] for s in sibs)
    return {"suite": SUITE, "host": "pega3", "days": [DAY],
            "runs": [{"runId": "x", "short": "abc123", "day": DAY, "slots": len(rows),
                      "startedAt": DAY + "T10:00:00", "station": "pt2_mlt1",
                      "url": "http://pega3:3000/suite_run/x"}],
            "units": rows, "siblings": sibs, "dayTotal": total}


def history_run(dut, status, ts, failures=(), station="mlt", suite=OTHER):
    return {"dutSerial": dut, "stationKey": station, "status": status,
            "startTs": ts, "suite": suite,
            "runId": OTHER + "_run_dead#slot0",
            "failures": [{"display": name, "test": name} for name in failures]}


def payload(runs):
    return {"runs": runs, "stations": [{"key": "mlt", "label": "MLT"}],
            "window": {"from": "2026-07-20", "to": DAY}}


class ClassifyTest(unittest.TestCase):
    def rows(self, units, runs=()):
        bundle = build_validation.build_bundle(payload(list(runs)), collected(units))
        return {row["dut"]: row for row in bundle["rows"]}

    def test_a_unit_with_no_earlier_run_here_is_a_new_build(self):
        rows = self.rows([("A", 0, "pass", [])])
        self.assertTrue(rows["A"]["isNew"])
        self.assertEqual(rows["A"]["priorRuns"], 0)

    def test_a_unit_that_failed_here_before_carries_that_failure_forward(self):
        rows = self.rows(
            [("A", 0, "pass", [])],
            [history_run("A", "fail", TS - 86400, ["SohuLlamaForwardIteratedTestCase"])])
        self.assertFalse(rows["A"]["isNew"])
        self.assertEqual(rows["A"]["priorStatus"], "fail")
        self.assertEqual(rows["A"]["priorFailures"],
                         ["SohuLlamaForwardIteratedTestCase"])

    def test_the_suite_s_own_run_does_not_make_the_unit_a_retest(self):
        """The validation run is on this page; counting it as prior history
        would call all 24 units retests and erase the split the page is for."""
        rows = self.rows([("A", 0, "pass", [])],
                         [history_run("A", "pass", TS, suite=SUITE)])
        self.assertTrue(rows["A"]["isNew"])

    def test_the_same_build_under_a_second_name_is_still_the_same_event(self):
        """08-14 ran the 225 commit as both mlt_2026.225.0-gitb937ca2c and
        mlt_validation_2026.225.0-gitb937ca2c. Matching on the name reports 0
        new builds; matching on the commit reports the 16 that are real."""
        rows = self.rows([("A", 0, "pass", [])],
                         [history_run("A", "pass", TS - 6000,
                                      suite="mlt_2026.225.0-gitb937ca2c")])
        self.assertTrue(rows["A"]["isNew"])

    def test_a_run_earlier_the_same_day_is_still_prior_history(self):
        """The exclusion is the suite, not the date — a unit that ran 220 in the
        morning and 225 in the afternoon is a retest either way."""
        rows = self.rows([("A", 0, "pass", [])],
                         [history_run("A", "fail", TS - 7200, ["X"])])
        self.assertFalse(rows["A"]["isNew"])

    def test_another_station_s_history_is_not_this_station_s(self):
        rows = self.rows([("A", 0, "fail", ["X"])],
                         [history_run("A", "fail", TS - 86400, station="htt")])
        self.assertTrue(rows["A"]["isNew"])


class CountsTest(unittest.TestCase):
    def bundle(self, units, runs=(), **kwargs):
        return build_validation.build_bundle(payload(list(runs)),
                                             collected(units, **kwargs))

    def test_new_and_seen_are_counted_separately(self):
        bundle = self.bundle(
            [("A", 0, "pass", []), ("B", 1, "fail", ["X"]), ("C", 2, "pass", [])],
            [history_run("C", "fail", TS - 86400, ["X"])])
        counts = bundle["counts"]
        self.assertEqual(counts["units"], 3)
        self.assertEqual(counts["passed"], 2)
        self.assertEqual((counts["new"]["units"], counts["new"]["passed"]), (2, 1))
        self.assertEqual((counts["seen"]["units"], counts["seen"]["passed"]), (1, 1))

    def test_the_day_s_other_suites_are_reported_not_absorbed(self):
        """24 on this page and 39 on the tracker have to both appear, or the
        page answers one question and leaves the disagreement standing."""
        bundle = self.bundle([("A", 0, "pass", []), ("B", 1, "pass", [])],
                             siblings=[(OTHER, 15, 0)])
        self.assertEqual(bundle["counts"]["units"], 2)
        self.assertEqual(bundle["reconcile"]["dayTotal"], 17)
        self.assertEqual(bundle["reconcile"]["siblings"][0]["suite"], OTHER)
        self.assertEqual(bundle["reconcile"]["siblings"][0]["overlap"], 0)

    def test_failures_first_so_the_page_opens_on_what_needs_reading(self):
        bundle = self.bundle([("A", 0, "pass", []), ("B", 1, "fail", ["X"])])
        self.assertEqual([row["dut"] for row in bundle["rows"]], ["B", "A"])

    def test_repeated_prior_failures_collapse_to_the_distinct_signatures(self):
        bundle = self.bundle(
            [("A", 0, "pass", [])],
            [history_run("A", "fail", TS - 172800, ["X", "Y"]),
             history_run("A", "fail", TS - 86400, ["X"])])
        self.assertEqual(bundle["rows"][0]["priorFailures"], ["X", "Y"])
        self.assertEqual(bundle["rows"][0]["priorRuns"], 2)


class BundleShapeTest(unittest.TestCase):
    def test_the_bundle_names_the_suite_and_host_it_measured(self):
        bundle = build_validation.build_bundle(payload([]),
                                               collected([("A", 0, "pass", [])]))
        self.assertEqual(bundle["suite"], SUITE)
        self.assertEqual(bundle["host"], "pega3")
        self.assertEqual(bundle["days"], [DAY])
        self.assertTrue(bundle["build"])

    def test_written_bundle_is_loadable_javascript(self):
        import tempfile
        from pathlib import Path

        bundle = build_validation.build_bundle(payload([]),
                                               collected([("A", 0, "pass", [])]))
        with tempfile.TemporaryDirectory() as tmp:
            path = build_validation.write_bundle(bundle, Path(tmp) / "validation.js")
            text = path.read_text(encoding="utf-8")
        self.assertIn("window.__FACTORY_VALIDATION__ = {", text)
        self.assertIn(SUITE, text)


class SuiteResolutionTest(unittest.TestCase):
    """Which suite the page shows when nobody says.

    A page pinned to one release stops being true the week after that release
    ships, and an unattended dashboard going quietly stale is worse than one
    that is obviously broken.
    """

    def setUp(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, build_validation, "collect", build_validation.collect)

    def listing(self, days):
        from factory import pega

        def fake(day, host="pega3"):
            return days.get(day, [])
        pega.day_suite_runs = fake

    def entry(self, suite, at, run=None):
        return {"suite_run_id": (run or suite) + "_run_abc",
                "suite_name": suite, "start_time": at}

    def test_the_newest_validation_suite_wins(self):
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        self.listing({today: [
            self.entry("mlt_2026.220.0-gitold", today + "T01:00:00Z"),
            self.entry("mlt_validation_2026.226.0-gitnew", today + "T09:00:00Z"),
            self.entry("mlt_validation_2026.225.0-gitb937ca2c", today + "T02:00:00Z"),
        ]})
        self.assertEqual(build_validation.latest_suite(),
                         "mlt_validation_2026.226.0-gitnew")

    def test_a_production_only_day_resolves_to_nothing(self):
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        self.listing({today: [self.entry("mlt_2026.220.0-gitold",
                                         today + "T01:00:00Z")]})
        self.assertIsNone(build_validation.latest_suite(days=1))

    def test_nothing_found_falls_back_to_the_named_default(self):
        """So the page still renders something rather than an empty table."""
        self.listing({})
        collected = build_validation.collect(days=1)
        self.assertEqual(collected["suite"], build_validation.DEFAULT_SUITE)

    def test_an_explicit_suite_is_never_overridden(self):
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        self.listing({today: [
            self.entry("mlt_validation_2026.226.0-gitnew", today + "T09:00:00Z")]})
        collected = build_validation.collect(suite="mlt_validation_2026.1-gitpin",
                                             days=1)
        self.assertEqual(collected["suite"], "mlt_validation_2026.1-gitpin")


if __name__ == "__main__":
    unittest.main()
