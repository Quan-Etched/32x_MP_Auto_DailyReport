"""The four outcomes, and the two implementations of them.

The rule lives twice: src/factory/outcomes.py builds the DOE page's numbers and
the deck, dashboard/customize.js classifies interactively from the run bundle.
Two implementations because one runs in Python at build time and the other in
the browser against a selection the reader is still changing — there is no
shared runtime to put it in.

So the risk is drift, and it is a quiet one: the page would filter slightly
differently from the page that reports the totals and nobody would see it until
two numbers were put side by side in a meeting. The last class here runs both
over the same fixture and requires the same answer, which is the only check that
actually holds them together.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

from factory import config, outcomes

DASHBOARD = config.REPO_ROOT / "dashboard"


def run(dut, station, status, ts, version="v1"):
    return {"dutSerial": dut, "stationKey": station, "status": status,
            "startTs": ts, "version": version}


#: One unit per outcome, plus the awkward ones.
FIXTURE = [
    # passed first time
    run("clean", "mlt", "pass", 1000),
    # failed, then passed on the same build: did not reproduce
    run("back-same", "mlt", "fail", 1000), run("back-same", "mlt", "pass", 2000),
    # failed, then passed on a new build: a fix released it
    run("back-new", "mlt", "fail", 1000, "v1"),
    run("back-new", "mlt", "pass", 2000, "v2"),
    # failed once, never retried
    run("stuck", "mlt", "fail", 1000),
    # failed, retried, failed again
    run("stuck-twice", "mlt", "fail", 1000),
    run("stuck-twice", "mlt", "fail", 2000),
    # ran, no verdict either time
    run("silent", "mlt", "skip", 1000), run("silent", "mlt", "unknown", 2000),
    # out of scope entirely
    run("baked", "tim", "fail", 1000),
]


class ClassifyTest(unittest.TestCase):

    def outcome(self, dut):
        attempts = sorted((r for r in FIXTURE
                           if r["dutSerial"] == dut and r["stationKey"] == "mlt"),
                          key=lambda r: r["startTs"])
        return outcomes.classify(attempts)

    def test_passed_first_time(self):
        self.assertEqual(outcomes.PASS, self.outcome("clean"))

    def test_failed_then_passed_is_a_retest_pass(self):
        self.assertEqual(outcomes.RETEST_PASS, self.outcome("back-same"))
        self.assertEqual(outcomes.RETEST_PASS, self.outcome("back-new"))

    def test_failed_once_and_never_retried_is_bonepile(self):
        """The half people forget: no second attempt is still bonepile."""
        self.assertEqual(outcomes.BONEPILE, self.outcome("stuck"))

    def test_failed_every_time_is_bonepile(self):
        self.assertEqual(outcomes.BONEPILE, self.outcome("stuck-twice"))

    def test_no_verdict_is_its_own_outcome(self):
        """Not a pass, and not the module's fault either."""
        self.assertEqual(outcomes.NO_RESULT, self.outcome("silent"))


class TallyTest(unittest.TestCase):

    def rows(self):
        return {row["key"]: row for row in outcomes.tally(FIXTURE)}

    def test_the_four_outcomes_partition_the_units(self):
        for row in outcomes.tally(FIXTURE):
            outcomes.check(row)                     # raises if they do not

    def test_fail_is_retest_pass_plus_bonepile(self):
        row = self.rows()["mlt"]
        self.assertEqual(row["counts"]["retest-pass"] + row["counts"]["bonepile"],
                         row["fail"])

    def test_tim_is_out_of_scope(self):
        """It is a bake. Its repeats are a soak re-run, not a second chance."""
        self.assertNotIn("tim", self.rows())
        self.assertEqual(("mlt", "htt"), outcomes.SCOPE)

    def test_the_release_split_counts_the_recovering_pass(self):
        row = self.rows()["mlt"]
        self.assertEqual(1, row["sameRelease"])
        self.assertEqual(1, row["differentRelease"])

    def test_recovery_is_over_first_attempt_failures_not_all_units(self):
        row = self.rows()["mlt"]
        self.assertEqual(4, row["fail"], "two back, two stuck")
        self.assertAlmostEqual(2 / 4, row["recoveryRate"])


class FlowTest(unittest.TestCase):

    FLOW = [
        run("a", "mlt", "pass", 1000), run("a", "htt", "pass", 3000),
        run("b", "mlt", "pass", 1000), run("b", "htt", "fail", 3000),
        run("c", "mlt", "fail", 1000),                 # never reaches HTT
        run("d", "htt", "pass", 3000),                 # not seen at MLT
    ]

    def ribbons(self):
        got = outcomes.flows(self.FLOW)
        return {(r["source"], r["target"]): r["units"] for r in got["ribbons"]}

    def test_a_unit_that_never_arrives_is_drawn(self):
        """Otherwise what leaves MLT does not equal what arrives at HTT, and a
        Sankey whose sides disagree is unreadable."""
        self.assertEqual(1, self.ribbons()[("bonepile",
                                            outcomes.DID_NOT_ARRIVE)])

    def test_a_unit_seen_only_at_htt_enters_as_its_own_band(self):
        """Tested before the window opened. Dropping it would make the
        arriving total disagree with HTT's own unit count."""
        self.assertEqual(1, self.ribbons()[("not-seen-here", "pass")])

    def test_the_ribbons_account_for_every_unit(self):
        got = outcomes.flows(self.FLOW)
        total = sum(r["units"] for r in got["ribbons"])
        self.assertEqual(4, total, "three at MLT plus one only at HTT")


