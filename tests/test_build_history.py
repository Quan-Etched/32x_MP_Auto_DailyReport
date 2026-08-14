"""New build or retest, and what a returning unit failed last time.

The page exists to answer one question — when a release claims to fix
something, were the units it passed on the ones it was developed against? — so
the properties worth pinning are the ones that would quietly answer it wrongly.
"""

import unittest

from factory import build_history

DAY = 1786000000          # 2026-08-05T…Z, exact value irrelevant
HOUR = 3600


def run(dut, station, status, ts, failures=(), suite="mlt"):
    return {
        "dutSerial": dut, "stationKey": station, "status": status,
        "startTs": ts, "suite": suite,
        "runId": "mlt_2026.225.0-gitabc_run_dead#slot0",
        "failures": [{"display": name, "test": name} for name in failures],
    }


def payload(runs):
    return {"runs": runs,
            "stations": [{"key": "mlt", "label": "MLT"},
                         {"key": "htt", "label": "HTT"}],
            "window": {"from": "2026-08-01", "to": "2026-08-14"},
            "dataSource": {"label": "pega2 - pega5"}}


class ClassifyTest(unittest.TestCase):
    def rows(self, runs, **kwargs):
        bundle = build_history.build_bundle(payload(runs), **kwargs)
        return sorted(bundle["rows"], key=lambda r: r["ts"])

    def test_a_unit_s_first_appearance_is_a_new_build(self):
        rows = self.rows([run("A", "mlt", "pass", DAY)])
        self.assertEqual(rows[0]["kind"], build_history.NEW)
        self.assertEqual(rows[0]["attempt"], 1)

    def test_coming_back_after_a_failure_is_the_interesting_case(self):
        rows = self.rows([run("A", "mlt", "fail", DAY, ["SohuLlamaForwardIteratedTestCase"]),
                          run("A", "mlt", "pass", DAY + HOUR)])
        self.assertEqual(rows[1]["kind"], build_history.RETEST_AFTER_FAIL)
        self.assertEqual(rows[1]["priorStatus"], "fail")
        self.assertEqual(rows[1]["priorFailures"], ["SohuLlamaForwardIteratedTestCase"])

    def test_coming_back_after_a_pass_is_a_different_thing(self):
        rows = self.rows([run("A", "mlt", "pass", DAY),
                          run("A", "mlt", "pass", DAY + HOUR)])
        self.assertEqual(rows[1]["kind"], build_history.RETEST_AFTER_PASS)

    def test_an_error_counts_as_having_failed(self):
        rows = self.rows([run("A", "mlt", "error", DAY), run("A", "mlt", "pass", DAY + HOUR)])
        self.assertEqual(rows[1]["kind"], build_history.RETEST_AFTER_FAIL)

    def test_history_is_per_station(self):
        # A unit's first HTT run is a new build even if it has been through MLT
        # ten times. Sharing history across stations would mark almost nothing
        # as new after the first day.
        rows = self.rows([run("A", "mlt", "fail", DAY),
                          run("A", "htt", "pass", DAY + HOUR, suite="htt")])
        self.assertEqual(rows[1]["kind"], build_history.NEW)

    def test_attempts_count_up(self):
        rows = self.rows([run("A", "mlt", "fail", DAY + n * HOUR) for n in range(3)])
        self.assertEqual([r["attempt"] for r in rows], [1, 2, 3])

    def test_prior_history_from_outside_the_published_window_still_counts(self):
        # The whole window is walked and only the tail published. A unit whose
        # earlier failure fell outside the published days must not be presented
        # as a new build — that is the error that would make a fix look better
        # than it is.
        old = run("A", "mlt", "fail", DAY, ["SohuLlamaForwardIteratedTestCase"])
        recent = run("A", "mlt", "pass", DAY + 5 * 86400)
        bundle = build_history.build_bundle(payload([old, recent]), days=1)
        self.assertEqual(len(bundle["rows"]), 1)
        self.assertEqual(bundle["rows"][0]["kind"], build_history.RETEST_AFTER_FAIL)
        self.assertEqual(bundle["rows"][0]["priorFailures"],
                         ["SohuLlamaForwardIteratedTestCase"])

    def test_engineering_and_unclassified_runs_are_left_out(self):
        rows = self.rows([run("A", "engineering", "fail", DAY),
                          run("B", "unclassified", "fail", DAY),
                          run("C", "mlt", "pass", DAY)])
        self.assertEqual([r["dut"] for r in rows], ["C"])

    def test_a_run_with_no_timestamp_is_skipped_rather_than_ordered_wrongly(self):
        undated = run("A", "mlt", "fail", None)
        rows = self.rows([undated, run("A", "mlt", "pass", DAY)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], build_history.NEW)


class CountsTest(unittest.TestCase):
    def test_pass_rates_are_reported_per_kind(self):
        # The comparison that matters: a fix that only passes on units it was
        # written against shows up as a gap between these two rates.
        bundle = build_history.build_bundle(payload([
            run("A", "mlt", "pass", DAY),
            run("B", "mlt", "fail", DAY),
            run("A", "mlt", "pass", DAY + HOUR),
        ]))
        counts = bundle["counts"]
        self.assertEqual(counts["new"]["runs"], 2)
        self.assertAlmostEqual(counts["new"]["rate"], 0.5)
        self.assertEqual(counts["retestAfterPass"]["runs"], 1)
        self.assertAlmostEqual(counts["retestAfterPass"]["rate"], 1.0)

    def test_a_kind_with_no_graded_runs_has_no_rate(self):
        bundle = build_history.build_bundle(payload([run("A", "mlt", "unknown", DAY)]))
        self.assertIsNone(bundle["counts"]["new"]["rate"])

    def test_units_are_counted_per_station_not_per_serial(self):
        bundle = build_history.build_bundle(payload([
            run("A", "mlt", "pass", DAY), run("A", "htt", "pass", DAY, suite="htt")]))
        self.assertEqual(bundle["counts"]["units"], 2)


class LinkTest(unittest.TestCase):
    def test_a_slotted_run_links_to_its_own_slot(self):
        bundle = build_history.build_bundle(payload([run("A", "mlt", "pass", DAY)]))
        url = bundle["rows"][0]["url"]
        self.assertIn("suite_run/mlt_2026.225.0-gitabc_run_dead", url)
        self.assertTrue(url.endswith("slot_number=0"), url)

    def test_the_controller_matches_the_station(self):
        record = run("A", "l10_fat", "pass", DAY)
        record["runId"] = "L10_FAT_run_00a5c0b4"
        bundle = build_history.build_bundle(
            {"runs": [record], "stations": [{"key": "l10_fat", "label": "L10 FAT"}]})
        self.assertIn("pega4:3000", bundle["rows"][0]["url"])


class FailureNamesTest(unittest.TestCase):
    def test_the_nest_is_not_the_failure(self):
        """SltModuleNestedTestCase fails because a leaf under it did. Printing
        it as the prior failure puts the same word on every returning unit."""
        bundle = build_history.build_bundle(payload([
            run("A", "mlt", "fail", DAY,
                ["SltModuleNestedTestCase", "SohuLaneRepairTestCase"]),
            run("A", "mlt", "pass", DAY + HOUR)]))
        latest = max(bundle["rows"], key=lambda r: r["ts"])
        self.assertEqual(latest["priorFailures"], ["SohuLaneRepairTestCase"])


if __name__ == "__main__":
    unittest.main()
