"""The station page's time range, and the weekly page's frozen charts.

Two questions the pages could not answer before. The station charts covered a
rolling seven days with no way to see further back, and the weekly page had the
numbers for a week but not the shape of it.
"""

import unittest

from factory import build_stations, build_weekly


def _run(day, station="mlt", status="pass", release="mlt_1.0", attempt=1):
    """One unit run, in the shape the collectors emit."""
    import calendar
    from datetime import datetime, timezone
    ts = calendar.timegm(datetime(
        int(day[:4]), int(day[5:7]), int(day[8:10]), 12, 0,
        tzinfo=timezone.utc).timetuple())
    return {"startTs": ts, "stationKey": station, "status": status,
            "version": release, "dutSerial": "SN%s" % day, "attempt": attempt,
            "level": "module", "runId": "r-%s-%s" % (day, station),
            "testNames": [], "failedTests": []}


class RangeTest(unittest.TestCase):
    def payload(self):
        # Eleven days at or after the floor, so the seven-day window is a
        # genuine subset, and one before it, so the floor has something to cut.
        days = ["2026-07-25"] + [
            "2026-08-%02d" % d for d in (1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13)]
        return {"runs": [_run(d) for d in days], "source": "pega",
                "timezone": "UTC", "generatedAt": "2026-08-13T00:00:00+00:00"}

    def bundle(self):
        return build_stations.build_ranged_bundle(self.payload())

    def test_the_default_range_is_seven_days_and_says_so(self):
        ranges = self.bundle()["ranges"]
        self.assertEqual(ranges["default"], "7d")
        first = ranges["options"][0]
        self.assertEqual((first["key"], first["note"]), ("7d", "default"))

    def test_the_wide_range_names_the_floor_it_used(self):
        """The label a reader sees and the date the build actually cut at are
        the same string, so they cannot drift."""
        bundle = self.bundle()
        self.assertEqual(bundle["ranges"]["floor"], build_stations.RANGE_FLOOR)
        self.assertIn(build_stations.RANGE_FLOOR,
                      bundle["ranges"]["options"][1]["note"])

    def test_the_floor_keeps_bring_up_out_of_all(self):
        """2026-07-25 is before the line produced. "All" must not reach it."""
        bundle = self.bundle()
        self.assertGreaterEqual(bundle["windowAll"]["from"],
                                build_stations.RANGE_FLOOR)

    def test_all_reaches_further_back_than_the_default(self):
        bundle = self.bundle()
        self.assertLess(bundle["windowAll"]["from"], bundle["window"]["from"])
        self.assertGreater(len(bundle["viewsAll"]["__all__"]["daily"]),
                           len(bundle["views"]["__all__"]["daily"]))

    def test_views_stays_the_narrow_set(self):
        """Everything already reading `views` — the flow page's links, the
        cross-source comparison — keeps its meaning. The wider set is additive
        and lives under its own key."""
        bundle = self.bundle()
        self.assertLessEqual(len(bundle["views"]["__all__"]["daily"]),
                             build_stations.WINDOW_DAYS)
        self.assertNotEqual(bundle["views"]["__all__"]["daily"],
                            bundle["viewsAll"]["__all__"]["daily"])

    def test_all_is_a_superset_of_the_default(self):
        """It was not, and that was reachable: the default keeps the last seven
        days *with data*, so on a quiet fortnight it reached back past the
        floor and picked up bring-up that All excludes — All showing fewer runs
        than the range inside it. The floor now applies to both."""
        bundle = self.bundle()
        seven = {s["key"]: s["runs"] for s in bundle["stations"]}
        every = {s["key"]: s["runs"] for s in bundle["stationsAll"]}
        for key in seven:
            self.assertGreaterEqual(every[key], seven[key], key)
        self.assertGreater(every["__all__"], seven["__all__"])
        self.assertLessEqual(bundle["windowAll"]["from"], bundle["window"]["from"])


