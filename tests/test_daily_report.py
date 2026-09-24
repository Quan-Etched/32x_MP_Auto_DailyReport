"""Standup markdown from one day's MLT/HTT tracker tab.

The fixture is a tab dict in the shape ``build_dailyexcel`` publishes, not a
workbook: the report reads verdicts, failure names and Jira keys off cells,
and a test that went through the .xlsx parser would be testing that parser.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory import cli, daily_report


MLT = 3
MLT_VER = 4
MLT_FAIL = 5
HTT = 7
HTT_VER = 8
HTT_FAIL = 9
JIRA = 11


def columns():
    return [
        {"key": "A", "title": "Date"},
        {"key": "B", "title": "SN"},
        {"key": "D", "title": "DUT PN"},
        {"key": "E", "title": "MLT Results", "station": "mlt",
         "sub": "mlt_2026.257.0-gitabc"},
        {"key": "Ev", "title": "MLT Version", "kind": "version",
         "station": "mlt"},
        {"key": "F", "title": "MLT Failure Test Case"},
        {"key": "G", "title": "FI Test Link"},
        {"key": "H", "title": "HTT Results", "station": "htt",
         "sub": "htt_2026.257.0-gitabc"},
        {"key": "Hv", "title": "HTT Version", "kind": "version",
         "station": "htt"},
        {"key": "I", "title": "HTT Failure Test Case"},
        {"key": "J", "title": "FI Test Link"},
        {"key": "K", "title": "Jira"},
    ]


def cell(value=None, tone=None, jira=None):
    out = {}
    if value is not None:
        out["v"] = value
    if tone:
        out["t"] = tone
    if jira:
        out["j"] = jira if isinstance(jira, list) else [jira]
    return out


def blank_row(dut, day="2026-09-10"):
    row = [{} for _ in range(12)]
    row[0] = cell(day)
    row[1] = cell(dut)
    row[MLT_VER] = cell("mlt_2026.257.0-gitabc")
    row[HTT_VER] = cell("htt_2026.257.0-gitabc")
    return row


def pass_both(dut):
    row = blank_row(dut)
    row[MLT] = cell("Passed", "pass")
    row[HTT] = cell("Passed", "pass")
    return row


def fail_mlt(dut, case, jira=None, note=None):
    row = blank_row(dut)
    row[MLT] = cell("Failed", "fail")
    row[MLT_FAIL] = cell(case)
    if jira or note:
        row[JIRA] = cell(note or jira, jira=jira)
    return row


def fail_htt(dut, case, jira=None):
    row = blank_row(dut)
    row[MLT] = cell("Passed", "pass")
    row[HTT] = cell("Failed", "fail")
    row[HTT_FAIL] = cell(case)
    if jira:
        row[JIRA] = cell(jira, jira=jira)
    return row


def tab(rows, claimed=None):
    return {
        "name": "09-10 {}x".format(claimed or len(rows)),
        "label": "09-10",
        "day": "2026-09-10",
        "claimedUnits": claimed or len(rows),
        "columns": columns(),
        "rows": rows,
    }


class ExampleReportTest(unittest.TestCase):
    """The shape the floor already pastes: retest of a named failing case."""

    COHORT = "SohuLaneRepairTestCase"
    TRACKER = ("https://docs.google.com/spreadsheets/d/"
               "1Js-kU6CbTjnG0OdFMP1nqzML2gKEA1YVRlXm9ThGS74/edit")

    def setUp(self):
        rows = [pass_both("u{:02d}".format(i)) for i in range(34)]
        rows.append(fail_mlt("lane", self.COHORT, "ETCH-42283",
                             "ETCH-42283: SohuLaneRepairTestCase"))
        rows.append(fail_mlt("tpm", "ProvisionTpmTestCase", "ETCH-43477",
                             "ETCH-43477: ProvisionTpmTestCase"))
        rows.append(fail_mlt("pv1", "SohuPowerVirusThermalTestCase",
                             "ETCH-43506",
                             "ETCH-43506: need to follow up"))
        rows.append(fail_mlt("pv2", "SohuPowerVirusThermalTestCase",
                             "ETCH-43506",
                             "ETCH-43506: need to follow up"))
        rows.append(fail_mlt("ops", "SohuWeightLoadTestCase", "ETCH-43487",
                             "ETCH-43487: Operator issue during MLT"))
        rows.extend(fail_htt("h{}".format(i), "SohuLlamaForwardIteratedTestCase")
                    for i in range(7))
        # 34 pass-both + 5 MLT fail + 7 HTT fail = 46. Pad MLT fails that
        # never reached HTT so MLT is 41 pass / 13 fail, matching the note.
        rows.extend(fail_mlt("m{}".format(i), "SohuVrmTestCase")
                    for i in range(8))
        self.tab = tab(rows, claimed=54)
        self.summary = daily_report.summarize(
            self.tab,
            product="A03 Sohu Module",
            master_jira="ETCH-42215",
            cohort_case=self.COHORT,
            tracker_url=self.TRACKER,
            established={},
            knowledge={},
        )
        self.md = daily_report.render(self.summary)

    def test_title_names_the_retest_cohort(self):
        self.assertIn(
            "A03 Sohu Module Retest 54x SohuLaneRepairTestCase failed unit",
            self.md.splitlines()[0])

    def test_combined_yield_is_units_that_passed_both_stations(self):
        self.assertEqual(self.summary["passedBoth"], 34)
        self.assertIn("34/54 passed MLT/HTT", self.md)

    def test_mlt_counts_and_release(self):
        mlt = self.summary["stations"][0]
        self.assertEqual(mlt["label"], "MLT")
        self.assertEqual(mlt["release"], "257")
        self.assertEqual(mlt["pass"], 41)
        self.assertEqual(mlt["fail"], 13)
        self.assertIn("MLT 257: 41x PASS / 13x FAIL", self.md)

    def test_remaining_original_failure_is_called_out(self):
        self.assertIn(
            "Only 1/54 still failed on SohuLaneRepairTestCase "
            "https://etched-ai.atlassian.net/browse/ETCH-42283",
            self.md)

    def test_a_new_one_off_is_a_new_symptom(self):
        self.assertIn(
            "New symptom ProvisionTpmTestCase failure "
            "https://etched-ai.atlassian.net/browse/ETCH-43477",
            self.md)

    def test_counted_failures_keep_the_note_as_a_suffix(self):
        self.assertIn(
            "2x SohuPowerVirusThermalTestCase need to follow up "
            "https://etched-ai.atlassian.net/browse/ETCH-43506",
            self.md)

    def test_operator_issue_is_the_bullet_not_the_test_case(self):
        self.assertIn(
            "Operator issue during MLT "
            "https://etched-ai.atlassian.net/browse/ETCH-43487",
            self.md)
        self.assertNotIn("SohuWeightLoadTestCase", self.md)

    def test_footer_carries_the_tracker_and_master_ticket(self):
        self.assertIn("Test Tracker: {}".format(self.TRACKER), self.md)
        self.assertIn(
            "Master Jira: https://etched-ai.atlassian.net/browse/ETCH-42215",
            self.md)

    def test_htt_headline(self):
        self.assertIn("HTT 257: 34x PASS / 7x FAIL", self.md)


class DailyTitleTest(unittest.TestCase):
    """Without a cohort case this is just today's tab, not a retest campaign."""

    def test_title_is_the_day_and_failures_are_counts(self):
        rows = [pass_both("ok"), fail_mlt("bad", "SohuVrmTestCase", "ETCH-1")]
        md = daily_report.render(daily_report.summarize(
            tab(rows), product="Sohu Module", established={}, knowledge={}))
        self.assertEqual(md.splitlines()[0], "Sohu Module 09-10 2x")
        self.assertIn("1/2 passed MLT/HTT", md)
        self.assertIn("SohuVrmTestCase", md)
        self.assertNotIn("Retest", md)
        self.assertNotIn("New symptom", md)
        self.assertNotIn("still failed", md)