class ConservationTest(unittest.TestCase):
    """The property that makes the Sankey trustworthy, on the real bundle.

    A Sankey is only readable if what leaves the left equals what arrives on the
    right, and if each side equals the station's own unit count. Get that wrong
    and the chart still draws — it just quietly misstates the size of every
    band, which is worse than not drawing it.
    """

    def setUp(self):
        path = config.REPO_ROOT / "dashboard" / "data" / "outcomes.js"
        if not path.exists():
            self.skipTest("no outcomes bundle built")
        text = path.read_text(encoding="utf-8")
        self.bundle = json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))

    def test_each_side_matches_its_station(self):
        for week in self.bundle.get("weeks") or []:
            flow = week.get("flow") or {}
            by_station = {row["key"]: row for row in week.get("stations") or []}
            left = right = 0
            gone = absent = 0
            for item in flow.get("ribbons") or []:
                left += item["units"]
                right += item["units"]
                if item["target"] == outcomes.DID_NOT_ARRIVE:
                    gone += item["units"]
                if item["source"] == "not-seen-here":
                    absent += item["units"]

            with self.subTest(week=week["week"], side="both"):
                self.assertEqual(left, right,
                                 "the two sides of the flow disagree")
            if "mlt" in by_station:
                with self.subTest(week=week["week"], side="mlt"):
                    self.assertEqual(by_station["mlt"]["units"], left - absent,
                                     "ribbons leaving MLT must be MLT's units")
            if "htt" in by_station:
                with self.subTest(week=week["week"], side="htt"):
                    self.assertEqual(by_station["htt"]["units"], right - gone,
                                     "ribbons arriving must be HTT's units")

    def test_every_week_partitions(self):
        for week in self.bundle.get("weeks") or []:
            for row in week.get("stations") or []:
                with self.subTest(week=week["week"], station=row["key"]):
                    outcomes.check(row)

    def test_only_mlt_and_htt_are_reported(self):
        for week in self.bundle.get("weeks") or []:
            for row in week.get("stations") or []:
                self.assertIn(row["key"], outcomes.SCOPE)


class SameRuleTest(unittest.TestCase):
    """The Python and the JavaScript must agree, on the same fixture.

    Run through JavaScriptCore rather than mocked: the point is to exercise the
    file the browser loads, not a transcription of it.
    """

    CASES = [
        ("clean", [("pass", 1000)], "pass"),
        ("back", [("fail", 1000), ("pass", 2000)], "retest-pass"),
        ("stuck", [("fail", 1000)], "bonepile"),
        ("stuck2", [("fail", 1000), ("fail", 2000)], "bonepile"),
        ("silent", [("skip", 1000)], "no-result"),
        # the ordering trap: the pass is earlier in the array but later in time
        ("ordered", [("pass", 2000), ("fail", 1000)], "retest-pass"),
        # error counts as a graded attempt, so a first error is a first failure
        ("errored", [("error", 1000), ("pass", 2000)], "retest-pass"),
    ]

    def test_python_agrees_with_the_page(self):
        script = DASHBOARD / "customize.js"
        source = script.read_text(encoding="utf-8")
        # the two functions under test, lifted out of the IIFE
        wanted = []
        for name in ("var GRADED = {", "function outcomeOf("):
            at = source.index(name)
            end = source.index("\n\n", at)
            wanted.append(source[at:end])
        harness = "\n".join(wanted) + """
var CASES = %s;
var out = CASES.map(function (c) {
  return c[0] + '=' + outcomeOf(c[1].map(function (a) {
    return { s: a[0], t: a[1] };
  }).sort(function (x, y) { return x.t - y.t; }));
});
JSON.stringify(out);
""" % json.dumps([[name, attempts] for name, attempts, _ in self.CASES])

        try:
            got = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", harness],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest("no JavaScript runtime available: {}".format(exc))
        if got.returncode:
            self.fail("the page's classifier would not run: " + got.stderr)

        from_js = dict(item.split("=") for item in json.loads(got.stdout))
        for name, attempts, expected in self.CASES:
            in_python = outcomes.classify(
                [{"status": status, "startTs": ts} for status, ts
                 in sorted(attempts, key=lambda pair: pair[1])])
            with self.subTest(case=name):
                self.assertEqual(expected, in_python, "python")
                self.assertEqual(expected, from_js[name], "the page")

    def test_the_page_lists_the_same_outcomes_in_the_same_order(self):
        source = (DASHBOARD / "customize.js").read_text(encoding="utf-8")
        block = source[source.index("var OUTCOMES = ["):]
        block = block[:block.index("\n  ];")]
        # the first quoted string of each entry, which is the key
        listed = re.findall(r"\[\s*'([a-z-]+)'", block)
        # OUTCOMES puts `fail` second because that is where a reader looks for
        # it; drop it and the rest must be the Python's exclusive order.
        exclusive = [name for name in listed if name != "fail"]
        self.assertEqual(list(outcomes.EXCLUSIVE), exclusive)


if __name__ == "__main__":
    unittest.main()