class WeekChartsTest(unittest.TestCase):
    def payload(self):
        # Two weeks either side of the one under test, so a chart that was not
        # frozen would visibly pick them up.
        days = ["2026-08-07", "2026-08-10", "2026-08-12", "2026-08-16",
                "2026-08-18"]
        return {"runs": [_run(d) for d in days], "source": "pega",
                "timezone": "UTC"}

    def charts(self):
        return build_weekly._charts(self.payload(), "2026-08-10", "2026-08-16")

    def test_the_week_is_frozen_to_its_own_days(self):
        """Monday to Sunday and nothing either side. The fixture has runs on
        08-07 and 08-18 precisely so a chart that was not frozen would show
        them."""
        rows = self.charts()["daily"]
        days = [row["day"] for row in rows]
        self.assertEqual(days[0], "2026-08-10")
        self.assertEqual(days[-1], "2026-08-16")
        self.assertEqual(len(days), 7)
        self.assertNotIn("2026-08-07", days)
        self.assertNotIn("2026-08-18", days)

    def test_only_the_days_inside_it_carry_runs(self):
        """The padding is zeroes, not a way to smuggle a neighbour in."""
        counted = {row["day"]: row["runs"] for row in self.charts()["daily"]}
        self.assertEqual(counted["2026-08-10"], 1)
        self.assertEqual(counted["2026-08-12"], 1)
        self.assertEqual(counted["2026-08-16"], 1)
        self.assertEqual(counted["2026-08-11"], 0)
        self.assertEqual(sum(counted.values()), 3)

    def test_the_three_shapes_the_charts_need_are_all_there(self):
        charts = self.charts()
        for key in ("daily", "releases", "pareto"):
            self.assertIn(key, charts)

    def test_a_week_with_no_runs_draws_nothing(self):
        """Four blank plots read as a broken page; the steps table says "no
        runs" in words instead."""
        self.assertIsNone(
            build_weekly._charts(self.payload(), "2026-06-01", "2026-06-07"))

    def test_engineering_runs_stay_out_of_the_weekly_shape(self):
        """Same rule as the station page's All: neither is a line stage, and
        letting them in would move a yield with nothing on the line changing."""
        from factory import stations
        payload = self.payload()
        payload["runs"].append(
            _run("2026-08-12", station=stations.ENGINEERING))
        charts = build_weekly._charts(payload, "2026-08-10", "2026-08-16")
        counted = sum(row["runs"] for row in charts["daily"])
        self.assertEqual(counted, 3)


if __name__ == "__main__":
    unittest.main()


class ExternalYieldWeekTest(unittest.TestCase):
    """A hand-reported figure is carried forward, never backward.

    WST and FT arrive from Sigurd as one number with the day it is about, they
    do not arrive every week — "FT: no new update" is a normal message — and
    that number was once attached to every window the builder ran over, so the
    week of 06-08, before the line existed, published WST 35.3% beside a row of
    dashes.

    Both halves matter and they pull opposite ways. A window after the figure
    should show it, marked, because a dash there reads as "there is no such
    measurement". A window *before* it must not, because that is the original
    defect. So the direction of the gap is the test, and the age of it decides
    how long "last known" survives.
    """

    ENTRY = {"yield": 0.353, "asOf": "2026-08-14",
             "source": "Sigurd", "note": "Wafer sort."}

    def at(self, start, end, entry=None):
        from factory import build_fpy
        return build_fpy._external_in(entry or self.ENTRY, start, end)  # noqa: SLF001

    def test_the_week_it_describes_keeps_the_figure(self):
        got = self.at("2026-08-10", "2026-08-16")
        self.assertEqual(got["yield"], 0.353)
        self.assertEqual(got["state"], "fresh")

    def test_a_later_week_carries_it_and_says_so(self):
        """The point of the change: nobody reported a new one, so the last one
        stands — labelled, dated and aged, not silently."""
        got = self.at("2026-08-17", "2026-08-23")
        self.assertEqual(got["yield"], 0.353)
        self.assertEqual(got["state"], "carried")
        self.assertEqual(got["ageDays"], 9)
        self.assertIn("2026-08-14", got["note"])

    def test_an_earlier_week_never_gets_it(self):
        """The regression this class exists for. August's figure on a June week
        is not a stale reading of that week, it is a number about a week that
        had not happened."""
        got = self.at("2026-06-08", "2026-06-14")
        self.assertIsNone(got["yield"])
        self.assertEqual(got["state"], "ahead")
        self.assertIn("2026-08-14", got["note"])

    def test_carrying_stops_after_three_weeks(self):
        """Marked-but-ancient is the original defect wearing a label: past the
        cap the figure is not shown at all."""
        from factory import build_fpy
        got = self.at("2026-09-14", "2026-09-20")
        self.assertIsNone(got["yield"])
        self.assertEqual(got["state"], "stale")
        self.assertGreater(got["ageDays"], build_fpy.CARRY_DAYS)

    def test_the_cap_is_the_boundary_it_claims(self):
        """One day inside carries, one day outside does not — checked at the
        edge rather than trusting the comparison."""
        from datetime import date, timedelta
        from factory import build_fpy

        as_of = date(2026, 8, 14)
        inside = as_of + timedelta(days=build_fpy.CARRY_DAYS)
        outside = as_of + timedelta(days=build_fpy.CARRY_DAYS + 1)
        self.assertEqual(
            self.at(inside.isoformat(), inside.isoformat())["state"], "carried")
        self.assertEqual(
            self.at(outside.isoformat(), outside.isoformat())["state"], "stale")

    def test_an_already_absent_figure_stays_absent(self):
        blank = {"yield": None, "asOf": None, "source": "not reported",
                 "note": "Wafer sort."}
        got = self.at("2026-06-08", "2026-06-14", entry=blank)
        self.assertIsNone(got["yield"])
        self.assertEqual(got["state"], "absent")

    def test_an_undated_figure_is_not_shown(self):
        """Without a date there is no way to say which window it belongs to,
        and every window would claim it."""
        got = self.at("2026-08-10", "2026-08-16",
                      entry={"yield": 0.5, "asOf": None, "source": "x",
                             "note": "y"})
        self.assertIsNone(got["yield"])
        self.assertEqual(got["state"], "absent")


