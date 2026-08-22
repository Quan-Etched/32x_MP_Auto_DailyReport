"""Wrong flow into HTT — and that the day view and the week view agree.

HTT only runs on a module that cleared MLT, so a unit at HTT with no MLT pass
behind it is a routing error worth naming. Two pages report it: the daily tab
(build_dailyexcel.misflow_for) and the weekly rollup (build_weekly._misflow).

They are separate implementations because they are handed different shapes — one
gets a day's joined units, the other a flat run list — and the first time they
were written they disagreed by a factor of three on the same week: 3 against 11
for W33, because the weekly version asked "did this unit ever pass MLT" and so
forgave a unit that passed last week, failed MLT today and went to HTT anyway.

That is what this file is for. Every case is put through both and the answers
have to match.
"""

import unittest

from factory import build_dailyexcel, build_weekly

DAY = "2026-08-20"
EARLIER = "2026-08-19"


def ts(day, hour=12):
    """A timestamp inside a UTC day, since both readers bucket by UTC."""
    from datetime import datetime, timezone

    year, month, date_ = (int(part) for part in day.split("-"))
    return int(datetime(year, month, date_, hour, tzinfo=timezone.utc).timestamp())


class Case:
    """One unit's runs, expressed once and handed to both implementations."""

    def __init__(self, dut, expect, mlt_today=None, htt_today="pass",
                 mlt_earlier=None):
        self.dut = dut
        self.expect = expect              # None, 'failed' or 'unproven'
        self.mlt_today = mlt_today        # 'pass' | 'fail' | None
        self.htt_today = htt_today
        self.mlt_earlier = mlt_earlier    # 'pass' | 'fail' | None

    # -- the day view's shape: units joined per serial, plus prior attempts
    def as_units(self):
        unit = {}
        if self.mlt_today:
            unit["mlt"] = {"status": self.mlt_today, "url": "u", "short": "m1"}
        if self.htt_today:
            unit["htt"] = {"status": self.htt_today, "url": "u", "short": "h1"}
        return unit

    def as_history(self):
        if not self.mlt_earlier:
            return []
        return [{"day": EARLIER, "status": self.mlt_earlier, "url": "u"}]

    # -- the week view's shape: a flat list of runs
    def as_runs(self):
        out = []
        if self.mlt_earlier:
            out.append({"runId": "mlt_x_run_old", "dutSerial": self.dut,
                        "stationKey": "mlt", "status": self.mlt_earlier,
                        "startTs": ts(EARLIER)})
        if self.mlt_today:
            out.append({"runId": "mlt_x_run_m1", "dutSerial": self.dut,
                        "stationKey": "mlt", "status": self.mlt_today,
                        "startTs": ts(DAY, 9)})
        if self.htt_today:
            out.append({"runId": "htt_x_run_h1", "dutSerial": self.dut,
                        "stationKey": "htt", "status": self.htt_today,
                        "startTs": ts(DAY, 15)})
        return out


CASES = [
    Case("1", None, mlt_today="pass"),
    Case("2", "failed", mlt_today="fail"),
    Case("3", None, mlt_today=None, mlt_earlier="pass"),
    Case("4", "unproven", mlt_today=None),
    # The case that broke them apart: an older pass does not excuse today's
    # failure. A unit that just failed MLT should not be at HTT.
    Case("5", "failed", mlt_today="fail", mlt_earlier="pass"),
    Case("6", "unproven", mlt_today=None, mlt_earlier="fail"),
    # No HTT run at all: nothing to be wrong about.
    Case("7", None, mlt_today="fail", htt_today=None),
]


def day_view(cases):
    units = {case.dut: case.as_units() for case in cases}
    history = {"mlt": {case.dut: case.as_history() for case in cases
                       if case.as_history()},
               "htt": {}}
    found = build_dailyexcel.misflow_for(units, history, DAY)
    return {entry["dut"]: entry["kind"] for entry in found}


def week_view(cases):
    runs = []
    for case in cases:
        runs.extend(case.as_runs())
    found = build_weekly._misflow({"runs": runs}, DAY, DAY)   # noqa: SLF001
    return {entry["dut"]: entry["kind"] for entry in found["units"]}


