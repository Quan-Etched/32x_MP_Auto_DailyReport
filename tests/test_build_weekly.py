"""The weekly tracker: Monday-anchored windows and the rows behind the numbers.

The window is the thing most likely to go quietly wrong. A rolling seven days
straddles two working weeks, so on a Saturday half of it belongs to the week
being discussed and half to the one before — and two people then compare
different days while believing they compare the same ones.
"""

import unittest
from datetime import date, datetime, timedelta, timezone

from factory import build_weekly


def ts(day, hour=12):
    return int(datetime(day.year, day.month, day.day, hour,
                        tzinfo=timezone.utc).timestamp())


def run(dut, station, status, when, suite="mlt_2026.220.0-gitabc"):
    return {"dutSerial": dut, "stationKey": station, "status": status,
            "startTs": when, "suite": suite,
            "runId": suite + "_run_dead#slot0", "failures": []}


def payload(runs):
    return {"runs": runs, "dataSource": {"label": "pega2 – pega5"}}


class WeekBoundaryTest(unittest.TestCase):
    def test_a_week_starts_on_monday(self):
        for day, monday in ((date(2026, 8, 15), date(2026, 8, 10)),   # Saturday
                            (date(2026, 8, 10), date(2026, 8, 10)),   # Monday
                            (date(2026, 8, 16), date(2026, 8, 10))):  # Sunday
            self.assertEqual(build_weekly.week_start(day), monday)

    def test_the_label_is_the_iso_week(self):
        self.assertEqual(build_weekly.week_label(date(2026, 8, 10)), "2026-W33")


class BundleTest(unittest.TestCase):
    def setUp(self):
        today = datetime.now(timezone.utc).date()
        self.monday = build_weekly.week_start(today)
        self.last_monday = self.monday - timedelta(days=7)

    def bundle(self, runs, weeks=3):
        return build_weekly.build_bundle(payload(runs), weeks=weeks)

    def test_runs_land_in_the_week_they_happened_in(self):
        bundle = self.bundle([run("A", "mlt", "pass", ts(self.monday)),
                              run("B", "mlt", "fail", ts(self.last_monday))])
        weeks = {week["week"]: week for week in bundle["weeks"]}
        this = build_weekly.week_label(self.monday)
        last = build_weekly.week_label(self.last_monday)
        self.assertEqual(weeks[this]["rows"][0]["units"], 1)
        self.assertEqual(weeks[last]["rows"][0]["units"], 1)

    def test_the_current_week_is_marked_as_still_running(self):
        bundle = self.bundle([run("A", "mlt", "pass", ts(self.monday))])
        current = bundle["weeks"][0]
        self.assertTrue(current["partial"])
        self.assertEqual(current["from"], self.monday.strftime("%Y-%m-%d"))

    def test_vbb_provisioning_is_not_a_product_test_step(self):
        """It is a real stage and it is on the station page, but a
        provisioning step sitting between FT and MLT in a yield table invites
        the wrong comparison."""
        bundle = self.bundle([run("A", "vbb_provision", "pass", ts(self.monday)),
                              run("B", "mlt", "pass", ts(self.monday))])
        keys = [row["key"] for row in bundle["weeks"][0]["rows"]]
        self.assertNotIn("vbb_provision", keys)
        self.assertIn("mlt", keys)
        duts = [row["dut"] for row in bundle["weeks"][0]["units"]]
        self.assertEqual(duts, ["B"])


class UnitRowTest(unittest.TestCase):
    def setUp(self):
        today = datetime.now(timezone.utc).date()
        self.monday = build_weekly.week_start(today)

    def rows(self, runs):
        bundle = build_weekly.build_bundle(payload(runs), weeks=1)
        return bundle["weeks"][0]["units"]

    def test_a_row_carries_what_a_reader_needs_to_check_it(self):
        """Serial, release, verdict, and a link to the log. Without those the
        yield above is a number nobody can audit."""
        rows = self.rows([run("268494130000067", "mlt", "fail", ts(self.monday))])
        row = rows[0]
        self.assertEqual(row["dut"], "268494130000067")
        self.assertEqual(row["release"], "mlt_2026.220.0-gitabc")
        self.assertEqual(row["status"], "fail")
        self.assertIn("pega3:3000/suite_run/", row["url"])
        self.assertEqual(row["controller"], "pega3")

    def test_attempts_are_numbered_across_the_history_not_the_week(self):
        earlier = ts(self.monday - timedelta(days=10))
        rows = self.rows([run("A", "mlt", "fail", earlier),
                          run("A", "mlt", "pass", ts(self.monday))])
        self.assertEqual([r["attempt"] for r in rows], [2])

    def test_the_slot_survives_onto_the_link(self):
        entry = run("A", "mlt", "pass", ts(self.monday))
        entry["runId"] = "mlt_2026.220.0-gitabc_run_dead#slot5"
        self.assertIn("slot_number=5", self.rows([entry])[0]["url"])


if __name__ == "__main__":
    unittest.main()
