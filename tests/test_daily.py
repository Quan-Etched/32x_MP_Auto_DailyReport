"""The four station views, and the fetch-vs-update bookkeeping."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from factory import daily, fetchstate

TZ = "America/Los_Angeles"


def ts(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


def run(day, hour=18, status="pass", dut="D1", attempt=1, version="2026.207.0-gitabc",
        failures=(), minute=0, station="l10_fat"):
    """A run at 18:00 UTC = 11:00 Los Angeles, safely inside the same local day."""
    return {
        "runId": "r-{}-{}-{}-{}".format(dut, day, hour, minute),
        "level": "l10", "suite": "L10_6U_FAT", "stationKey": station,
        "dutSerial": dut, "version": version,
        "startTs": ts("2026-08-{:02d}T{:02d}:{:02d}:00".format(day, hour, minute)),
        "status": status, "attempt": attempt, "durationSec": 100.0,
        "testCounts": {"pass": 3, "fail": len(failures), "error": 0, "skip": 0, "unknown": 0},
        "failures": [{"test": f, "display": None, "code": None, "log": None} for f in failures],
    }


class DailyYieldTest(unittest.TestCase):
    def test_one_row_per_local_day_with_mix_and_fpy(self):
        runs = [
            run(3, status="pass", dut="A"),
            run(3, status="fail", dut="B", minute=10),
            run(3, status="error", dut="C", minute=20),
            run(4, status="pass", dut="D"),
        ]
        rows = daily.daily_yield(runs, TZ)
        self.assertEqual([r["day"] for r in rows], ["2026-08-03", "2026-08-04"])
        self.assertEqual((rows[0]["pass"], rows[0]["fail"], rows[0]["abort"]), (1, 1, 1))
        self.assertAlmostEqual(rows[0]["fpy"], 1 / 3)

    def test_days_are_cut_in_the_factory_timezone(self):
        # 04:00 UTC on the 4th is still 21:00 on the 3rd in Los Angeles.
        rows = daily.daily_yield([run(4, hour=4)], TZ)
        self.assertEqual(rows[0]["day"], "2026-08-03")

    def test_retries_do_not_count_toward_fpy(self):
        runs = [run(3, status="fail", dut="A", attempt=1),
                run(3, status="pass", dut="A", attempt=2, minute=30)]
        row = daily.daily_yield(runs, TZ)[0]
        self.assertEqual(row["fpy"], 0.0)          # the first attempt failed
        self.assertEqual(row["fpyTotal"], 1)

    def test_thin_sample_is_flagged(self):
        self.assertTrue(daily.daily_yield([run(3)], TZ)[0]["thin"])
        many = [run(3, dut="D%d" % i, minute=i) for i in range(6)]
        self.assertFalse(daily.daily_yield(many, TZ)[0]["thin"])

    def test_skipped_runs_leave_the_denominator(self):
        row = daily.daily_yield([run(3, status="pass", dut="A"),
                                 run(3, status="skip", dut="B", minute=5)], TZ)[0]
        self.assertEqual(row["graded"], 1)
        self.assertEqual(row["fpy"], 1.0)


class ReleaseYieldTest(unittest.TestCase):
    def test_groups_by_release_with_its_date_range(self):
        runs = [
            run(3, version="2026.204.0-gitaaa", dut="A"),
            run(5, version="2026.204.0-gitbbb", dut="B", status="fail"),
            run(6, version="2026.207.0-gitccc", dut="C"),
        ]
        rows = daily.release_yield(runs, TZ)
        self.assertEqual([r["release"] for r in rows], ["204", "207"])
        self.assertEqual(rows[0]["firstDay"], "2026-08-03")
        self.assertEqual(rows[0]["lastDay"], "2026-08-05")
        self.assertEqual(rows[0]["runs"], 2)
        # A release can ship under several build hashes; all are kept.
        self.assertEqual(len(rows[0]["versions"]), 2)

    def test_releases_sort_numerically_not_lexically(self):
        runs = [run(3, version="2026.9.0-x", dut="A"),
                run(3, version="2026.10.0-y", dut="B", minute=5)]
        self.assertEqual([r["release"] for r in daily.release_yield(runs, TZ)], ["9", "10"])


class ParetoTest(unittest.TestCase):
    def test_buckets_by_area_with_cumulative_share(self):
        runs = [
            run(3, status="fail", dut="A", failures=["chip1_c2c_integrity"]),
            run(3, status="fail", dut="B", minute=5, failures=["chip2_c2c_integrity"]),
            run(3, status="fail", dut="C", minute=9, failures=["chip1_lane_repair"]),
        ]
        rows = daily.top_yield_hits(runs)
        self.assertEqual(rows[0]["area"], "C2C")
        self.assertEqual(rows[0]["fails"], 2)
        self.assertAlmostEqual(rows[0]["share"], 2 / 3)
        self.assertAlmostEqual(rows[-1]["cumulativeShare"], 1.0)

    def test_nested_containers_are_excluded(self):
        runs = [{
            "status": "fail", "dutSerial": "A", "startTs": ts("2026-08-03T18:00:00"),
            "attempt": 1, "failures": [
                {"test": "chip1", "display": "SltModuleNestedTestCase"},
                {"test": "chip1_c2c_integrity", "display": "SohuC2cTestCase"},
            ],
        }]
        rows = daily.top_yield_hits(runs)
        self.assertEqual([r["area"] for r in rows], ["C2C"])

    def test_first_failure_counts_each_run_once(self):
        runs = [run(3, status="fail", dut="A",
                    failures=["chip1_c2c_integrity", "chip1_lane_repair"])]
        self.assertEqual(sum(r["fails"] for r in daily.top_yield_hits(runs)), 2)
        self.assertEqual(sum(r["fails"] for r in daily.first_failure_areas(runs)), 1)


class RetestTest(unittest.TestCase):
    def test_retest_rate_and_recovery(self):
        runs = [
            # A: failed then passed on retry -> retested, recovered
            run(3, status="fail", dut="A", attempt=1),
            run(3, status="pass", dut="A", attempt=2, minute=30),
            # B: passed first time -> not retested
            run(3, status="pass", dut="B", minute=5),
            # C: failed twice -> retested, still failing
            run(3, status="fail", dut="C", attempt=1, minute=6),
            run(4, status="fail", dut="C", attempt=2),
        ]
        r = daily.retest(runs, TZ)
        self.assertEqual(r["units"], 3)
        self.assertEqual(r["retestedUnits"], 2)
        self.assertAlmostEqual(r["retestRate"], 2 / 3)
        self.assertEqual(r["totalRetestRuns"], 2)
        self.assertEqual(r["failedFirst"], 2)          # A and C
        self.assertEqual(r["recovered"], 1)            # only A
        self.assertAlmostEqual(r["recoveryRate"], 0.5)
        self.assertEqual(r["stillFailing"], 1)         # C

    def test_depth_histogram_caps_at_five_plus(self):
        runs = [run(3, dut="A", attempt=i + 1, minute=i) for i in range(7)]
        depth = {d["attempts"]: d["units"] for d in daily.retest(runs, TZ)["depth"]}
        self.assertEqual(depth, {5: 1})

    def test_detail_is_ordered_by_run_count(self):
        runs = [run(3, dut="A"), run(3, dut="B", minute=1), run(3, dut="B", attempt=2, minute=2)]
        detail = daily.retest(runs, TZ)["detail"]
        self.assertEqual(detail[0]["dut"], "B")
        self.assertEqual(detail[0]["attempts"], 2)


class SplitByStationTest(unittest.TestCase):
    def test_uses_stationKey_not_the_absent_api_station_field(self):
        runs = [run(3, station="l10_fat"), run(3, dut="B", minute=5, station="mlt")]
        grouped = daily.split_by_station(runs)
        self.assertEqual(sorted(grouped), ["l10_fat", "mlt"])


class FetchStateTest(unittest.TestCase):
    """Last fetch and last update must move independently."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "fetch_state.json"

    def tearDown(self):
        self.dir.cleanup()

    def payload(self, runs):
        return {"runs": runs, "window": {"from": "a", "to": "b"}, "levelErrors": {}}

    def test_identical_data_advances_fetch_but_not_update(self):
        runs = [run(3, dut="A")]
        first = fetchstate.record_fetch(self.payload(runs), self.path)
        self.assertTrue(first["changed"])
        first_update = first["lastUpdateAt"]

        second = fetchstate.record_fetch(self.payload(list(runs)), self.path)
        self.assertFalse(second["changed"])
        self.assertEqual(second["lastUpdateAt"], first_update)
        self.assertEqual(second["consecutiveNoChange"], 1)
        self.assertEqual(second["totalFetches"], 2)

    def test_new_data_moves_the_update_stamp(self):
        fetchstate.record_fetch(self.payload([run(3, dut="A")]), self.path)
        third = fetchstate.record_fetch(
            self.payload([run(3, dut="A"), run(3, dut="B", minute=5)]), self.path)
        self.assertTrue(third["changed"])
        self.assertEqual(third["consecutiveNoChange"], 0)

    def test_a_changed_status_counts_as_an_update_even_at_the_same_run_count(self):
        fetchstate.record_fetch(self.payload([run(3, dut="A", status="fail")]), self.path)
        after = fetchstate.record_fetch(
            self.payload([run(3, dut="A", status="pass")]), self.path)
        self.assertTrue(after["changed"])

    def test_hash_ignores_ordering(self):
        a, b = run(3, dut="A"), run(3, dut="B", minute=5)
        self.assertEqual(fetchstate.content_hash([a, b]), fetchstate.content_hash([b, a]))

    def test_a_failed_fetch_advances_neither_stamp(self):
        ok = fetchstate.record_fetch(self.payload([run(3, dut="A")]), self.path)
        failed = fetchstate.record_failure("boom", self.path)
        self.assertEqual(failed["lastFetchStatus"], "error")
        self.assertEqual(failed["lastUpdateAt"], ok["lastUpdateAt"])
        self.assertEqual(failed["lastFetchAt"], ok["lastFetchAt"])

    def test_per_station_stamps_are_independent(self):
        # Driven through _station_state with explicit stamps: two record_fetch
        # calls in the same wall-clock second would produce identical strings
        # and prove nothing.
        before = fetchstate._station_state({}, [
            run(3, dut="A", station="mlt"),
            run(3, dut="B", minute=5, station="l10_fat"),
        ], "2026-08-07T10:00:00+00:00")

        after = fetchstate._station_state(before, [
            run(3, dut="A", station="mlt"),
            run(3, dut="B", minute=5, station="l10_fat"),
            run(3, dut="C", minute=9, station="l10_fat"),
        ], "2026-08-07T11:00:00+00:00")

        # MLT gained nothing, so its stamp must not move; L10 FAT's must.
        self.assertEqual(after["mlt"]["lastUpdateAt"], "2026-08-07T10:00:00+00:00")
        self.assertEqual(after["l10_fat"]["lastUpdateAt"], "2026-08-07T11:00:00+00:00")

    def test_a_station_that_goes_quiet_is_retained(self):
        fetchstate.record_fetch(self.payload([run(3, dut="A", station="mlt")]), self.path)
        after = fetchstate.record_fetch(self.payload([]), self.path)
        self.assertIn("mlt", after["stations"])
        self.assertEqual(after["stations"]["mlt"]["runs"], 0)


if __name__ == "__main__":
    unittest.main()
