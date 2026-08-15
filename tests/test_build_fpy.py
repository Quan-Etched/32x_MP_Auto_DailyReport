"""First-pass yield, step by step.

The numbers on this page get read out at an all-hands, so the properties worth
pinning are the ones that would put a confident wrong figure on a slide: a
retest counted as a first pass, a one-unit stage dragging the whole line to
zero, and a provisioning sequence reported as a 100% retest rate.
"""

import unittest
from datetime import datetime, timedelta, timezone

from factory import build_fpy

DAY = 86400


def ts(days_ago, hour=12):
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return int(moment.replace(hour=hour, minute=0, second=0,
                              microsecond=0).timestamp())


def run(dut, station, status, when, failures=()):
    return {"dutSerial": dut, "stationKey": station, "status": status,
            "startTs": when, "suite": station,
            "failures": [{"display": name, "test": name} for name in failures]}


def payload(runs):
    return {"runs": runs, "dataSource": {"label": "pega2 – pega5"}}


class FirstPassTest(unittest.TestCase):
    def rows(self, runs, days=7):
        bundle = build_fpy.build_bundle(payload(runs), days=days)
        return {row["key"]: row for row in bundle["rows"]}

    def test_a_unit_that_passes_first_time_is_a_first_pass(self):
        rows = self.rows([run("A", "mlt", "pass", ts(1))])
        self.assertEqual(rows["mlt"]["fpy"], 1.0)

    def test_a_unit_that_fails_then_passes_is_not(self):
        """The whole reason FPY is published beside the pass rate: this unit
        makes the run-level rate 50% and the first-pass rate 0%."""
        rows = self.rows([run("A", "mlt", "fail", ts(3)),
                          run("A", "mlt", "pass", ts(2))])
        self.assertEqual(rows["mlt"]["fpy"], 0.0)
        self.assertEqual(rows["mlt"]["finalYield"], 1.0)
        self.assertEqual(rows["mlt"]["retestRatio"], 1.0)

    def test_a_unit_returning_from_before_the_window_is_not_a_first_pass(self):
        """It first ran three weeks ago. Counting today's run as its first
        would report a retest as a fresh unit and inflate the headline."""
        rows = self.rows([run("A", "mlt", "fail", ts(20)),
                          run("A", "mlt", "pass", ts(1))])
        self.assertEqual(rows["mlt"]["newUnits"], 0)
        self.assertIsNone(rows["mlt"]["fpy"])
        self.assertEqual(rows["mlt"]["units"], 1)
        self.assertEqual(rows["mlt"]["finalYield"], 1.0)

    def test_runs_outside_the_window_are_not_counted_in_it(self):
        rows = self.rows([run("A", "mlt", "pass", ts(20)),
                          run("B", "mlt", "pass", ts(1))])
        self.assertEqual(rows["mlt"]["units"], 1)
        self.assertEqual(rows["mlt"]["runs"], 1)


class RetestTest(unittest.TestCase):
    def test_a_provisioning_sequence_is_not_a_retest_rate(self):
        """VBB puts every board through eight suites under one station key.
        Counting units with more than one run called that a 100% retest rate
        for a stage that retests almost nothing."""
        bundle = build_fpy.build_bundle(payload([
            run("A", "vbb_provision", "pass", ts(2)),
            run("A", "vbb_provision", "pass", ts(2) + 60)]))
        row = bundle["rows"][0]
        self.assertIsNone(row["retestRatio"])
        self.assertIn("sequence", row["retestNote"])


class RolledTest(unittest.TestCase):
    def bundle(self, runs):
        return build_fpy.build_bundle(payload(runs))

    def many(self, station, count, passing):
        out = []
        for i in range(count):
            status = "pass" if i < passing else "fail"
            out.append(run("%s-%d" % (station, i), station, status, ts(2)))
        return out

    def test_rolled_is_the_product_of_the_stages_it_names(self):
        bundle = self.bundle(self.many("mlt", 40, 20) + self.many("htt", 40, 30))
        totals = bundle["totals"]
        self.assertAlmostEqual(totals["rolledFpy"], 0.5 * 0.75)
        self.assertEqual(sorted(totals["rolledOver"]), ["HTT", "MLT"])

    def test_a_one_unit_stage_cannot_take_the_line_to_zero(self):
        """L10 SFT ran one unit this week and it failed. Multiplying by its 0%
        reports the whole line at 0% — arithmetically correct, entirely false."""
        bundle = self.bundle(self.many("mlt", 40, 20) +
                             [run("X", "l10_sft", "fail", ts(1))])
        self.assertAlmostEqual(bundle["totals"]["rolledFpy"], 0.5)
        self.assertEqual([e["label"] for e in bundle["totals"]["excludedThin"]],
                         ["L10 SFT"])

    def test_the_thin_stages_are_named_rather_than_dropped(self):
        """That they are too thin to read is the readiness finding; hiding
        them would make the headline look like whole-line coverage."""
        bundle = self.bundle([run("X", "l10_fat", "fail", ts(1))])
        thin = bundle["totals"]["excludedThin"]
        self.assertEqual(thin[0]["units"], 1)
        self.assertIsNone(bundle["totals"]["rolledFpy"])


class ExternalTest(unittest.TestCase):
    def test_reported_stages_carry_their_source_and_date(self):
        """A figure someone typed in and a figure from 279 runs must never be
        indistinguishable on a slide."""
        bundle = build_fpy.build_bundle(payload([run("A", "mlt", "pass", ts(1))]))
        external = {item["key"]: item for item in bundle["external"]}
        self.assertEqual(set(external), {"wst", "ft"})
        for item in external.values():
            self.assertFalse(item["measured"])
            self.assertTrue(item["source"])
            self.assertTrue(item["asOf"])

    def test_measured_rows_say_so(self):
        bundle = build_fpy.build_bundle(payload([run("A", "mlt", "pass", ts(1))]))
        self.assertTrue(bundle["rows"][0]["measured"])


class FailureTest(unittest.TestCase):
    def test_containers_do_not_top_the_failure_list(self):
        bundle = build_fpy.build_bundle(payload([
            run("A", "mlt", "fail", ts(1),
                ["SltModuleNestedTestCase", "SohuPowerVirusTestCase"])]))
        names = [f["name"] for f in bundle["rows"][0]["topFailures"]]
        self.assertEqual(names, ["SohuPowerVirusTestCase"])

    def test_a_passing_run_contributes_no_failures(self):
        bundle = build_fpy.build_bundle(payload([
            run("A", "mlt", "pass", ts(1), ["SohuPowerVirusTestCase"])]))
        self.assertEqual(bundle["rows"][0]["topFailures"], [])


if __name__ == "__main__":
    unittest.main()
