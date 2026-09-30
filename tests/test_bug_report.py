"""One Jira bug per failing test case, every serial in the body.

The fixture is a tracker tab, the same shape ``daily_report`` tests use.
Filing is exercised with a fake client so the test never talks to Jira.
"""

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from factory import bug_report, cli


def cell(value=None, tone=None, href=None, jira=None):
    out = {}
    if value is not None:
        out["v"] = value
    if tone:
        out["t"] = tone
    if href:
        out["h"] = href
    if jira:
        out["j"] = jira if isinstance(jira, list) else [jira]
    return out


def columns():
    return [
        {"key": "A", "title": "Date"},
        {"key": "B", "title": "SN"},
        {"key": "E", "title": "MLT Results", "station": "mlt",
         "sub": "mlt_2026.257.0-gitabc"},
        {"key": "Ev", "title": "MLT Version", "kind": "version", "station": "mlt"},
        {"key": "F", "title": "MLT Failure Test Case"},
        {"key": "G", "title": "FI Test Link"},
        {"key": "H", "title": "HTT Results", "station": "htt",
         "sub": "htt_2026.246.0-gitabc"},
        {"key": "Hv", "title": "HTT Version", "kind": "version", "station": "htt"},
        {"key": "I", "title": "HTT Failure Test Case"},
        {"key": "J", "title": "FI Test Link"},
        {"key": "K", "title": "Jira"},
    ]


def row(sn, mlt="pass", mlt_case="", htt="pass", htt_case="", jira=None,
        mlt_url="", htt_run=""):
    return [
        cell("2026-09-22"),
        cell(sn),
        cell(mlt.upper(), tone=mlt),
        cell("mlt_2026.257.0-gitabc"),
        cell(mlt_case),
        cell(href=mlt_url) if mlt_url else cell(),
        cell(htt.upper(), tone=htt),
        cell("htt_2026.246.0-gitabc"),
        cell(htt_case),
        cell(htt_run),
        cell(jira, jira=jira) if jira else cell(),
    ]


def bundle(rows):
    return {
        "tabs": [{
            "day": "2026-09-22",
            "columns": columns(),
            "rows": rows,
        }],
        "source": {"url": "https://tracker.example/sheet"},
    }


CASES = ["SohuLaneRepairTestCase", "SohuVminTestCase"]
CATALOGUE = {
    "SohuLaneRepairTestCase": [
        {"code": "TH-HBM-0006", "message": "no passing repair"},
        {"code": "TH-HBM-0008", "message": "sweep did not complete"},
    ],
}


