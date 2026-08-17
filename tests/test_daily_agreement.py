"""The station page and the daily tracker must not disagree about a day.

Both are built from the controllers and both were being read as "the line's
yield on 08-14". They differed for two reasons that had nothing to do with the
data: the tracker counts one row per unit with the last attempt winning while
the station page counted every run, and the tracker cuts days in UTC — matching
the line's own sheet — while the station page cut them in Pacific, putting the
same units a day earlier.
"""

import unittest
from datetime import datetime, timezone

from factory import build_stations, daily


def ts(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


def run(dut, status, when, station="mlt"):
    return {"dutSerial": dut, "status": status, "startTs": ts(when),
            "stationKey": station, "level": "module", "attempt": 1,
            "suite": "mlt_2026.220.0-gitabc", "version": "2026.220.0-gitabc"}


class PerUnitDayTest(unittest.TestCase):
    def test_a_retested_unit_is_one_row_not_two(self):
        """Failed at 09:00, passed at 14:00. The tracker shows one pass; the
        station page was showing a pass and a failure and calling it 50%."""
        runs = [run("A", "fail", "2026-08-14T09:00"),
                run("A", "pass", "2026-08-14T14:00")]
        per_run = daily.daily_yield(runs, "UTC")[0]
        per_unit = daily.daily_yield(runs, "UTC", per_unit=True)[0]
        self.assertEqual((per_run["pass"], per_run["fail"]), (1, 1))
        self.assertEqual((per_unit["pass"], per_unit["fail"]), (1, 0))

    def test_the_last_attempt_of_the_day_is_the_one_that_counts(self):
        runs = [run("A", "pass", "2026-08-14T09:00"),
                run("A", "fail", "2026-08-14T14:00")]
        row = daily.daily_yield(runs, "UTC", per_unit=True)[0]
        self.assertEqual((row["pass"], row["fail"]), (0, 1))

    def test_units_without_a_serial_are_kept_not_merged(self):
        """Nothing to collapse them onto; dropping them would quietly lose
        runs from the count."""
        runs = [dict(run("A", "pass", "2026-08-14T09:00"), dutSerial=""),
                dict(run("B", "fail", "2026-08-14T10:00"), dutSerial="")]
        row = daily.daily_yield(runs, "UTC", per_unit=True)[0]
        self.assertEqual(row["pass"] + row["fail"], 2)

    def test_first_pass_yield_is_unchanged_by_the_mode(self):
        runs = [run("A", "fail", "2026-08-14T09:00"),
                run("A", "pass", "2026-08-14T14:00")]
        self.assertEqual(daily.daily_yield(runs, "UTC")[0]["fpy"],
                         daily.daily_yield(runs, "UTC", per_unit=True)[0]["fpy"])


class DayBoundaryTest(unittest.TestCase):
    """17:30 Pacific on 08-11 is 00:30 UTC on 08-12, and the line's sheet files
    it under 08-12 — verified against a runId stamped 20260812_0030."""

    def payload(self, source):
        return {"runs": [run("A", "pass", "2026-08-12T00:30")],
                "source": source, "timezone": "America/Los_Angeles",
                "stations": [{"key": "mlt", "label": "MLT", "levels": ["module"]}]}

    def test_controller_data_is_bucketed_in_utc(self):
        bundle = build_stations.build_bundle(self.payload("pega"))
        self.assertEqual(bundle["views"]["mlt"]["daily"][0]["day"], "2026-08-12")
        self.assertEqual(bundle["dayBasis"]["timezone"], "UTC")

    def test_eos_data_keeps_the_factory_local_day(self):
        """EOS is one row per fixture and has no tracker to agree with."""
        bundle = build_stations.build_bundle(self.payload("eos"))
        self.assertEqual(bundle["views"]["mlt"]["daily"][0]["day"], "2026-08-11")
        self.assertEqual(bundle["dayBasis"]["counts"], "runs")


class WindowTest(unittest.TestCase):
    def payload(self, days):
        runs = [run("U%d" % d, "pass", "2026-08-%02dT12:00" % (1 + d))
                for d in range(days)]
        return {"runs": runs, "source": "pega", "timezone": "UTC",
                "stations": [{"key": "mlt", "label": "MLT", "levels": ["module"]}]}

    def test_only_the_last_seven_days_are_reported(self):
        """A month-long average hides the week inside it: a release that landed
        on Tuesday is a fifth of a 30-day bar and all of a 7-day one."""
        bundle = build_stations.build_bundle(self.payload(30))
        self.assertEqual(len(bundle["views"]["mlt"]["daily"]), 7)
        self.assertEqual(bundle["window"]["days"], 7)

    def test_the_window_is_anchored_on_the_newest_day_with_data(self):
        """Anchoring on today would empty the page over a quiet weekend."""
        bundle = build_stations.build_bundle(self.payload(30))
        self.assertEqual(bundle["views"]["mlt"]["daily"][-1]["day"], "2026-08-30")

    def test_a_short_history_is_not_padded(self):
        bundle = build_stations.build_bundle(self.payload(3))
        self.assertEqual(len(bundle["views"]["mlt"]["daily"]), 3)

    def test_the_collected_window_is_still_recorded(self):
        """30 days are still collected — the weekly page needs them to tell a
        unit's first attempt from its fourth."""
        payload = dict(self.payload(30), window={"from": "2026-07-19",
                                                 "to": "2026-08-30"})
        bundle = build_stations.build_bundle(payload)
        self.assertEqual(bundle["collectedWindow"]["from"], "2026-07-19")


if __name__ == "__main__":
    unittest.main()
