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
        # min_cohort=1: these cases are about what counts as a first pass, not
        # about the volume floor, which has its own tests below.
        bundle = build_fpy.build_bundle(payload(runs), days=days, min_cohort=1)
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
            run("A", "vbb_provision", "pass", ts(2) + 60)]), min_cohort=1)
        row = bundle["rows"][0]
        self.assertIsNone(row["retestRatio"])
        self.assertIn("sequence", row["retestNote"])


class RolledTest(unittest.TestCase):
    def bundle(self, runs, **kwargs):
        return build_fpy.build_bundle(payload(runs), **kwargs)

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
        """One unit ran at a stage and it failed. Multiplying by its 0%
        reports the whole line at 0% — arithmetically correct, entirely false.

        Uses SLT rather than an L10 stage: L10 and L11 report quantity only by
        policy now, so they can no longer demonstrate the volume floor."""
        bundle = self.bundle(self.many("mlt", 40, 20) +
                             [run("X", "slt", "fail", ts(1))])
        self.assertAlmostEqual(bundle["totals"]["rolledFpy"], 0.5)
        self.assertEqual([e["label"] for e in bundle["totals"]["excludedThin"]],
                         ["SLT"])

    def test_below_the_floor_no_yield_is_published_at_all(self):
        """A 0.0% over two units is not a yield. Printing one invites somebody
        to quote it; the counts beside it say all that can honestly be said."""
        bundle = self.bundle([run("X", "slt", "fail", ts(1)),
                              run("Y", "slt", "pass", ts(1))])
        row = bundle["rows"][0]
        self.assertIsNone(row["fpy"])
        self.assertIsNone(row["finalYield"])
        self.assertFalse(row["readable"])
        self.assertEqual(row["units"], 2)
        self.assertEqual(row["passedUnits"], 1)

    def test_the_thin_stages_are_named_rather_than_dropped(self):
        """That they are too thin to read is the readiness finding; hiding
        them would make the headline look like whole-line coverage."""
        bundle = self.bundle([run("X", "slt", "fail", ts(1))])
        thin = bundle["totals"]["excludedThin"]
        self.assertEqual(thin[0]["units"], 1)
        self.assertIsNone(bundle["totals"]["rolledFpy"])


class ExternalTest(unittest.TestCase):
    def test_reported_stages_carry_their_source_and_date(self):
        """A figure someone typed in and a figure from 279 runs must never be
        indistinguishable on a slide."""
        bundle = build_fpy.build_bundle(payload([run("A", "mlt", "pass", ts(1))]),
                                        min_cohort=1)
        external = {item["key"]: item for item in bundle["external"]}
        self.assertEqual(set(external), {"wst", "ft"})
        for item in external.values():
            self.assertFalse(item["measured"])
            self.assertTrue(item["source"])
            self.assertTrue(item["asOf"])

    def test_measured_rows_say_so(self):
        bundle = build_fpy.build_bundle(payload([run("A", "mlt", "pass", ts(1))]),
                                        min_cohort=1)
        self.assertTrue(bundle["rows"][0]["measured"])


class FailureTest(unittest.TestCase):
    def test_containers_do_not_top_the_failure_list(self):
        bundle = build_fpy.build_bundle(payload([
            run("A", "mlt", "fail", ts(1),
                ["SltModuleNestedTestCase", "SohuPowerVirusTestCase"])]),
            min_cohort=1)
        names = [f["name"] for f in bundle["rows"][0]["topFailures"]]
        self.assertEqual(names, ["SohuPowerVirusTestCase"])

    def test_a_passing_run_contributes_no_failures(self):
        bundle = build_fpy.build_bundle(payload([
            run("A", "mlt", "pass", ts(1), ["SohuPowerVirusTestCase"])]),
            min_cohort=1)
        self.assertEqual(bundle["rows"][0]["topFailures"], [])