class AgreementTest(unittest.TestCase):
    """The two implementations must classify every case the same way."""

    def test_each_case_lands_where_it_should(self):
        for view, name in ((day_view, "day"), (week_view, "week")):
            got = view(CASES)
            for case in CASES:
                with self.subTest(view=name, dut=case.dut):
                    self.assertEqual(got.get(case.dut), case.expect)

    def test_the_two_views_agree_exactly(self):
        """The assertion the drift would have failed."""
        self.assertEqual(day_view(CASES), week_view(CASES))

    def test_an_older_pass_does_not_excuse_a_failure_today(self):
        """Case 5, called out on its own because it is the one that broke."""
        case = [c for c in CASES if c.dut == "5"]
        self.assertEqual(day_view(case), {"5": "failed"})
        self.assertEqual(week_view(case), {"5": "failed"})

    def test_a_pass_yesterday_and_htt_today_is_not_wrong_flow(self):
        """Case 3 — the ordinary one. 80 of the 92 units that reached HTT
        without an MLT pass on the day since 08-01 are this, and calling them
        wrong flow threw 17 good units out of 08-14's yield."""
        case = [c for c in CASES if c.dut == "3"]
        self.assertEqual(day_view(case), {})
        self.assertEqual(week_view(case), {})


class WeekWindowTest(unittest.TestCase):
    def test_a_run_outside_the_window_is_not_counted(self):
        runs = Case("9", "unproven").as_runs()
        got = build_weekly._misflow({"runs": runs},          # noqa: SLF001
                                    "2026-08-01", "2026-08-02")
        self.assertEqual(got["total"], 0)
        self.assertEqual(got["httGraded"], 0)

    def test_the_denominator_is_the_htt_results_in_the_window(self):
        runs = []
        for case in CASES:
            runs.extend(case.as_runs())
        got = build_weekly._misflow({"runs": runs}, DAY, DAY)  # noqa: SLF001
        self.assertEqual(got["httGraded"],
                         len([c for c in CASES if c.htt_today]))
        self.assertEqual(got["total"], got["failed"] + got["unproven"])


class PopulationTest(unittest.TestCase):
    """The two pages count different populations, and that is on purpose.

    They agree on the rule — AgreementTest asserts that — and still report
    different totals for the same seven days: 11 against 4 for W33. The reason
    is the payload, not the logic. The daily tracker keeps validation and debug
    builds because it answers "what did the line test today"; the weekly page is
    fed by pega_collect, which drops them, because a yield is a claim about
    production. Of the 22 wrong-flow units since 2026-08-03, exactly 11 were on
    a validation or debug build.

    Asserted here so that the day somebody 'fixes' the gap, this says why it is
    there. Both pages carry a note to the same effect.
    """

    def test_the_collector_excludes_validation_and_debug(self):
        from factory import pega_collect

        for suite in ("htt_validation_2026.226.0-gitfe7ab71c",
                      "debug_only_htt_2026.223.0-git78e6956e2",
                      "mlt_2026.225.0-gitb937ca2c_validation"):
            with self.subTest(suite=suite):
                self.assertIsNone(pega_collect.station_of("pega3", suite))

    def test_the_collector_keeps_a_release_build(self):
        from factory import pega_collect

        self.assertEqual(
            pega_collect.station_of("pega3", "htt_2026.226.0-gitfe7ab71c"),
            "htt")

    def test_the_tracker_keeps_validation_builds(self):
        """The other half of the asymmetry: build_dailyexcel's own exclusion
        list deliberately does not match validation."""
        from factory import build_dailyexcel

        self.assertIsNone(
            build_dailyexcel.ENGINEERING.search(
                "htt_validation_2026.226.0-gitfe7ab71c"))


class LinkTest(unittest.TestCase):
    def test_every_entry_carries_the_run_it_is_about(self):
        """The count on the page is an accusation about routing, so it has to be
        followable to a record rather than taken on trust."""
        runs = []
        for case in CASES:
            runs.extend(case.as_runs())
        got = build_weekly._misflow({"runs": runs}, DAY, DAY)  # noqa: SLF001
        for entry in got["units"]:
            with self.subTest(dut=entry["dut"]):
                self.assertTrue(entry["httRun"])
                self.assertIn("day", entry)


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
