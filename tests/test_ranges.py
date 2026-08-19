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
        days = [row["day"] for row in self.charts()["daily"]]
        self.assertEqual(days, ["2026-08-10", "2026-08-12", "2026-08-16"])

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