class ReleaseTokenTest(unittest.TestCase):

    def test_validation_builds_still_name_the_release_number(self):
        self.assertEqual(
            daily_report._release_token("mlt_validation_2026.247.0-gitfeb"),
            "247")

    def test_a_versions_heading_is_not_a_release(self):
        self.assertIsNone(
            daily_report._release_token("3 versions in this column"))

    def test_release_falls_back_to_the_version_column(self):
        rows = [pass_both("ok")]
        built = tab(rows)
        for column in built["columns"]:
            column.pop("kind", None)
            if column.get("station") == "mlt":
                column["sub"] = "3 versions in this column"
        summary = daily_report.summarize(
            built, established={}, knowledge={})
        self.assertEqual(summary["stations"][0]["release"], "257")


class JiraFallbackTest(unittest.TestCase):

    def test_established_ref_fills_in_when_the_sheet_has_no_ticket(self):
        rows = [fail_mlt("a", "PcieSetupTestCase")]
        md = daily_report.render(daily_report.summarize(
            tab(rows),
            established={"PcieSetupTestCase": {"ref": "ETCH-35872"}},
            knowledge={}))
        self.assertIn(
            "https://etched-ai.atlassian.net/browse/ETCH-35872", md)

    def test_the_sheet_ticket_wins_over_the_catalogue(self):
        rows = [fail_mlt("a", "PcieSetupTestCase", "ETCH-99999")]
        md = daily_report.render(daily_report.summarize(
            tab(rows),
            established={"PcieSetupTestCase": {"ref": "ETCH-35872"}},
            knowledge={}))
        self.assertIn("ETCH-99999", md)
        self.assertNotIn("ETCH-35872", md)

    def test_a_failure_with_no_ticket_is_not_given_one(self):
        rows = [fail_mlt("a", "MysteryTestCase")]
        md = daily_report.render(daily_report.summarize(
            tab(rows), established={}, knowledge={}))
        self.assertIn("MysteryTestCase", md)
        self.assertNotIn("atlassian.net", md.split("MysteryTestCase")[1].split("\n")[0])