class CollectTest(unittest.TestCase):
    def drafts(self, rows, **kwargs):
        return bug_report.build_drafts(
            bundle(rows), cases=CASES, epic="ETCH-44407",
            by_case=CATALOGUE, **kwargs)

    def test_one_bug_per_case_lists_every_serial(self):
        drafts = self.drafts([
            row("SN-A", mlt="fail", mlt_case="SohuLaneRepairTestCase",
                mlt_url="http://pega3/run/a", jira="ETCH-35587"),
            row("SN-B", htt="fail", htt_case="SohuVminTestCase", htt_run="run-b"),
            row("SN-C", mlt="fail",
                mlt_case="SohuLaneRepairTestCase\nSohuVminTestCase"),
            row("SN-D", mlt="pass", htt="pass"),
            row("SN-E", mlt="fail", mlt_case="SohuLlamaForwardIteratedTestCase"),
        ])
        by_case = {draft["case"]: draft for draft in drafts}
        self.assertEqual(set(by_case), set(CASES))

        lane = by_case["SohuLaneRepairTestCase"]
        self.assertEqual(lane["serials"], ["SN-A", "SN-C"])
        self.assertEqual(lane["epic"], "ETCH-44407")
        self.assertEqual(lane["project"], "ETCH")
        self.assertIn("SN-A", lane["markdown"])
        self.assertIn("SN-C", lane["markdown"])
        self.assertNotIn("SN-B", lane["markdown"])
        self.assertNotIn("SN-E", lane["markdown"])
        self.assertEqual(lane["catalogue"][0]["code"], "TH-HBM-0006")
        self.assertEqual(lane["existingJira"], ["ETCH-35587"])
        lane_csv = bug_report.occurrences_csv(lane)
        self.assertIn("http://pega3/run/a", lane_csv)
        self.assertNotIn("http://pega3/run/a", lane["markdown"])
        self.assertIn("daily/bug-drafts/SohuLaneRepairTestCase-occurrences.csv",
                      lane["markdown"])

        vmin = by_case["SohuVminTestCase"]
        self.assertEqual(vmin["serials"], ["SN-B", "SN-C"])
        self.assertIn("run-b", bug_report.occurrences_csv(vmin))
        self.assertNotIn("run-b", vmin["markdown"])

    def test_a_pass_with_a_stale_case_name_is_not_a_hit(self):
        drafts = self.drafts([
            row("SN-OK", mlt="pass", mlt_case="SohuLaneRepairTestCase",
                htt="fail", htt_case="SohuVminTestCase"),
        ])
        self.assertEqual([draft["case"] for draft in drafts],
                         ["SohuVminTestCase"])
        self.assertEqual(drafts[0]["serials"], ["SN-OK"])

    def test_same_serial_on_two_days_is_listed_once(self):
        first = bundle([
            row("SN-A", mlt="fail", mlt_case="SohuLaneRepairTestCase"),
        ])
        second = bundle([
            row("SN-A", htt="fail", htt_case="SohuLaneRepairTestCase"),
        ])
        second["tabs"][0]["day"] = "2026-09-21"
        merged = {"tabs": first["tabs"] + second["tabs"], "source": first["source"]}
        drafts = bug_report.build_drafts(
            merged, cases=["SohuLaneRepairTestCase"], epic="ETCH-44407",
            by_case={})
        self.assertEqual(drafts[0]["serials"], ["SN-A"])
        self.assertEqual(len(drafts[0]["hits"]), 2)
        table = bug_report.occurrences_csv(drafts[0])
        self.assertIn("2026-09-21", table)
        self.assertIn("2026-09-22", table)
        tail = drafts[0]["markdown"].split("Occurrences", 1)[1]
        self.assertNotIn("SN-A  2026-09-21", tail)
        self.assertIn("occurrences.csv", tail)

    def test_day_window_drops_older_tabs(self):
        data = bundle([
            row("SN-OLD", mlt="fail", mlt_case="SohuVminTestCase"),
        ])
        data["tabs"].append({
            "day": "2026-09-08",
            "columns": columns(),
            "rows": [row("SN-EARLY", mlt="fail", mlt_case="SohuVminTestCase")],
        })
        drafts = bug_report.build_drafts(
            data, cases=["SohuVminTestCase"], epic="ETCH-44407",
            day_from="2026-09-22", by_case={})
        self.assertEqual(drafts[0]["serials"], ["SN-OLD"])

    def test_no_hits_is_an_error(self):
        with self.assertRaises(bug_report.NoHits):
            self.drafts([row("SN-D")])

    def test_parent_is_the_epic_until_a_classic_project_rejects_it(self):
        drafts = self.drafts([
            row("SN-A", mlt="fail", mlt_case="SohuLaneRepairTestCase"),
        ])
        fields = bug_report.issue_fields(drafts[0])
        self.assertEqual(fields["parent"], {"key": "ETCH-44407"})
        self.assertEqual(fields["issuetype"], {"name": "Bug"})
        text = json.dumps(fields["description"])
        self.assertIn("SN-A", text)
        self.assertIn("Expected", text)

        classic = bug_report.issue_fields(drafts[0], epic_field="customfield_10014")
        self.assertNotIn("parent", classic)
        self.assertEqual(classic["customfield_10014"], "ETCH-44407")

        linked = bug_report.apply_occurrences_url(
            drafts[0], "https://drive.google.com/file/d/abc/view")
        linked_text = json.dumps(linked["adf"])
        self.assertIn("https://drive.google.com/file/d/abc/view", linked_text)
        self.assertNotIn("http://pega3/run/a", linked_text)
        self.assertIn("SN-A", linked["markdown"])


