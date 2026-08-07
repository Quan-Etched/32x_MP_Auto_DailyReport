"""Metric definitions are pinned here.

Each test states the definition it is protecting, because these are the numbers a
line lead makes decisions on and a silent change of definition is worse than a
crash. The dashboard's JS mirrors these; docs/metrics.md is the prose version.
"""

import unittest
from datetime import datetime, timezone

from factory import hourly

TZ = "America/Los_Angeles"


def ts(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


def run(hour_utc, status="pass", dut="D1", attempt=1, duration=100.0,
        station="ST-01", failures=(), minute=0):
    """A minimal run record shaped like collect.collect() output."""
    return {
        "runId": "r-{}-{}-{}".format(dut, hour_utc, minute),
        "level": "l10",
        "dutSerial": dut,
        "station": station,
        "suite": "L10_tests",
        "startTs": ts("2026-08-03T{:02d}:{:02d}:00".format(hour_utc, minute)),
        "durationSec": duration,
        "status": status,
        "attempt": attempt,
        "testCounts": {"pass": 3, "fail": len(failures), "error": 0, "skip": 0, "unknown": 0},
        "failures": [{"test": name, "code": "E_X", "log": None} for name in failures],
    }


class HourBucketTest(unittest.TestCase):
    def test_buckets_use_the_factory_timezone_not_utc(self):
        # 16:00 UTC is 09:00 in Los Angeles — the hour the floor means.
        self.assertEqual(hourly.hour_key(ts("2026-08-03T16:30:00"), TZ), "2026-08-03T09")
        self.assertEqual(hourly.hour_key(ts("2026-08-03T16:30:00"), "UTC"), "2026-08-03T16")

    def test_runs_without_a_timestamp_are_excluded_not_guessed(self):
        runs = [run(16), {"runId": "x", "status": "pass", "startTs": None}]
        self.assertEqual(len(hourly.usable(runs)), 1)


class PercentileTest(unittest.TestCase):
    def test_interpolates_and_handles_degenerate_input(self):
        self.assertEqual(hourly.percentile([10, 20, 30], 0.5), 20)
        self.assertEqual(hourly.percentile([10, 20], 0.5), 15)
        self.assertEqual(hourly.percentile([7], 0.9), 7)
        self.assertIsNone(hourly.percentile([], 0.5))


class HourlyMetricsTest(unittest.TestCase):
    def test_one_row_per_hour_that_has_a_run(self):
        rows = hourly.hourly_metrics([run(16), run(16, minute=30, dut="D2"), run(18, dut="D3")], TZ)
        self.assertEqual([r["hour"] for r in rows], ["2026-08-03T09", "2026-08-03T11"])
        self.assertEqual(rows[0]["runs"], 2)

    def test_units_counts_distinct_duts_not_runs(self):
        rows = hourly.hourly_metrics(
            [run(16, dut="D1"), run(16, minute=10, dut="D1", attempt=2), run(16, minute=20, dut="D2")],
            TZ,
        )
        self.assertEqual(rows[0]["runs"], 3)
        self.assertEqual(rows[0]["units"], 2)

    def test_pass_rate_covers_every_attempt_fpy_only_the_first(self):
        # D1 fails then passes on retry; D2 passes first time.
        runs = [
            run(16, status="fail", dut="D1", attempt=1),
            run(16, minute=20, status="pass", dut="D1", attempt=2),
            run(16, minute=30, status="pass", dut="D2", attempt=1),
        ]
        row = hourly.hourly_metrics(runs, TZ)[0]
        self.assertAlmostEqual(row["passRate"], 2 / 3)       # 2 of 3 runs passed
        self.assertAlmostEqual(row["firstPassYield"], 1 / 2)  # 1 of 2 first attempts passed

    def test_errored_runs_count_against_yield_but_stay_distinguishable(self):
        row = hourly.hourly_metrics(
            [run(16, status="error", dut="D1"), run(16, minute=10, status="pass", dut="D2")], TZ
        )[0]
        self.assertEqual(row["errored"], 1)
        self.assertEqual(row["failed"], 0)
        self.assertAlmostEqual(row["passRate"], 0.5)

    def test_unknown_status_is_left_out_of_the_rate_rather_than_assumed(self):
        row = hourly.hourly_metrics(
            [run(16, status="unknown", dut="D1"), run(16, minute=10, status="pass", dut="D2")], TZ
        )[0]
        self.assertEqual(row["passRate"], 1.0)

    def test_hour_with_no_verdicts_reports_none_not_zero(self):
        row = hourly.hourly_metrics([run(16, status="unknown")], TZ)[0]
        self.assertIsNone(row["passRate"])

    def test_cycle_time_percentiles(self):
        runs = [run(16, minute=m, dut="D%d" % m, duration=d)
                for m, d in enumerate([10, 20, 30, 40, 100])]
        row = hourly.hourly_metrics(runs, TZ)[0]
        self.assertEqual(row["cycleTimeMedian"], 30)
        self.assertEqual(row["cycleTimeP90"], 76)

    def test_station_counts_are_per_hour(self):
        row = hourly.hourly_metrics(
            [run(16, station="ST-01"), run(16, minute=5, dut="D2", station="ST-02"),
             run(16, minute=9, dut="D3", station="ST-01")], TZ
        )[0]
        self.assertEqual(row["stations"], {"ST-01": 2, "ST-02": 1})


class ParetoTest(unittest.TestCase):
    def test_counts_run_occurrences_and_accumulates_share(self):
        runs = [
            run(16, status="fail", dut="D1", failures=["A", "B"]),
            run(16, minute=5, status="fail", dut="D2", failures=["A"]),
            run(17, status="fail", dut="D3", failures=["A"]),
        ]
        rows = hourly.failure_pareto(runs)
        self.assertEqual(rows[0]["test"], "A")
        self.assertEqual(rows[0]["failures"], 3)
        self.assertAlmostEqual(rows[0]["share"], 0.75)
        self.assertAlmostEqual(rows[1]["cumulativeShare"], 1.0)
        self.assertEqual(rows[0]["duts"], 3)

    def test_empty_input_is_an_empty_ranking(self):
        self.assertEqual(hourly.failure_pareto([run(16)]), [])


class BreakdownTest(unittest.TestCase):
    def test_station_rows_are_ranked_by_volume(self):
        runs = [run(16, station="ST-01"), run(16, minute=5, dut="D2", station="ST-01"),
                run(16, minute=9, dut="D3", station="ST-02", status="fail")]
        rows = hourly.station_breakdown(runs)
        self.assertEqual(rows[0]["station"], "ST-01")
        self.assertEqual(rows[0]["passRate"], 1.0)
        self.assertEqual(rows[1]["passRate"], 0.0)

    def test_dut_rows_surface_repeat_offenders_first(self):
        runs = [
            run(16, status="fail", dut="D1", attempt=1),
            run(17, status="fail", dut="D1", attempt=2, minute=5),
            run(16, status="fail", dut="D2", minute=10),
        ]
        rows = hourly.dut_breakdown(runs)
        self.assertEqual(rows[0]["dut"], "D1")
        self.assertEqual(rows[0]["failures"], 2)
        self.assertEqual(rows[0]["lastStatus"], "fail")


class SummaryTest(unittest.TestCase):
    def test_rates_are_per_active_hour_not_per_elapsed_hour(self):
        # Three runs in two active hours, with a quiet hour between them.
        runs = [run(16, dut="D1"), run(16, minute=5, dut="D2"), run(18, dut="D3")]
        head = hourly.summary(runs, TZ)
        self.assertEqual(head["activeHours"], 2)
        self.assertEqual(head["units"], 3)
        self.assertAlmostEqual(head["unitsPerHour"], 1.5)
        self.assertAlmostEqual(head["runsPerHour"], 1.5)

    def test_untimestamped_runs_are_reported_not_silently_dropped(self):
        head = hourly.summary([run(16), {"runId": "x", "startTs": None, "status": "pass"}], TZ)
        self.assertEqual(head["runsWithoutTimestamp"], 1)


if __name__ == "__main__":
    unittest.main()