class PickTabTest(unittest.TestCase):

    def test_newest_day_is_the_default(self):
        older = tab([pass_both("a")])
        older["day"] = "2026-09-09"
        newer = tab([pass_both("b")])
        picked = daily_report.pick_tab({"tabs": [older, newer]})
        self.assertEqual(picked["day"], "2026-09-10")

    def test_an_empty_newest_day_is_skipped(self):
        real = tab([pass_both("a")])
        empty = tab([blank_row("b")])
        empty["day"] = "2026-09-11"
        empty["label"] = "09-11"
        picked = daily_report.pick_tab({"tabs": [real, empty]})
        self.assertEqual(picked["day"], "2026-09-10")

    def test_missing_day_names_what_is_there(self):
        with self.assertRaises(daily_report.NoTab) as caught:
            daily_report.pick_tab({"tabs": [tab([pass_both("a")])]},
                                  day="2026-01-01")
        self.assertIn("2026-09-10", str(caught.exception))

    def test_empty_bundle_is_an_error(self):
        with self.assertRaises(daily_report.NoTab):
            daily_report.pick_tab({"tabs": []})


class RefreshWindowTest(unittest.TestCase):

    def test_lookback_from_today_when_nothing_is_on_disk(self):
        start, today = daily_report.refresh_window(
            tabs=[], today="2026-09-22", lookback=14)
        self.assertEqual(today, "2026-09-22")
        self.assertEqual(start, "2026-09-08")

    def test_the_newest_published_day_is_always_re_fetched(self):
        # A 3-day lookback from 09-22 would start on 09-19 and miss the gap
        # after 09-11. The last published day pulls the window back.
        start, _ = daily_report.refresh_window(
            tabs=[{"day": "2026-09-11"}], today="2026-09-22", lookback=3)
        self.assertEqual(start, "2026-09-11")

    def test_an_older_requested_day_widens_the_window(self):
        start, _ = daily_report.refresh_window(
            day="2026-08-20", tabs=[{"day": "2026-09-11"}],
            today="2026-09-22", lookback=14)
        self.assertEqual(start, "2026-08-20")

    def test_refresh_is_the_default_and_offline_skips_it(self):
        bundle = {"tabs": [tab([pass_both("ok")])], "source": {}}
        with mock.patch.object(daily_report, "refresh",
                               return_value=bundle) as fetched:
            daily_report.generate(fetch=True, product="Sohu Module")
            fetched.assert_called_once()
        with mock.patch.object(daily_report, "refresh") as fetched:
            with mock.patch.object(daily_report, "load_bundle",
                                   return_value=bundle):
                daily_report.generate(fetch=False, product="Sohu Module")
            fetched.assert_not_called()


class WriteTest(unittest.TestCase):

    def test_writes_utf8_markdown(self):
        tmp = Path(tempfile.mkdtemp()) / "out.md"
        daily_report.write("# hello\n", tmp)
        self.assertEqual(tmp.read_text(encoding="utf-8"), "# hello\n")

    def test_default_path_is_the_day_under_daily(self):
        path = daily_report.default_path("2026-09-10", directory=Path("C:/tmp"))
        self.assertEqual(path, Path("C:/tmp") / "2026-09-10.md")


class CliTest(unittest.TestCase):

    def test_stdout_dash_prints_and_writes_nothing(self):
        rows = [pass_both("ok"), fail_mlt("bad", "SohuVrmTestCase")]
        bundle = {
            "tabs": [tab(rows)],
            "source": {"url": "https://example/sheet"},
        }
        buf = io.StringIO()
        with mock.patch.object(daily_report, "load_bundle", return_value=bundle):
            with mock.patch("sys.stdout", buf):
                rc = cli.main(["daily-report", "--offline", "--out", "-",
                               "--product", "Sohu Module"])
        self.assertEqual(rc, 0)
        self.assertIn("Sohu Module 09-10 2x", buf.getvalue())
        self.assertIn("1/2 passed MLT/HTT", buf.getvalue())

    def test_missing_tab_is_exit_1(self):
        err = io.StringIO()
        with mock.patch.object(daily_report, "load_bundle",
                               return_value={"tabs": []}):
            with mock.patch("sys.stderr", err):
                rc = cli.main(["daily-report", "--offline", "--out", "-"])
        self.assertEqual(rc, 1)
        self.assertIn("Cannot write the daily report", err.getvalue())


if __name__ == "__main__":
    unittest.main()
