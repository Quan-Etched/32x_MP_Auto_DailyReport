"""The .xlsx reader and the daily tracker bundle.

The fixture is built in memory rather than committed as a binary: a test whose
input you cannot read in the diff is a test nobody can check. It reproduces the
shapes that actually appear in the line's tracker — shared strings, a styled
header, green/red result fills, external hyperlinks, and a cell holding two
test-case names separated by a newline.
"""

import io
import json
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from factory import build_dailyexcel, xlsx

# --------------------------------------------------------------------- fixture

SHARED = [
    "Date", "DUT SN", "ASIC SN", "DUT PN",
    "MLT Results mlt_2026.220", "MLT Failure Test Case mlt_2026.220",
    "FI Test Link", "HTT Results htt_2026.217",
    "HTT Failure Test Case htt_2026.217", "FI Test Link", "Jira",
    "2026-08-12", "268494130000006", "1500027-B", "Passed", "4cb95b11",
    "1af8af3d", "Failed", "SohuVfioPingTestCase\nSohuVrmTestCase",
    "ETCH-38719: SohuVfioPingTestCase, SohuVrmTestCase", "268494130000067",
]
INDEX = {value: position for position, value in enumerate(SHARED)}

#: style index -> fill, matching the roles build_dailyexcel maps.
STYLES = [
    ("FFFFFFFF", 0),   # 0 plain
    ("FF1E3A5F", 1),   # 1 header
    ("FFD1FAE5", 0),   # 2 pass
    ("FFFEE2E2", 0),   # 3 fail
    ("FFFACC15", 0),   # 4 an unmapped colour, on purpose
]


def _cell(ref, value, style=0, kind="s"):
    if value is None:
        return '<c r="%s" s="%d"/>' % (ref, style)
    return '<c r="%s" s="%d" t="%s"><v>%d</v></c>' % (
        ref, style, kind, INDEX[value])


def _sheet(rows_xml, links_xml=""):
    return (
        '<?xml version="1.0"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<cols><col min="2" max="2" width="18.13"/></cols>'
        "<sheetData>%s</sheetData>%s</worksheet>" % (rows_xml, links_xml)
    )


def workbook_bytes(tab_names=("08-12  51x", "Sohu MLTHTT Tracker")):
    header = "".join(
        _cell("%s1" % chr(65 + i), SHARED[i], style=1) for i in range(11))
    row2 = "".join([
        _cell("A2", "2026-08-12"), _cell("B2", "268494130000006"),
        _cell("C2", None), _cell("D2", "1500027-B"),
        _cell("E2", "Passed", style=2), _cell("F2", None),
        _cell("G2", "4cb95b11"), _cell("H2", "Passed", style=2),
        _cell("I2", None), _cell("J2", "1af8af3d"), _cell("K2", None),
    ])
    row3 = "".join([
        _cell("A3", "2026-08-12"), _cell("B3", "268494130000067"),
        _cell("C3", None), _cell("D3", "1500027-B"),
        _cell("E3", "Failed", style=3),
        _cell("F3", "SohuVfioPingTestCase\nSohuVrmTestCase", style=4),
        _cell("G3", "4cb95b11"), _cell("H3", None), _cell("I3", None),
        _cell("J3", None),
        _cell("K3", "ETCH-38719: SohuVfioPingTestCase, SohuVrmTestCase"),
    ])
    links = ('<hyperlinks><hyperlink ref="G2" r:id="rl1"/>'
             '<hyperlink ref="J2" r:id="rl2"/></hyperlinks>')
    sheet1 = _sheet(
        '<row r="1">%s</row><row r="2">%s</row><row r="3">%s</row>'
        '<row r="4"><c r="A4" s="0"/></row>' % (header, row2, row3), links)

    fills = "".join(
        '<fill><patternFill patternType="solid"><fgColor rgb="%s"/>'
        "</patternFill></fill>" % rgb for rgb, _ in STYLES)
    xfs = "".join(
        '<xf fillId="%d" fontId="%d" numFmtId="0"/>' % (i, font)
        for i, (_, font) in enumerate(STYLES))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main" xmlns:r="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships">'
                   "<sheets>" + "".join(
                       '<sheet name="%s" sheetId="%d" r:id="rId%d"/>'
                       % (name, i + 1, i + 1)
                       for i, name in enumerate(tab_names)) +
                   "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships">' + "".join(
                       '<Relationship Id="rId%d" Target="worksheets/sheet%d.xml"/>'
                       % (i + 1, i + 1) for i in range(len(tab_names))) +
                   "</Relationships>")
        z.writestr("xl/sharedStrings.xml",
                   '<sst xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main">' + "".join(
                       "<si><t>%s</t></si>" % value.replace("\n", "&#10;")
                       for value in SHARED) + "</sst>")
        z.writestr("xl/styles.xml",
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main">'
                   "<fonts><font/><font><color rgb=\"FFFFFFFF\"/><b/></font></fonts>"
                   "<fills>%s</fills><cellXfs>%s</cellXfs></styleSheet>"
                   % (fills, xfs))
        z.writestr("xl/worksheets/sheet1.xml", sheet1)
        z.writestr("xl/worksheets/_rels/sheet1.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships">'
                   '<Relationship Id="rl1" Target="http://pega3:3000/suite_run/'
                   'mlt_2026.220.0-gitabc_run_4cb95b11?slot_number=7" '
                   'TargetMode="External"/>'
                   '<Relationship Id="rl2" Target="http://pega3:3000/suite_run/'
                   'htt_2026.217.0-gitdef_run_1af8af3d?slot_number=7" '
                   'TargetMode="External"/></Relationships>')
        for extra in range(2, len(tab_names) + 1):
            z.writestr("xl/worksheets/sheet%d.xml" % extra, _sheet(""))
    return buffer.getvalue()