class FaJiraTest(unittest.TestCase):
    def test_one_row_files_one_ticket_and_a_second_click_is_the_same_url(self):
        report = {
            "day": "2026-09-24",
            "stage": "fat",
            "rows": [{
                "id": "SN-F|BmcCheck|http://pega4/f|",
                "sn": "SN-F",
                "errorType": "BMC",
                "test": "BmcCheck",
                "code": "NA",
                "url": "http://pega4/f",
                "at": "",
                "jira": "",
            }],
        }

        class Fake:
            def __init__(self):
                self.calls = 0

            def create_bug(self, draft):
                self.calls += 1
                self.draft = draft
                return "ETCH-90100"

        client = Fake()
        filed = bug_report.file_fa_row(
            report, "SN-F|BmcCheck|http://pega4/f|",
            epic="ETCH-44407", client=client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(filed["key"], "ETCH-90100")
        self.assertIn("SN-F", client.draft["summary"])
        self.assertIn("BmcCheck", client.draft["summary"])
        self.assertIn("L10 FAT", client.draft["summary"])
        self.assertEqual(report["rows"][0]["jira"], filed["url"])
        again = bug_report.file_fa_row(
            report, "SN-F|BmcCheck|http://pega4/f|",
            epic="ETCH-44407", client=client)
        self.assertEqual(client.calls, 1)
        self.assertTrue(again["already"])
        self.assertEqual(again["url"], filed["url"])

    def test_a_group_id_files_every_leaf_of_that_error_type(self):
        report = {
            "day": "2026-09-24",
            "stage": "sft",
            "rows": [
                {"sn": "SN-C", "errorType": "Sohu C2C",
                 "test": "C2cLinkupMultiChipTestCase",
                 "url": "http://pega4/c1", "at": "", "code": "TH-C2C-0001",
                 "jira": ""},
                {"sn": "SN-C", "errorType": "Sohu C2C",
                 "test": "C2cPrbsMultiChipTestCase",
                 "url": "http://pega4/c1", "at": "", "code": "NA", "jira": ""},
            ],
        }

        class Fake:
            def create_bug(self, draft):
                self.draft = draft
                return "ETCH-90101"

        client = Fake()
        filed = bug_report.file_fa_row(
            report, "SN-C|hardware|http://pega4/c1",
            epic="ETCH-44407", client=client)
        self.assertEqual(filed["key"], "ETCH-90101")
        self.assertEqual(report["rows"][0]["jira"], filed["url"])
        self.assertEqual(report["rows"][1]["jira"], filed["url"])
        self.assertIn("hardware", client.draft["summary"])
        self.assertIn("Eason Chuang", client.draft["markdown"])

    def test_dri_from_the_request_is_written_on_the_ticket(self):
        report = {
            "day": "2026-09-24",
            "stage": "sft",
            "rows": [{
                "id": "SN-L|SohuLlama70bForwardIteratedTestCase|http://pega4/l|",
                "sn": "SN-L",
                "errorType": "software",
                "test": "SohuLlama70bForwardIteratedTestCase",
                "code": "NA",
                "url": "http://pega4/l",
                "at": "",
                "jira": "",
            }],
        }

        class Fake:
            def create_bug(self, draft):
                self.draft = draft
                return "ETCH-90102"

        client = Fake()
        bug_report.file_fa_row(
            report,
            "SN-L|SohuLlama70bForwardIteratedTestCase|http://pega4/l|",
            epic="ETCH-44407", client=client, dri="Jonathan Wang")
        self.assertIn("Jonathan Wang", client.draft["markdown"])
        self.assertIn("Error type: software", client.draft["markdown"])

    def test_preview_does_not_create_a_ticket(self):
        report = {
            "day": "2026-09-24",
            "stage": "fat",
            "rows": [{
                "sn": "SN-F",
                "errorType": "hardware",
                "test": "BmcCheck",
                "code": "NA",
                "url": "http://pega4/f",
                "at": "",
                "jira": "",
            }],
        }
        preview = bug_report.preview_fa_row(
            report, "SN-F|hardware|http://pega4/f",
            epic="ETCH-44407", dri="Eason Chuang")
        self.assertFalse(preview["already"])
        self.assertIn("SN-F", preview["summary"])
        self.assertIn("BmcCheck", preview["markdown"])
        self.assertIn("Eason Chuang", preview["markdown"])
        self.assertEqual(preview["epic"], "ETCH-44407")
        self.assertFalse(report["rows"][0].get("jira"))

    def test_confirm_uses_the_edited_summary_and_body(self):
        report = {
            "day": "2026-09-24",
            "stage": "fat",
            "rows": [{
                "sn": "SN-F",
                "errorType": "hardware",
                "test": "BmcCheck",
                "code": "NA",
                "url": "http://pega4/f",
                "at": "",
                "jira": "",
            }],
        }

        class Fake:
            def create_bug(self, draft):
                self.draft = draft
                return "ETCH-90103"

        client = Fake()
        bug_report.file_fa_row(
            report, "SN-F|hardware|http://pega4/f",
            epic="ETCH-44407", client=client, dri="Jonathan Wang",
            summary="edited title for SN-F",
            markdown="Operator notes.\n\npega URL: http://pega4/f\n")
        self.assertEqual(client.draft["summary"], "edited title for SN-F")
        self.assertIn("Operator notes.", client.draft["markdown"])
        text = json.dumps(client.draft["adf"])
        self.assertIn("Operator notes.", text)
        self.assertIn("http://pega4/f", text)

    def test_plain_text_turns_urls_into_adf_links(self):
        adf = bug_report.adf_from_plain(
            "See https://jira.example/browse/ETCH-1.\n- first\n- second\n")
        text = json.dumps(adf)
        self.assertIn('"type": "link"', text)
        self.assertIn("https://jira.example/browse/ETCH-1", text)
        self.assertIn("bulletList", text)


class SftJiraTest(unittest.TestCase):
    def test_the_draft_lists_every_case_id(self):
        report = {
            "day": "2026-09-24",
            "kinds": [],
        }
        kind = {"test": "FanTest", "caseIds": ["case-b1", "case-b2"],
                "sns": ["SN-B"]}
        draft = bug_report.sft_draft(report, kind, "ETCH-44407")
        text = json.dumps(draft["adf"])
        self.assertIn("case-b1", text)
        self.assertIn("case-b2", text)
        self.assertIn("SN-B", text)
        self.assertEqual(draft["epic"], "ETCH-44407")
        self.assertNotIn("http://pega4", text)

    def test_kinds_are_filed_by_coverage_stage(self):
        report = {
            "day": "2026-09-24",
            "kinds": [
                {"test": "FanTest", "caseIds": ["fan-1"], "sns": ["SN-B"]},
                {"test": "C2cLinkupMultiChipTestCase",
                 "caseIds": ["c-link"], "sns": ["SN-C"]},
                {"test": "C2cPrbsMultiChipTestCase",
                 "caseIds": ["c-prbs"], "sns": ["SN-C"]},
                {"test": "CheckInterfaceLinkStatus",
                 "caseIds": ["link-1"], "sns": ["SN-D"]},
                {"test": "SohuLlama70bForwardIteratedTestCase",
                 "caseIds": ["llama-1"], "sns": ["SN-E"]},
                {"test": "C2cLinkupTestCase",
                 "caseIds": ["c-alias"], "sns": ["SN-F"]},
            ],
            "rows": [
                {"sn": "SN-C", "c2c": True, "final": "fail",
                 "tests": ["C2cLinkupMultiChipTestCase",
                           "C2cPrbsMultiChipTestCase"],
                 "caseIds": ["c-link", "c-prbs"], "jira": ""},
                {"sn": "SN-B", "c2c": False, "final": "fail",
                 "tests": ["FanTest"], "caseIds": ["fan-1"], "jira": ""},
                {"sn": "SN-D", "c2c": False, "final": "fail",
                 "tests": ["CheckInterfaceLinkStatus"],
                 "caseIds": ["link-1"], "jira": ""},
                {"sn": "SN-E", "c2c": False, "final": "fail",
                 "tests": ["SohuLlama70bForwardIteratedTestCase"],
                 "caseIds": ["llama-1"], "jira": ""},
                {"sn": "SN-F", "c2c": True, "final": "fail",
                 "tests": ["C2cLinkupTestCase"],
                 "caseIds": ["c-alias"], "jira": ""},
            ],
        }

        class Fake:
            def __init__(self):
                self.calls = 0
                self.drafts = []

            def create_bug(self, draft):
                self.calls += 1
                self.drafts.append(draft)
                return "ETCH-900{:02d}".format(self.calls)

        client = Fake()
        filed = bug_report.file_sft_report(report, epic="ETCH-44407",
                                           client=client)
        names = [item["test"] for item in filed]
        self.assertEqual(client.calls, 4)
        self.assertEqual(set(names), {
            "Sohu C2C", "FanTest", "Connectivity",
            "Model Registry & Inference",
        })
        by_name = {item["test"]: item for item in filed}
        self.assertIn("/ETCH-900", by_name["Sohu C2C"]["url"])
        self.assertIn("ETCH-900", report["rows"][0]["jira"])
        self.assertEqual(report["rows"][0]["jira"],
                         report["rows"][4]["jira"])
        self.assertNotEqual(report["rows"][0]["jira"],
                            report["rows"][1]["jira"])
        self.assertNotEqual(report["rows"][0]["jira"],
                            report["rows"][2]["jira"])
        self.assertNotEqual(report["rows"][2]["jira"],
                            report["rows"][3]["jira"])
        c2c = next(draft for draft in client.drafts
                   if draft["case"] == "Sohu C2C")
        text = json.dumps(c2c["adf"])
        self.assertIn("c-link", text)
        self.assertIn("c-prbs", text)
        self.assertIn("c-alias", text)
        self.assertIn("C2cLinkupMultiChipTestCase", text)
        self.assertNotIn("FanTest", text)
        self.assertNotIn("CheckInterfaceLinkStatus", text)


class FileTest(unittest.TestCase):
    def test_classic_epic_link_is_the_retry(self):
        draft = {
            "case": "SohuVminTestCase",
            "epic": "ETCH-44407",
            "project": "ETCH",
            "issueType": "Bug",
            "summary": "SohuVminTestCase failure (1 serial)",
            "adf": {"type": "doc", "version": 1, "content": []},
            "serials": ["SN-B"],
            "hits": [],
        }

        class Fake(bug_report.JiraClient):
            def __init__(self):
                self.calls = []
                self._epic_field = None
                self._epic_field_loaded = False

            def post(self, path, body):
                self.calls.append(body)
                if "parent" in body["fields"]:
                    raise bug_report.JiraError("parent: not on screen", status=400)
                return {"key": "ETCH-90001"}

            def get(self, path):
                return [{"id": "customfield_10014", "name": "Epic Link"}]

        client = Fake()
        filed = bug_report.file_drafts([draft], client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["fields"]["customfield_10014"], "ETCH-44407")
        self.assertEqual(filed[0]["key"], "ETCH-90001")
        self.assertTrue(filed[0]["url"].endswith("/ETCH-90001"))

    def test_cli_prints_drafts_and_does_not_file(self):
        data = bundle([
            row("SN-A", mlt="fail", mlt_case="SohuLaneRepairTestCase"),
            row("SN-B", htt="fail", htt_case="SohuVminTestCase"),
        ])
        drafts = bug_report.build_drafts(
            data, cases=CASES, epic="ETCH-44407", by_case={})
        stdout, stderr = io.StringIO(), io.StringIO()
        with TemporaryDirectory() as directory:
            with mock.patch("factory.bug_report.generate", return_value=drafts), \
                    mock.patch("sys.stdout", stdout), \
                    mock.patch("sys.stderr", stderr):
                code = cli.main([
                    "file-bugs", "--offline", "--epic", "ETCH-44407",
                    "--out", directory,
                    "--case", "SohuLaneRepairTestCase",
                    "--case", "SohuVminTestCase",
                ])
            self.assertEqual(code, 0)
            self.assertTrue((Path(directory) / "SohuLaneRepairTestCase.md").exists())
        text = stdout.getvalue()
        self.assertIn("SN-A", text)
        self.assertIn("SN-B", text)
        self.assertIn("ETCH-44407", text)
        self.assertIn("Draft only", stderr.getvalue())

    def test_cli_offline_without_a_bundle_fails(self):
        # generate(fetch=False) reads the on-disk bundle. Point it at a
        # bundle we pass by patching generate's loader via --offline and an
        # explicit bundle is the unit above; here the CLI path with no
        # tracker should say so rather than file an empty bug.
        stdout, stderr = io.StringIO(), io.StringIO()
        with unittest.mock.patch("sys.stdout", stdout), \
                unittest.mock.patch("sys.stderr", stderr), \
                unittest.mock.patch(
                    "factory.bug_report.generate",
                    side_effect=bug_report.NoHits("no failures")):
            code = cli.main(["file-bugs", "--offline", "--create"])
        self.assertEqual(code, 1)
        self.assertIn("no failures", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
