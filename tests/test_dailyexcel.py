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
