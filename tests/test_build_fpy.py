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


def run(dut, station, status, when, failures=(), version=None):
    return {"dutSerial": dut, "stationKey": station, "status": status,
            "startTs": when, "suite": station,
            # Bonepile recovery asks which release a unit came back on, so a
            # run needs one. Defaulted per station so the cases that do not
            # care about releases read as "one release, throughout".
            "version": version or (station + "_2026.230.0"),
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

    def test_a_station_outside_the_scope_stays_out_however_readable(self):
        """The failure this pins actually happened.

        The rolled figure multiplied every stage with a readable cohort, so the
        week TIM started reporting it silently became TIM x MLT x HTT and W34's
        headline read 19.7% where the line quotes 55.4%. A headline that changes
        meaning because a new station came online is worse than one with a
        stated scope — so the scope is a list, and this is the test that fails
        when something joins it without the pages being re-labelled.
        """
        bundle = self.bundle(self.many("mlt", 40, 20) +
                             self.many("htt", 40, 30) +
                             self.many("tim", 40, 40))
        totals = bundle["totals"]
        self.assertEqual(sorted(totals["rolledOver"]), ["HTT", "MLT"])
        self.assertAlmostEqual(totals["rolledFpy"], 0.5 * 0.75)

        tim = [row for row in bundle["rows"] if row["key"] == "tim"][0]
        self.assertEqual(1.0, tim["fpy"], "TIM is still measured and published")
        self.assertTrue(tim["readable"])
        self.assertNotIn("TIM", [item["label"] for item
                                 in totals["excludedThin"]],
                         "out of scope is not the same as too thin to read")

    def test_l10_and_l11_publish_a_yield_now(self):
        """They used to publish counts and no yield. The line asked for the
        numbers; what makes it safe is that the rolled figure is scoped to
        MLT x HTT, so a two-unit stage can no longer drag the headline."""
        bundle = self.bundle(self.many("mlt", 40, 20) +
                             self.many("l10_fat", 4, 1))
        rows = {row["key"]: row for row in bundle["rows"]}
        fat = rows["l10_fat"]
        self.assertEqual(0.25, fat["fpy"], "the yield must be published")
        self.assertFalse(fat["countsOnly"])
        self.assertTrue(fat["thinCohort"], "and marked as thin")
        self.assertEqual(["MLT"], bundle["totals"]["rolledOver"],
                         "but it stays out of the rolled figure")

    def test_a_thin_yield_is_marked_not_withheld(self):
        bundle = self.bundle(self.many("mlt", 40, 20))
        mlt = [row for row in bundle["rows"] if row["key"] == "mlt"][0]
        self.assertFalse(mlt["thinCohort"], "40 units is not thin")

    def test_bonepile_recovery_splits_by_release(self):
        """Chris Zhu's question, and the split that answers it.

        Recovered on the same release means the first failure did not
        reproduce — a test-escape question. Recovered on a different release
        means a fix released the unit — a schedule item. A single recovery rate
        hides which, and for W34 the answer was mostly the former, so the split
        is the finding rather than a detail.
        """
        runs = [
            # failed, then passed on the same release: did not reproduce
            run("A", "mlt", "fail", ts(3), version="mlt_2026.230.0"),
            run("A", "mlt", "pass", ts(2), version="mlt_2026.230.0"),
            # failed, then passed on a later release: a fix released it
            run("B", "mlt", "fail", ts(3), version="mlt_2026.230.0"),
            run("B", "mlt", "pass", ts(2), version="mlt_2026.231.0"),
            # failed and stayed failed
            run("C", "mlt", "fail", ts(3), version="mlt_2026.230.0"),
            # passed first time: not in the population at all
            run("D", "mlt", "pass", ts(3), version="mlt_2026.230.0"),
        ]
        row = [r for r in self.bundle(runs)["rows"] if r["key"] == "mlt"][0]
        bone = row["bonepile"]
        self.assertEqual(3, bone["firstPassFailed"], "D passed first time")
        self.assertEqual(2, bone["recovered"])
        self.assertAlmostEqual(2 / 3, bone["recoveryRate"])
        self.assertEqual(1, bone["sameRelease"])
        self.assertEqual(1, bone["differentRelease"])
        self.assertEqual(1, bone["stillOut"])

    def test_first_pass_failures_reconcile_with_the_yield(self):
        """The population is the one FPY uses, so the two numbers agree.

        If they used different populations, somebody would put 'FPY 71.2%' and
        'recovery of 100 failures' on one slide out of 350 units and the
        arithmetic would not close.
        """
        bundle = self.bundle(self.many("mlt", 40, 30))
        row = [r for r in bundle["rows"] if r["key"] == "mlt"][0]
        self.assertAlmostEqual(0.75, row["fpy"])
        self.assertEqual(10, row["bonepile"]["firstPassFailed"],
                         "40 units at 75% leaves 10 first-pass failures")

    def test_a_stage_with_no_failures_reports_no_rate(self):
        row = [r for r in self.bundle(self.many("mlt", 20, 20))["rows"]
               if r["key"] == "mlt"][0]
        self.assertEqual(0, row["bonepile"]["firstPassFailed"])
        self.assertIsNone(row["bonepile"]["recoveryRate"],
                          "0/0 is not 0% and must not print as one")

    def test_the_scope_is_the_module_line(self):
        self.assertEqual(("mlt", "htt"), build_fpy.ROLLED_STATIONS)

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

    def test_below_the_floor_the_yield_publishes_but_is_marked(self):
        """It used to be withheld. A 0.0% over two units is still not a yield
        to lean on, but a column of dashes read as "no testing happened", which
        is a worse claim — so the number publishes with its denominator and a
        thin mark, and `readable` stays false so nothing computes with it."""
        bundle = self.bundle([run("X", "slt", "fail", ts(1)),
                              run("Y", "slt", "pass", ts(1))])
        row = bundle["rows"][0]
        self.assertEqual(0.5, row["fpy"])
        self.assertEqual(0.5, row["finalYield"])
        self.assertFalse(row["readable"])
        self.assertTrue(row["thinCohort"])
        self.assertEqual(row["units"], 2)
        self.assertEqual(row["passedUnits"], 1)
        self.assertIsNone(bundle["totals"]["rolledFpy"],
                          "and it is not in the rolled product")

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


class L10L11YieldTest(unittest.TestCase):
    """L10 and L11 publish a yield now. They used to publish counts only.

    The old policy withheld it: chassis and rack level, in bring-up,
    single-digit volumes, and a percentage over three chassis swings 33 points
    on one unit. All still true. What changed is that the line asked for the
    numbers, and that the rolled figure is now scoped to MLT x HTT — so a
    two-unit stage can no longer drag the whole-line headline to zero, which
    was the damage the policy was actually preventing.

    What replaces it is a mark, not a blank: `thinCohort` on any row whose yield
    is over fewer than MIN_COHORT units. The reader sees the number and the
    denominator together and can judge it.
    """

    def bundle(self, runs, **kwargs):
        return build_fpy.build_bundle(payload(runs), **kwargs)

    def many(self, station, count, passing):
        return [run("%s-%d" % (station, i), station,
                    "pass" if i < passing else "fail", ts(2))
                for i in range(count)]

    def rows(self, runs, **kwargs):
        return {row["key"]: row for row in self.bundle(runs, **kwargs)["rows"]}

    def test_a_yield_is_published(self):
        row = self.rows(self.many("l10_fat", 60, 40))["l10_fat"]
        self.assertAlmostEqual(row["fpy"], 40 / 60)
        self.assertAlmostEqual(row["finalYield"], 40 / 60)
        self.assertFalse(row["countsOnly"])

    def test_a_retest_rate_is_published(self):
        """It was withheld under the same policy and for the same reason."""
        row = self.rows(self.many("l10_fat", 60, 40))["l10_fat"]
        self.assertIsNotNone(row["retestRatio"])

    def test_a_small_cohort_is_marked_not_withheld(self):
        rows = self.rows(self.many("l11_test", 5, 3))
        row = rows["l11_test"]
        self.assertAlmostEqual(row["fpy"], 0.6)
        self.assertTrue(row["thinCohort"],
                        "five units is a number, not a yield to lean on")
        self.assertFalse(row["readable"],
                         "and `readable` still says so, for anything that "
                         "computes rather than displays")

    def test_the_counts_are_still_published(self):
        row = self.rows(self.many("l11_test", 5, 3))["l11_test"]
        self.assertEqual(row["units"], 5)
        self.assertEqual(row["runs"], 5)
        self.assertEqual(row["passedUnits"], 3)

    def test_a_big_cohort_is_not_marked(self):
        row = self.rows(self.many("l10_fat", 60, 40))["l10_fat"]
        self.assertFalse(row["thinCohort"])

    def test_module_stages_are_untouched(self):
        row = self.rows(self.many("mlt", 40, 20))["mlt"]
        self.assertAlmostEqual(row["fpy"], 0.5)
        self.assertFalse(row["countsOnly"])

    def test_no_stage_is_counts_only_any_more(self):
        """The prefix list is empty. If something is added back, this says so
        rather than a yield quietly vanishing from a page."""
        self.assertEqual((), build_fpy.COUNTS_ONLY_PREFIXES)
        for key in ("l10_fat", "l11_test", "mlt", "htt", "tim"):
            self.assertFalse(build_fpy.counts_only(key), key)

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