class TempWorkbook:
    """Writes the fixture to a real file, since Workbook takes a path."""

    def __init__(self, directory, name="tracker.xlsx", **kwargs):
        self.path = Path(directory) / name
        self.path.write_bytes(workbook_bytes(**kwargs))


# ----------------------------------------------------------------- the reader

class XlsxReaderTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = xlsx.Workbook(TempWorkbook(self.tmp.name).path)

    def test_sheet_names_are_in_workbook_order(self):
        self.assertEqual(self.book.sheet_names(),
                         ["08-12  51x", "Sohu MLTHTT Tracker"])

    def test_values_hyperlinks_and_fills_come_through(self):
        sheet = self.book.sheet("08-12  51x")
        header, first = sheet.rows[0], sheet.rows[1]
        self.assertEqual(header[0].value, "Date")
        self.assertEqual(header[0].fill, "FF1E3A5F")
        self.assertTrue(header[0].bold)
        self.assertEqual(first[1].value, "268494130000006")
        self.assertEqual(first[4].fill, "FFD1FAE5")          # Passed
        self.assertIn("suite_run/mlt_", first[6].href)
        self.assertIsNone(first[1].href)

    def test_empty_cells_are_present_so_columns_stay_aligned(self):
        row = self.book.sheet("08-12  51x").rows[1]
        self.assertEqual(row[2].value, "")                   # ASIC SN, blank
        self.assertEqual(row[2].column, "C")

    def test_column_widths_are_read(self):
        self.assertAlmostEqual(
            self.book.sheet("08-12  51x").widths["B"], 18.13, places=2)

    def test_newlines_inside_a_cell_survive(self):
        row = self.book.sheet("08-12  51x").rows[2]
        self.assertEqual(row[5].value,
                         "SohuVfioPingTestCase\nSohuVrmTestCase")

    def test_column_letters_round_trip(self):
        for letters in ("A", "K", "Z", "AA", "AZ", "BA"):
            self.assertEqual(
                xlsx.column_letters(xlsx.column_index(letters)), letters)


# ----------------------------------------------------------------- the bundle

class DailyExcelBundleTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = TempWorkbook(self.tmp.name).path

    def build(self, payload=None):
        return build_dailyexcel.build_bundle(payload or {}, path=self.path)

    def test_only_day_named_tabs_are_published(self):
        bundle = self.build()
        self.assertEqual([tab["name"] for tab in bundle["tabs"]], ["08-12  51x"])
        self.assertEqual(bundle["source"]["tabsInWorkbook"], 2)

    def test_label_and_day_come_from_the_name_and_the_rows(self):
        tab = self.build()["tabs"][0]
        self.assertEqual(tab["label"], "08-12")
        self.assertEqual(tab["day"], "2026-08-12")
        self.assertEqual(tab["claimedUnits"], 51)

    def test_table_is_as_wide_as_its_titled_columns(self):
        tab = self.build()["tabs"][0]
        self.assertEqual(len(tab["columns"]), 11)
        self.assertEqual(tab["columns"][-1]["title"], "Jira")
        for row in tab["rows"]:
            self.assertEqual(len(row), 11)

    def test_trailing_blank_rows_are_dropped(self):
        self.assertEqual(len(self.build()["tabs"][0]["rows"]), 2)

    def test_result_fills_become_roles_not_hex(self):
        rows = self.build()["tabs"][0]["rows"]
        self.assertEqual(rows[0][4]["t"], "pass")
        self.assertEqual(rows[1][4]["t"], "fail")
        self.assertNotIn("t", rows[0][1])            # DUT SN is not a verdict

    def test_pega_links_survive_onto_the_cell(self):
        row = self.build()["tabs"][0]["rows"][0]
        self.assertIn("pega3:3000/suite_run/mlt_", row[6]["h"])
        self.assertIn("pega3:3000/suite_run/htt_", row[9]["h"])

    def test_counts_are_the_sheets_own_verdicts(self):
        counts = self.build()["tabs"][0]["counts"]
        self.assertEqual(counts["E"]["pass"], 1)
        self.assertEqual(counts["E"]["fail"], 1)
        # The failed unit never reached HTT, so its cell is blank, not a fail.
        self.assertEqual(counts["H"]["pass"], 1)
        self.assertEqual(counts["H"]["fail"], 0)
        self.assertEqual(counts["H"]["blank"], 1)

    def test_jira_keys_are_extracted(self):
        row = self.build()["tabs"][0]["rows"][1]
        self.assertEqual(row[10]["j"], ["ETCH-38719"])

    def test_an_unmapped_fill_is_a_warning_not_a_silent_drop(self):
        bundle = self.build()
        self.assertTrue(any("FFFACC15" in w for w in bundle["warnings"]),
                        bundle["warnings"])
        # ...and the cell's text is still published.
        self.assertIn("SohuVfioPingTestCase", bundle["tabs"][0]["rows"][1][5]["v"])

    def test_dut_links_only_where_the_run_table_has_that_serial(self):
        payload = {"runs": [{"dutSerial": "268494130000006"}]}
        rows = self.build(payload)["tabs"][0]["rows"]
        self.assertEqual(rows[0][1]["d"], "268494130000006")
        self.assertNotIn("d", rows[1][1])            # not collected -> no link
        self.assertEqual(self.build(payload)["crossref"],
                         {"matched": 1, "duts": 2, "runsCollectedAt": None})

    def test_no_payload_means_no_dut_links_but_still_a_page(self):
        rows = self.build({})["tabs"][0]["rows"]
        self.assertTrue(all("d" not in row[1] for row in rows))
        self.assertEqual(len(rows), 2)

    def test_bundle_is_json_serialisable(self):
        json.dumps(self.build())

    def test_a_tab_named_for_another_day_is_flagged(self):
        path = Path(self.tmp.name) / "wrong.xlsx"
        path.write_bytes(workbook_bytes(tab_names=("07-04 12x",)))
        bundle = build_dailyexcel.build_bundle({}, path=path)
        self.assertTrue(any("07-04" in w for w in bundle["warnings"]),
                        bundle["warnings"])

    def test_a_workbook_with_no_day_tabs_says_so(self):
        path = Path(self.tmp.name) / "none.xlsx"
        path.write_bytes(workbook_bytes(tab_names=("Notes",)))
        bundle = build_dailyexcel.build_bundle({}, path=path)
        self.assertEqual(bundle["tabs"], [])
        self.assertTrue(any("nothing to publish" in w for w in bundle["warnings"]))

    def test_missing_workbook_raises_something_actionable(self):
        with self.assertRaises(FileNotFoundError) as caught:
            build_dailyexcel.build_bundle({}, path="/nonexistent/tracker.xlsx")
        self.assertIn("tracker.xlsx", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class DerivedTabTest(unittest.TestCase):
    """The EOS fallback: days EOS has that the workbook has not caught up with.

    pega3 is switched off for these. A unit test that reaches the factory
    network passes or fails on where it is run, which is not a property of the
    code — and the pega3 path has its own tests below, against a stub.
    """

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        previous = os.environ.get("FACTORY_PEGA")
        os.environ["FACTORY_PEGA"] = "0"
        self.addCleanup(lambda: os.environ.__setitem__("FACTORY_PEGA", previous)
                        if previous is not None
                        else os.environ.pop("FACTORY_PEGA", None))
        self.path = TempWorkbook(self.tmp.name).path      # its only tab is 08-12

    #: Computed, not hard-coded: a literal epoch is a magic number nobody can
    #: check, and the first draft of it was a day out.
    #: 01:50Z is 18:50 the previous day in the factory zone, which is exactly
    #: the window where the two day boundaries disagree.
    LATER = int(datetime(2026, 8, 13, 1, 50, 38, tzinfo=timezone.utc).timestamp())
    EARLIER = int(datetime(2026, 8, 10, 1, 50, 38, tzinfo=timezone.utc).timestamp())

    def run_at(self, ts, station="mlt", status="fail", tests=None):
        return {
            "runId": "mlt_2026.220.0-gitabc_20260813_015038",
            "dutSerial": "268494130000061", "level": "module",
            "stationKey": station, "version": "2026.220.0-gitabc",
            "startTs": ts, "status": status,
            "tests": tests if tests is not None else [
                {"name": "chip0_boot", "status": "pass",
                 "displayName": "BootloaderResultTestCase"},
                {"name": "chip1_boot", "status": "fail",
                 "displayName": "BootloaderResultTestCase"},
            ],
        }

    def build(self, runs, derive=True):
        return build_dailyexcel.build_bundle(
            {"runs": runs}, path=self.path, derive=derive)

    def test_a_later_day_is_derived(self):
        tabs = self.build([self.run_at(self.LATER)])["tabs"]
        self.assertEqual([t["day"] for t in tabs], ["2026-08-12", "2026-08-13"])
        self.assertTrue(tabs[1]["derived"])
        self.assertFalse(tabs[0].get("derived", False))

    def test_a_day_the_sheet_skipped_is_left_alone(self):
        # Earlier than the newest real tab: the line chose not to track it, and
        # backfilling would compete with its record rather than extend it.
        tabs = self.build([self.run_at(self.EARLIER)])["tabs"]
        self.assertEqual([t["day"] for t in tabs], ["2026-08-12"])

    def test_derive_can_be_switched_off(self):
        tabs = self.build([self.run_at(self.LATER)], derive=False)["tabs"]
        self.assertEqual(len(tabs), 1)

    def test_one_row_per_chip_not_per_run(self):
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        self.assertEqual(len(tab["rows"]), 2)
        self.assertEqual([row[1]["v"] for row in tab["rows"]], ["chip 0", "chip 1"])

    def test_verdicts_are_per_chip_even_though_the_run_failed(self):
        tab = self.build([self.run_at(self.LATER, status="fail")])["tabs"][1]
        self.assertEqual(tab["rows"][0][4], {"v": "Passed", "t": "pass"})
        self.assertEqual(tab["rows"][1][4], {"v": "Failed", "t": "fail"})
        self.assertEqual(tab["rows"][1][5]["v"], "BootloaderResultTestCase")

    def test_the_other_station_columns_stay_blank(self):
        # MLT and HTT are separate fixture runs, so a derived row fills one
        # pair — the same convention the sheet uses when a unit never reached
        # HTT because it failed MLT.
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        for row in tab["rows"]:
            self.assertEqual(row[7], {})           # HTT Results
            self.assertEqual(row[8], {})           # HTT Failure Test Case

    def test_headings_carry_the_versions_actually_seen(self):
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        titles = [c["title"] for c in tab["columns"]]
        # The heading keeps the line's own prefix (mlt_2026.220, not
        # 2026.220) because it is copied from the real tab and only the
        # version token is swapped.
        self.assertEqual(titles[4], "MLT Results mlt_2026.220")
        # Nothing ran for HTT that day, so the heading drops the version
        # instead of inheriting one that never ran.
        self.assertEqual(titles[7], "HTT Results")
        self.assertEqual(len(titles), 11)

    def test_the_link_keeps_the_serial_eos_did_record(self):
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        link = tab["rows"][0][6]
        self.assertEqual(link["d"], "268494130000061")
        self.assertIn("268494130000061", link["title"])

    def test_a_derived_day_uses_the_utc_boundary(self):
        # 2026-08-13T01:50Z is 2026-08-12 18:50 in the factory's zone. The
        # tracker files it under the UTC day, so the derived tab must too or it
        # lands beside the wrong tab.
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        self.assertEqual(tab["day"], "2026-08-13")

    def test_a_run_with_no_chip_tests_contributes_no_rows(self):
        run = self.run_at(self.LATER, tests=[
            {"name": "server_setup", "status": "fail",
             "displayName": "ServerNestedTestCase"}])
        tabs = self.build([run])["tabs"]
        self.assertEqual(tabs[1]["rows"], [])


class PegaTabTest(unittest.TestCase):
    """The good path: a day rebuilt from pega3, which knows every slot's unit.

    Stubbed, not live. The shapes below are the ones the real API returns —
    ``participating`` with one entry per slot, and the run-level
    ``first_failed_test_case`` the tracker copies into its failure column.
    """

    LISTING = [
        {"suite_run_id": "mlt_2026.220.0-gitabc_run_4cb95b11",
         "suite_name": "mlt_2026.220.0-gitabc", "dut_part_number": "1500027-B",
         "asic_lot_code": None, "first_failed_test_case": "BootloaderResultTestCase",
         "second_failed_test_case": None},
        {"suite_run_id": "htt_2026.224.0-gitdef_run_1af8af3d",
         "suite_name": "htt_2026.224.0-gitdef", "dut_part_number": "1500027-B",
         "asic_lot_code": None, "first_failed_test_case": "", "second_failed_test_case": None},
        # Engineering: must not reach the tab.
        {"suite_run_id": "mlt_2026.218.0-gitxyz_validation_run_deadbeef",
         "suite_name": "mlt_2026.218.0-gitxyz_validation", "dut_part_number": "1500027-B",
         "first_failed_test_case": "", "second_failed_test_case": None},
    ]

    DETAIL = {
        "mlt_2026.220.0-gitabc_run_4cb95b11": {"status": "failed", "participating": [
            {"dut_sn": "268494130000045", "slot_number": 0, "status": "Failed"},
            {"dut_sn": "268494130000044", "slot_number": 1, "status": "Passed"}]},
        "htt_2026.224.0-gitdef_run_1af8af3d": {"status": "passed", "participating": [
            {"dut_sn": "268494130000045", "slot_number": 0, "status": "Passed"}]},
        "mlt_2026.218.0-gitxyz_validation_run_deadbeef": {"status": "passed",
            "participating": [{"dut_sn": "999", "slot_number": 0, "status": "Passed"}]},
    }

    def setUp(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, pega, "suite_run", pega.suite_run)
        pega.day_suite_runs = lambda day: list(self.LISTING)
        pega.suite_run = lambda run_id: self.DETAIL[run_id]

    def build(self):
        return build_dailyexcel._pega_tab("2026-08-13", None)

    def test_every_slot_becomes_a_named_unit(self):
        rows = self.build()["rows"]
        self.assertEqual(sorted(row[1]["v"] for row in rows),
                         ["268494130000044", "268494130000045"])

    def test_mlt_and_htt_merge_onto_one_row_per_unit(self):
        # The whole point of having the serial: the sheet's shape is one row
        # per unit with both stations, which per-chip rows cannot express.
        row = next(r for r in self.build()["rows"] if r[1]["v"] == "268494130000045")
        self.assertEqual(row[4], {"v": "Failed", "t": "fail"})     # MLT
        self.assertEqual(row[7], {"v": "Passed", "t": "pass"})     # HTT

    def test_the_failure_case_lands_only_on_the_unit_that_failed(self):
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertEqual(rows["268494130000045"][5]["v"], "BootloaderResultTestCase")
        self.assertEqual(rows["268494130000044"][5], {})

    def test_the_link_is_the_sheets_own_slot_url(self):
        row = next(r for r in self.build()["rows"] if r[1]["v"] == "268494130000044")
        self.assertTrue(row[6]["h"].endswith(
            "/suite_run/mlt_2026.220.0-gitabc_run_4cb95b11?slot_number=1"), row[6]["h"])
        self.assertEqual(row[6]["v"], "4cb95b11")

    def test_part_number_comes_through(self):
        self.assertEqual(self.build()["rows"][0][3]["v"], "1500027-B")

    def test_engineering_runs_are_excluded(self):
        # Same policy as stations.py's _krish exclusions.
        self.assertNotIn("999", [row[1]["v"] for row in self.build()["rows"]])
        self.assertEqual(self.build()["derivedFrom"]["runs"], 2)

    def test_headings_name_the_release_that_ran(self):
        titles = [c["title"] for c in self.build()["columns"]]
        self.assertEqual(titles[4], "MLT Results mlt_2026.220")
        self.assertEqual(titles[7], "HTT Results htt_2026.224")

    def test_passes_sort_before_failures(self):
        rows = self.build()["rows"]
        self.assertEqual(rows[0][1]["v"], "268494130000044")   # all passed
        self.assertEqual(rows[-1][1]["v"], "268494130000045")  # failed MLT

    def test_the_source_is_recorded_so_the_page_can_say_so(self):
        self.assertEqual(self.build()["derivedFrom"]["source"], "pega3")

    def test_an_unreachable_pega_yields_none_rather_than_raising(self):
        from factory import pega
        def boom(day):
            raise pega.PegaUnavailable("no route to host")
        pega.day_suite_runs = boom
        self.assertIsNone(build_dailyexcel._pega_tab("2026-08-13", None))


class PegaCacheTest(unittest.TestCase):
    """The cache is also the transport to a host with no route to pega3.

    The dashboard host's DNS does not know the name, so it can never populate
    this itself; a laptop on the VPN does, and data/raw/pega/ is copied across
    like the CA bundle. That only works if a cache read never depends on the
    network being reachable.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        from factory import pega
        self.pega = pega
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(setattr, pega, "CACHE_DIR", pega.CACHE_DIR)
        self.addCleanup(setattr, pega, "_UNREACHABLE", False)
        pega.CACHE_DIR = Path(tmp.name)
        pega._UNREACHABLE = False

    def test_a_cached_answer_is_served_when_the_host_is_unreachable(self):
        self.pega._write_cache("/api/test_suite_run/x", {"dut_sn": "268494130000045"})
        self.pega._UNREACHABLE = True
        self.assertEqual(self.pega._get("/api/test_suite_run/x", cache=True),
                         {"dut_sn": "268494130000045"})

    def test_an_uncached_path_still_fails_when_unreachable(self):
        self.pega._UNREACHABLE = True
        with self.assertRaises(self.pega.PegaUnavailable):
            self.pega._get("/api/test_suite_run/missing", cache=True)

    def test_a_stale_ok_request_falls_back_to_cache_on_a_network_error(self):
        # The day listing grows while the day runs, so it prefers the network —
        # but a stale copy beats no copy when there is no network at all.
        path = "/api/history/data-analysis/suite-runs?start=x"
        self.pega._write_cache(path, {"suite_runs": [{"suite_run_id": "a"}], "total": 1})
        import os
        previous = os.environ.get("FACTORY_PEGA_URL")
        os.environ["FACTORY_PEGA_URL"] = "http://192.0.2.1:9"   # black-holed
        self.addCleanup(lambda: os.environ.__setitem__("FACTORY_PEGA_URL", previous)
                        if previous is not None
                        else os.environ.pop("FACTORY_PEGA_URL", None))
        self.pega.TIMEOUT = 0.35
        self.addCleanup(setattr, self.pega, "TIMEOUT", 8.0)
        got = self.pega._get(path, cache=True, stale_ok=True)
        self.assertEqual(got["total"], 1)

    def test_a_corrupt_cache_entry_is_discarded_rather_than_raising(self):
        path = "/api/test_suite_run/bad"
        self.pega._cache_path(path).write_text("{not json", encoding="utf-8")
        self.assertIsNone(self.pega._read_cache(path))
        self.assertFalse(self.pega._cache_path(path).exists())