class WeekIsSevenDaysTest(unittest.TestCase):
    """Monday to Sunday, including the ones nothing ran on.

    The chart drew five bars for a seven-day week because the weekend had no
    runs and the aggregation only emits days it saw. Five bars is a chart of
    the working week, and it made two weeks incomparable at a glance.
    """

    def rows(self):
        return [{"day": "2026-08-10", "runs": 3, "pass": 3, "fail": 0,
                 "abort": 0, "graded": 3, "fpyPass": 3, "fpyTotal": 3,
                 "fpy": 1.0, "thin": True, "units": 3, "perUnit": True}]

    def test_a_full_week_is_seven_columns(self):
        got = build_weekly._every_day(self.rows(), "2026-08-10", "2026-08-16", True)
        self.assertEqual(len(got), 7)
        self.assertEqual(got[0]["day"], "2026-08-10")
        self.assertEqual(got[-1]["day"], "2026-08-16")

    def test_a_padded_day_is_a_real_zero_not_a_zero_yield(self):
        """No first attempts is not a yield of nought — the trend line skips
        the day instead of diving to the floor and back."""
        got = build_weekly._every_day(self.rows(), "2026-08-10", "2026-08-16", True)
        weekend = [row for row in got if row["day"] == "2026-08-15"][0]
        self.assertEqual(weekend["runs"], 0)
        self.assertIsNone(weekend["fpy"])

    def test_the_running_week_stops_at_today(self):
        """Days that have not happened are not drawn as empty ones."""
        got = build_weekly._every_day(self.rows(), "2026-08-10", "2026-08-12", True)
        self.assertEqual([r["day"] for r in got],
                         ["2026-08-10", "2026-08-11", "2026-08-12"])

    def test_the_days_that_had_runs_are_untouched(self):
        got = build_weekly._every_day(self.rows(), "2026-08-10", "2026-08-16", True)
        self.assertEqual(got[0], self.rows()[0])


class WeekToDateTest(unittest.TestCase):
    """The flow chart counts the week the line is standing in.

    It showed the same trailing seven days the station page does, which on a
    Thursday is half of this week and half of last — so a number quoted on
    Thursday covered days already quoted on Monday under a different heading.
    """

    def payload(self):
        """Built relative to the clock the code reads, not a fixed date.

        This used to pin `today = date(2026, 8, 20)` and place its runs in that
        Thursday's week. Which meant the fixture agreed with the code for
        exactly one calendar week and then went quietly wrong: at 2026-08-24
        00:00 UTC the week under test became last week, every run fell outside
        the window, and two assertions failed on a Monday morning with nothing
        having changed in the code. The boundary is what is being tested, so the
        fixture has to be placed against the same boundary the code computes.
        """
        from datetime import datetime, timedelta, timezone
        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        return {
            "runs": [_run((monday + timedelta(days=d)).strftime("%Y-%m-%d"))
                     for d in range(4)] +
                    [_run((monday - timedelta(days=d)).strftime("%Y-%m-%d"))
                     for d in (1, 2, 3)],
            "source": "pega", "timezone": "UTC",
        }

    def test_the_window_starts_on_monday(self):
        import datetime as dt
        window = build_stations.build_ranged_bundle(self.payload())["windowWeek"]
        monday = dt.datetime.strptime(window["weekOf"], "%Y-%m-%d").date()
        self.assertEqual(monday.weekday(), 0)

    def test_it_carries_a_start_time_and_a_last_counted_time(self):
        """Read at nine on a Thursday, a pair of dates does not say whether
        this morning's units are in the number."""
        window = build_stations.build_ranged_bundle(self.payload())["windowWeek"]
        self.assertTrue(window["startedAt"].startswith(window["weekOf"]))
        self.assertIn("T00:00:00", window["startedAt"])
        self.assertIsNotNone(window["lastRunAt"])
        self.assertGreater(window["lastRunAt"], window["startedAt"])

    def test_last_week_is_not_dragged_in(self):
        """The whole point. The rolling window had three of these."""
        bundle = build_stations.build_ranged_bundle(self.payload())
        week = {s["key"]: s["runs"] for s in bundle["stationsWeek"]}
        every = {s["key"]: s["runs"] for s in bundle["stationsAll"]}
        self.assertEqual(week["__all__"], 4)
        self.assertEqual(every["__all__"], 7)

    def test_the_week_is_the_calendar_week_not_the_last_seven_with_data(self):
        """A Monday with nothing on it is a Monday the line did not run.
        Reaching back into the previous Sunday to fill it would be the rolling
        window again under another name."""
        window = build_stations.build_ranged_bundle(self.payload())["windowWeek"]
        self.assertGreaterEqual(window["from"], window["weekOf"])