class CountsOnlyTest(unittest.TestCase):
    """L10 and L11 publish quantity, never a yield or a retest rate.

    Chassis and rack level, in bring-up, single-digit volumes: a percentage
    over three chassis swings 33 points on one unit, gets quoted anyway, and no
    fix can be judged by it. This is a policy about the stage, not about this
    week's volume — unlike the cohort floor it does not lift when the numbers
    grow.
    """

    def bundle(self, runs):
        return build_fpy.build_bundle(payload(runs), min_cohort=1)

    def many(self, station, count, passing):
        return [run("%s-%d" % (station, i), station,
                    "pass" if i < passing else "fail", ts(2))
                for i in range(count)]

    def rows(self, runs):
        return {row["key"]: row for row in self.bundle(runs)["rows"]}

    def test_no_yield_however_many_units_ran(self):
        rows = self.rows(self.many("l10_fat", 60, 40))
        row = rows["l10_fat"]
        self.assertIsNone(row["fpy"])
        self.assertIsNone(row["finalYield"])
        self.assertIsNone(row["retestRatio"])
        self.assertTrue(row["countsOnly"])

    def test_the_counts_are_still_published(self):
        row = self.rows(self.many("l11_test", 5, 3))["l11_test"]
        self.assertEqual(row["units"], 5)
        self.assertEqual(row["runs"], 5)
        self.assertEqual(row["passedUnits"], 3)

    def test_the_reason_is_on_the_row(self):
        row = self.rows(self.many("l10_2u", 3, 1))["l10_2u"]
        self.assertIn("bring-up", row["retestNote"])

    def test_module_stages_are_untouched(self):
        row = self.rows(self.many("mlt", 40, 20))["mlt"]
        self.assertAlmostEqual(row["fpy"], 0.5)
        self.assertFalse(row["countsOnly"])

    def test_they_are_not_listed_as_too_thin(self):
        """Two different reasons for a blank yield. Reporting L10 as "too few
        units" would suggest volume alone would fix it."""
        totals = self.bundle(self.many("l10_fat", 60, 40))["totals"]
        self.assertEqual(totals["excludedThin"], [])


if __name__ == "__main__":
    unittest.main()


class ExternalYieldTest(unittest.TestCase):
    """WST and FT, which arrive by message and have nowhere else to come from.

    Kept in a data file a human edits on a Saturday rather than in this
    module, so updating them is a change to a number and not a patch to a
    program — and so the figure carries the date and the person who reported
    it instead of a comment nobody re-reads.
    """

    def write(self, tmp, payload):
        import json as _json
        from pathlib import Path
        path = Path(tmp) / "external_yields.json"
        path.write_text(_json.dumps(payload), encoding="utf-8")
        return path

    def using(self, path):
        original = build_fpy.EXTERNAL_FILE
        build_fpy.EXTERNAL_FILE = path
        self.addCleanup(setattr, build_fpy, "EXTERNAL_FILE", original)

    def test_a_reported_figure_is_read_with_its_provenance(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.using(self.write(tmp, {
                "wst": {"yield": 0.41, "asOf": "2026-08-22",
                        "source": "Anne, #production-test-eng"},
                "ft": {"yield": 0.9, "asOf": "2026-08-22", "source": "Anne"}}))
            out = build_fpy.external()
        self.assertEqual(out["wst"]["yield"], 0.41)
        self.assertEqual(out["wst"]["asOf"], "2026-08-22")
        self.assertIn("Anne", out["wst"]["source"])

    def test_a_missing_file_reports_absence_rather_than_a_stale_number(self):
        """A figure nobody sent this week must not be shown as this week's.
        The shape of the page survives; the number does not."""
        from pathlib import Path
        self.using(Path("/nonexistent/external_yields.json"))
        out = build_fpy.external()
        self.assertIsNone(out["wst"]["yield"])
        self.assertIn("external_yields.json", out["wst"]["note"])

    def test_a_half_filled_file_only_loses_the_half_that_is_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.using(self.write(tmp, {
                "wst": {"yield": 0.41, "asOf": "2026-08-22", "source": "Anne"}}))
            out = build_fpy.external()
        self.assertEqual(out["wst"]["yield"], 0.41)
        self.assertIsNone(out["ft"]["yield"])

    def test_malformed_json_does_not_take_the_build_down(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "external_yields.json"
            path.write_text("{ this is not json", encoding="utf-8")
            self.using(path)
            out = build_fpy.external()
        self.assertIsNone(out["ft"]["yield"])
