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

# Column positions by name. The tab gained a per-unit version column after each
# Results column and lost the always-empty ASIC SN, and hand-numbered indices
# are how that becomes a morning of fixing tests that were never about
# numbering.
(DATE, DUT, PN,
 MLT, MLT_VERSION, MLT_FAIL, MLT_LINK,
 HTT, HTT_VERSION, HTT_FAIL, HTT_LINK, JIRA) = range(12)

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

class NoPega:
    """Pin FACTORY_PEGA=0 for a test class.

    A unit test that reaches the factory network passes or fails on where it is
    run, and it is slow: leaving this off made the module take eight seconds of
    real HTTP. The pega3 paths have their own tests, against stubs.
    """

    def _pin_pega_off(self):
        import os
        previous = os.environ.get("FACTORY_PEGA")
        os.environ["FACTORY_PEGA"] = "0"
        self.addCleanup(lambda: os.environ.__setitem__("FACTORY_PEGA", previous)
                        if previous is not None
                        else os.environ.pop("FACTORY_PEGA", None))


class DailyExcelBundleTest(NoPega, unittest.TestCase):
    def setUp(self):
        import tempfile
        self._pin_pega_off()
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
        self.assertEqual(len(tab["columns"]), 12)
        self.assertEqual(tab["columns"][-1]["title"], "Jira")
        for row in tab["rows"]:
            self.assertEqual(len(row), len(tab["columns"]))

    def test_trailing_blank_rows_are_dropped(self):
        self.assertEqual(len(self.build()["tabs"][0]["rows"]), 2)

    def test_result_fills_become_roles_not_hex(self):
        rows = self.build()["tabs"][0]["rows"]
        self.assertEqual(rows[0][MLT]["t"], "pass")
        self.assertEqual(rows[1][MLT]["t"], "fail")
        self.assertNotIn("t", rows[0][DUT])          # DUT SN is not a verdict

    def test_pega_links_survive_onto_the_cell(self):
        row = self.build()["tabs"][0]["rows"][0]
        self.assertIn("pega3:3000/suite_run/mlt_", row[MLT_LINK]["h"])
        self.assertIn("pega3:3000/suite_run/htt_", row[HTT_LINK]["h"])

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
        self.assertEqual(row[JIRA]["j"], ["ETCH-38719"])

    def test_an_unmapped_fill_is_a_warning_not_a_silent_drop(self):
        bundle = self.build()
        self.assertTrue(any("FFFACC15" in w for w in bundle["warnings"]),
                        bundle["warnings"])
        # ...and the cell's text is still published.
        self.assertIn("SohuVfioPingTestCase", bundle["tabs"][0]["rows"][1][MLT_FAIL]["v"])

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


class EmptyColumnTest(unittest.TestCase):
    """A column no tab has ever filled is horizontal space, not information.

    ASIC SN is the case in hand: the sheet carries it and the line has never
    typed in it, so it sat empty between the serial and the part number on
    every published day.
    """

    def tab(self, values, keys=("A", "B", "C")):
        columns = [{"key": key, "title": key, "width": None} for key in keys]
        return {"columns": columns,
                "rows": [[{"v": value} if value else {} for value in row]
                         for row in values]}

    def test_a_column_empty_everywhere_is_dropped(self):
        tabs = [self.tab([["1", "A", ""]]), self.tab([["2", "B", ""]])]
        build_dailyexcel._drop_always_empty(tabs)
        for tab in tabs:
            self.assertEqual([c["key"] for c in tab["columns"]], ["A", "B"])
            self.assertEqual(len(tab["rows"][0]), 2)

    def test_one_filled_cell_anywhere_keeps_it_on_every_tab(self):
        """Judged across the published set, so the tabs keep one shape — a
        table whose columns move when you switch days is a table you re-read."""
        tabs = [self.tab([["1", "A", ""]]), self.tab([["2", "B", "26849410"]])]
        build_dailyexcel._drop_always_empty(tabs)
        for tab in tabs:
            self.assertEqual([c["key"] for c in tab["columns"]], ["A", "B", "C"])

    def test_an_empty_failure_column_stays(self):
        """No failures is the best news the tracker carries; deleting the
        column for being blank would report it as "not tracked"."""
        tabs = [self.tab([["1", "268", "", ""]], keys=("A", "B", "F", "C"))]
        build_dailyexcel._drop_always_empty(tabs)
        self.assertEqual([c["key"] for c in tabs[0]["columns"]], ["A", "B", "F"])

    def test_the_version_column_stays_when_a_station_did_not_run(self):
        tabs = [self.tab([["1", "268", ""]], keys=("A", "B", "Ev"))]
        build_dailyexcel._drop_always_empty(tabs)
        self.assertEqual([c["key"] for c in tabs[0]["columns"]], ["A", "B", "Ev"])


class CandidateDaysTest(unittest.TestCase):
    """Which days the page tries to rebuild.

    It used to be "days EOS has module runs for", and 08-14 never appeared:
    pega3 had 49 units on it and EOS had none, so a day the line had plainly
    worked was missing from a page whose rows come from pega3 anyway.
    """

    def setUp(self):
        import os
        self.previous = os.environ.get("FACTORY_PEGA")
        self.addCleanup(self._restore)

    def _restore(self):
        import os
        if self.previous is None:
            os.environ.pop("FACTORY_PEGA", None)
        else:
            os.environ["FACTORY_PEGA"] = self.previous

    def _set(self, value):
        import os
        os.environ["FACTORY_PEGA"] = value

    def payload(self, days):
        return {"runs": [{"level": "module", "stationKey": "mlt",
                          "startTs": int(datetime(
                              int(day[:4]), int(day[5:7]), int(day[8:]), 12,
                              tzinfo=timezone.utc).timestamp())}
                         for day in days]}

    def test_today_is_a_candidate_even_when_eos_has_nothing(self):
        self._set("1")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertIn(today, build_dailyexcel._candidate_days({"runs": []}))

    def test_eos_days_still_count_when_pega_is_unreachable(self):
        """The fallback path: if pega3 is off, EOS is all there is, and its
        days must still produce tabs."""
        self._set("0")
        days = build_dailyexcel._candidate_days(self.payload(["2026-08-11"]))
        self.assertEqual(days, {"2026-08-11"})

    def test_a_day_only_eos_has_is_not_dropped_when_pega_is_on(self):
        self._set("1")
        days = build_dailyexcel._candidate_days(self.payload(["2026-01-02"]))
        self.assertIn("2026-01-02", days)


if __name__ == "__main__":
    unittest.main()


class DerivedTabTest(NoPega, unittest.TestCase):
    """The EOS fallback: days EOS has that the workbook has not caught up with.

    pega3 is switched off for these. A unit test that reaches the factory
    network passes or fails on where it is run, which is not a property of the
    code — and the pega3 path has its own tests below, against a stub.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._pin_pega_off()
        self.path = TempWorkbook(self.tmp.name).path      # its only tab is 08-12

    #: Computed, not hard-coded: a literal epoch is a magic number nobody can
    #: check, and the first draft of it was a day out.
    #: 01:50Z is 18:50 the previous day in the factory zone, which is exactly
    #: the window where the two day boundaries disagree.
    LATER = int(datetime(2026, 8, 13, 1, 50, 38, tzinfo=timezone.utc).timestamp())
    EARLIER = int(datetime(2026, 8, 10, 1, 50, 38, tzinfo=timezone.utc).timestamp())

    def run_at(self, ts, station="mlt", status="fail", tests=None,
               version="2026.220.0-gitabc"):
        return {
            "runId": "mlt_2026.220.0-gitabc_20260813_015038",
            "dutSerial": "268494130000061", "level": "module",
            "stationKey": station, "version": version,
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

    def test_every_failure_on_the_chip_reaches_the_cell(self):
        # The fallback must say what the controller would; a day built without
        # pega3 losing failures is how 2026-08-14 came out single-named.
        run = self.run_at(self.LATER, tests=[
            {"name": "chip0_alpha", "status": "fail", "displayName": "AlphaTestCase"},
            {"name": "chip0_beta", "status": "fail", "displayName": "BetaTestCase"},
        ])
        tab = self.build([run])["tabs"][1]
        self.assertEqual(tab["rows"][0][MLT_FAIL]["v"], "AlphaTestCase\nBetaTestCase")

    def test_verdicts_are_per_chip_even_though_the_run_failed(self):
        tab = self.build([self.run_at(self.LATER, status="fail")])["tabs"][1]
        self.assertEqual(tab["rows"][0][MLT], {"v": "Passed", "t": "pass"})
        self.assertEqual(tab["rows"][1][MLT], {"v": "Failed", "t": "fail"})
        self.assertEqual(tab["rows"][1][MLT_FAIL]["v"], "BootloaderResultTestCase")

    def test_the_other_station_columns_stay_blank(self):
        # MLT and HTT are separate fixture runs, so a derived row fills one
        # pair — the same convention the sheet uses when a unit never reached
        # HTT because it failed MLT.
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        for row in tab["rows"]:
            self.assertEqual(row[HTT], {})           # HTT Results
            self.assertEqual(row[HTT_FAIL], {})      # HTT Failure Test Case

    def test_headings_carry_the_versions_actually_seen(self):
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        columns = tab["columns"]
        # The build sits on a second line under the heading, keeping the line's
        # own prefix (mlt_2026.220, not 2026.220).
        self.assertEqual(columns[MLT]["title"], "MLT Results")
        self.assertEqual(columns[MLT]["sub"], "mlt_2026.220.0-gitabc")
        # Nothing ran for HTT that day, so the heading drops the version
        # instead of inheriting one that never ran.
        self.assertEqual(columns[HTT]["title"], "HTT Results")
        self.assertIsNone(columns[HTT]["sub"])
        self.assertEqual(len(columns), 12)

    def test_a_mixed_day_counts_the_builds_rather_than_naming_one(self):
        """08-14 ran four MLT builds under one heading, and the heading named
        whichever was most common — which is how one day was reported as both
        24 units and 39."""
        tab = self.build([self.run_at(self.LATER),
                          self.run_at(self.LATER + 60, version="2026.225.0-gitxyz")
                          ])["tabs"][1]
        self.assertEqual(tab["columns"][MLT]["sub"], "2 versions in this column")
        versions = {(row[MLT_VERSION] or {}).get("v") for row in tab["rows"]}
        self.assertEqual(versions, {"mlt_2026.220.0-gitabc", "mlt_2026.225.0-gitxyz"})

    def test_the_link_keeps_the_serial_eos_did_record(self):
        tab = self.build([self.run_at(self.LATER)])["tabs"][1]
        link = tab["rows"][0][MLT_LINK]
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


def _case(run, chip, name, status, start):
    """One pega3 test-case row. test_id carries the chip index, as the API's does."""
    return {"test_id": "%s_chip%d_%s" % (run, chip, name.lower()),
            "test_name": name, "status": status, "start_time": start}


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
        {"suite_run_id": "mlt_2026.218.0-gitxyz_debug_run_deadbeef",
         "suite_name": "mlt_2026.218.0-gitxyz_validation", "dut_part_number": "1500027-B",
         "first_failed_test_case": "", "second_failed_test_case": None},
    ]

    #: test_id carries the chip index, which is how a failure is attributed to a
    #: slot. chip1 fails too, on a unit that passed overall — if that leaked onto
    #: chip0's row the column would name another unit's failure, which is exactly
    #: what the run-level first_failed_test_case used to do.
    MLT = "mlt_2026.220.0-gitabc_run_4cb95b11"
    DETAIL = {
        MLT: {"status": "failed",
              "participating": [
                  {"dut_sn": "268494130000045", "slot_number": 0, "status": "Failed"},
                  {"dut_sn": "268494130000044", "slot_number": 1, "status": "Passed"}],
              "test_cases": [
                  _case(MLT, 0, "SltModuleNestedTestCase", "failed", "01:00"),
                  _case(MLT, 0, "BootloaderResultTestCase", "failed", "01:05"),
                  _case(MLT, 0, "SohuDmaTestCase", "failed", "01:09"),
                  _case(MLT, 1, "SohuVrmTestCase", "failed", "01:02"),
              ]},
        "htt_2026.224.0-gitdef_run_1af8af3d": {"status": "passed", "participating": [
            {"dut_sn": "268494130000045", "slot_number": 0, "status": "Passed"}]},
        "mlt_2026.218.0-gitxyz_debug_run_deadbeef": {"status": "passed",
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

    def at(self, key):
        """Column position by key. build_bundle drops the always-empty ASIC SN
        column across every tab; the raw builder still has it, and hard-coded
        positions turn that into failures about numbering."""
        columns = self.build()["columns"]
        return {column["key"]: position
                for position, column in enumerate(columns)}[key]

    def test_every_slot_becomes_a_named_unit(self):
        rows = self.build()["rows"]
        self.assertEqual(sorted(row[1]["v"] for row in rows),
                         ["268494130000044", "268494130000045"])

    def test_mlt_and_htt_merge_onto_one_row_per_unit(self):
        # The whole point of having the serial: the sheet's shape is one row
        # per unit with both stations, which per-chip rows cannot express.
        row = next(r for r in self.build()["rows"] if r[1]["v"] == "268494130000045")
        self.assertEqual(row[self.at("E")], {"v": "Failed", "t": "fail"})     # MLT
        self.assertEqual(row[self.at("H")], {"v": "Passed", "t": "pass"})     # HTT

    def test_every_failure_on_the_slot_is_named(self):
        # A unit that fails eight tests has eight things wrong with it. The
        # first one to run is rarely the interesting one.
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertEqual(rows["268494130000045"][self.at("F")]["v"].split("\n"),
                         ["BootloaderResultTestCase", "SohuDmaTestCase"])

    def test_another_slot_s_failure_never_leaks_onto_this_unit(self):
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertNotIn("SohuVrmTestCase", rows["268494130000045"][self.at("F")]["v"])

    def test_containers_are_left_out_of_the_list(self):
        # chip0's nest failed only because a leaf under it did, and
        # ServerNestedTestCase would appear twice in one cell.
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertNotIn("SltModuleNestedTestCase", rows["268494130000045"][self.at("F")]["v"])

    def test_a_unit_failing_only_nests_still_gets_a_name(self):
        # An empty cell beside "Failed" is the one thing this column must not say.
        from factory import pega
        run = "mlt_2026.220.0-gitabc_run_nestonly"
        listing = [dict(self.LISTING[0], suite_run_id=run)]
        detail = {run: {"status": "failed",
                        "participating": [{"dut_sn": "268494130000045",
                                           "slot_number": 0, "status": "Failed"}],
                        "test_cases": [_case(run, 0, "SltModuleNestedTestCase",
                                                  "failed", "01:00")]}}
        pega.day_suite_runs = lambda day: listing
        pega.suite_run = lambda run_id: detail[run_id]
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertEqual(rows["268494130000045"][self.at("F")]["v"], "SltModuleNestedTestCase")

    def test_a_passing_unit_gets_no_failure_even_when_its_slot_failed_a_test(self):
        # chip1 has a failing test case but pega3 graded the unit Passed; the
        # verdict is pega3's, and a failure name without a failure is noise.
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertEqual(rows["268494130000044"][self.at("F")], {})

    def test_failures_are_listed_oldest_first(self):
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        names = rows["268494130000045"][self.at("F")]["v"].split("\n")
        self.assertEqual(names[0], "BootloaderResultTestCase")   # 01:05
        self.assertEqual(names[-1], "SohuDmaTestCase")           # 01:09

    def test_the_latest_attempt_wins_when_a_unit_runs_twice(self):
        # Keeping whichever run pega3 returned last made the verdict depend on
        # listing order and disagreed with the line on 9 of 87 units.
        from factory import pega
        late = "mlt_2026.220.0-gitabc_run_99999999"
        listing = list(self.LISTING) + [dict(self.LISTING[0], suite_run_id=late,
                                             start_time="2026-08-13T23:00:00Z")]
        listing[0] = dict(listing[0], start_time="2026-08-13T01:00:00Z")
        detail = dict(self.DETAIL)
        detail[late] = {"status": "passed", "participating": [
            {"dut_sn": "268494130000045", "slot_number": 0, "status": "Passed"}]}
        pega.day_suite_runs = lambda day: listing
        pega.suite_run = lambda run_id: detail[run_id]
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertEqual(rows["268494130000045"][self.at("E")]["v"], "Passed")
        self.assertTrue(rows["268494130000045"][self.at("G")]["h"].endswith(
            "run_99999999?slot_number=0"))

    def test_the_link_is_the_sheets_own_slot_url(self):
        row = next(r for r in self.build()["rows"] if r[1]["v"] == "268494130000044")
        self.assertTrue(row[self.at("G")]["h"].endswith(
            "/suite_run/mlt_2026.220.0-gitabc_run_4cb95b11?slot_number=1"),
            row[self.at("G")]["h"])
        self.assertEqual(row[self.at("G")]["v"], "4cb95b11")

    def test_part_number_comes_through(self):
        self.assertEqual(self.build()["rows"][0][self.at("D")]["v"], "1500027-B")

    def test_engineering_runs_are_excluded(self):
        # Same policy as stations.py's _krish exclusions.
        self.assertNotIn("999", [row[1]["v"] for row in self.build()["rows"]])
        self.assertEqual(self.build()["derivedFrom"]["runs"], 2)

    def test_a_validation_run_is_a_thing_the_line_tested(self):
        """It used to be dropped, but only when the word sat at the end of the
        name: 08-14 lost the two htt validation runs and kept the 24 units of
        mlt_validation 225. The row names its own build now, so the reader
        tells them apart instead of the page deciding."""
        from factory import pega
        run = "htt_2026.224.0-gitdef_validation_run_beef01"
        listing = list(self.LISTING) + [dict(
            self.LISTING[0], suite_run_id=run,
            suite_name="htt_2026.224.0-gitdef_validation",
            start_time="2026-08-13T22:00:00Z")]
        detail = dict(self.DETAIL)
        detail[run] = {"status": "passed", "participating": [
            {"dut_sn": "268494130000044", "slot_number": 3, "status": "Passed"}]}
        pega.day_suite_runs = lambda day: listing
        pega.suite_run = lambda run_id: detail[run_id]
        rows = {r[1]["v"]: r for r in self.build()["rows"]}
        self.assertEqual(rows["268494130000044"][self.at("Hv")]["v"],
                         "htt_2026.224.0-gitdef_validation")

    def test_headings_name_the_release_that_ran(self):
        columns = self.build()["columns"]
        self.assertEqual(columns[self.at("E")]["title"], "MLT Results")
        self.assertEqual(columns[self.at("E")]["sub"], "mlt_2026.220.0-gitabc")
        self.assertEqual(columns[self.at("H")]["sub"], "htt_2026.224.0-gitdef")

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
        self.addCleanup(setattr, pega, "_UNREACHABLE", set())
        pega.CACHE_DIR = Path(tmp.name)
        pega._UNREACHABLE = set()

    def test_a_cached_answer_is_served_when_the_host_is_unreachable(self):
        self.pega._write_cache("/api/test_suite_run/x", {"dut_sn": "268494130000045"})
        # Unreachable is tracked per host now: pega4 being down says nothing
        # about pega3, and a shared flag would stop reading one that answers.
        self.pega._UNREACHABLE = {"default"}
        self.assertEqual(self.pega._get("/api/test_suite_run/x", cache=True),
                         {"dut_sn": "268494130000045"})

    def test_an_uncached_path_still_fails_when_unreachable(self):
        self.pega._UNREACHABLE = {"default"}
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


class EnrichmentTest(unittest.TestCase):
    """Filling the sheet's lossy failure column from pega3.

    The sheet is the line's record and stays so — only the two failure columns
    are touched, and only where pega3 has the unit.
    """

    def setUp(self):
        import tempfile
        from factory import build_dailyexcel as bd
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = TempWorkbook(self.tmp.name).path
        self.addCleanup(setattr, bd, "_pega_units", bd._pega_units)
        # The workbook fixture's failing unit is 268494130000067, whose sheet
        # cell already names two cases.
        bd._pega_units = lambda day: ({
            "268494130000067": {"mlt": {"fail": "SohuVfioPingTestCase\nSohuVrmTestCase\n"
                                                "SohuI2cTestCase"}},
        }, {"mlt": [], "htt": []}, 1)

    def build(self, **kwargs):
        return build_dailyexcel.build_bundle({}, path=self.path, derive=False, **kwargs)

    def tab(self, **kwargs):
        return self.build(**kwargs)["tabs"][0]

    def test_the_failure_column_gains_what_the_sheet_omitted(self):
        rows = self.tab()["rows"]
        cell = rows[1][MLT_FAIL]["v"].split("\n")
        self.assertEqual(cell, ["SohuVfioPingTestCase", "SohuVrmTestCase",
                                "SohuI2cTestCase"])

    def test_the_sheet_s_own_columns_are_untouched(self):
        # Jira is the one thing pega3 does not have; losing it would trade a
        # better failure column for a worse page.
        row = self.tab()["rows"][1]
        self.assertEqual(row[JIRA]["j"], ["ETCH-38719"])
        self.assertEqual(row[MLT], {"v": "Failed", "t": "fail"})
        self.assertEqual(row[DUT]["v"], "268494130000067")

    def test_a_unit_pega3_does_not_have_keeps_the_sheet_s_text(self):
        row = self.tab()["rows"][0]           # 268494130000006, passed
        self.assertEqual(row[MLT_FAIL], {})

    def test_a_name_only_the_sheet_has_is_kept(self):
        from factory import build_dailyexcel as bd
        bd._pega_units = lambda day: ({
            "268494130000067": {"mlt": {"fail": "SohuI2cTestCase"}}}, {}, 1)
        names = self.tab()["rows"][1][MLT_FAIL]["v"].split("\n")
        # pega3's first, then what the person typed that pega3 lacks — a name
        # written down deliberately is evidence even when it is not in the API.
        self.assertEqual(names[0], "SohuI2cTestCase")
        self.assertIn("SohuVfioPingTestCase", names)

    def test_the_tab_records_that_it_was_enriched(self):
        marker = self.tab()["enriched"]
        self.assertEqual(marker["source"], "pega3")
        self.assertEqual(marker["rows"], 1)

    def test_enrichment_can_be_switched_off(self):
        tab = self.tab(enrich=False)
        self.assertNotIn("enriched", tab)
        self.assertEqual(tab["rows"][1][MLT_FAIL]["v"],
                         "SohuVfioPingTestCase\nSohuVrmTestCase")

    def test_an_unreachable_pega_leaves_the_sheet_exactly_as_it_was(self):
        from factory import build_dailyexcel as bd
        bd._pega_units = lambda day: None
        tab = self.tab()
        self.assertNotIn("enriched", tab)
        self.assertEqual(tab["rows"][1][MLT_FAIL]["v"],
                         "SohuVfioPingTestCase\nSohuVrmTestCase")


class MultiHostTest(unittest.TestCase):
    """One client, five controllers.

    pega2 provisions VBB boards, pega3 the module stations, pega4 L10, pega5
    L11. They answer the same paths with different data, so nothing keyed on
    the path alone may be shared between them.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        from factory import pega
        self.pega = pega
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(setattr, pega, "CACHE_DIR", pega.CACHE_DIR)
        self.addCleanup(setattr, pega, "_UNREACHABLE", set())
        pega.CACHE_DIR = Path(tmp.name)
        pega._UNREACHABLE = set()

    def test_a_host_swaps_the_name_in_the_base_url(self):
        self.assertEqual(self.pega.base_url("pega4"), "http://pega4:3000")
        self.assertEqual(self.pega.base_url(), "http://pega3:3000")

    def test_an_override_keeps_working_for_every_host(self):
        import os
        previous = os.environ.get("FACTORY_PEGA_URL")
        os.environ["FACTORY_PEGA_URL"] = "http://10.0.0.5:3100"
        self.addCleanup(lambda: os.environ.__setitem__("FACTORY_PEGA_URL", previous)
                        if previous is not None
                        else os.environ.pop("FACTORY_PEGA_URL", None))
        # The port and scheme survive; only the name is swapped.
        self.assertEqual(self.pega.base_url("pega4"), "http://pega4:3100")

    def test_two_hosts_do_not_share_a_cache_entry(self):
        # The decisive one: the same path on pega3 and pega4 is different data,
        # and one line's runs must never be served to the other.
        path = "/api/test_suite_run/shared_id"
        self.pega._write_cache(path, {"dut_sn": "module"}, host="pega3")
        self.pega._write_cache(path, {"dut_sn": "chassis"}, host="pega4")
        self.assertEqual(self.pega._read_cache(path, "pega3")["dut_sn"], "module")
        self.assertEqual(self.pega._read_cache(path, "pega4")["dut_sn"], "chassis")

    def test_one_unreachable_host_does_not_mute_another(self):
        self.pega._write_cache("/p", {"ok": True}, host="pega4")
        self.pega._UNREACHABLE = {"pega3"}
        # pega4 still answers from its cache rather than inheriting pega3's fate.
        self.assertEqual(self.pega._get("/p", cache=True, host="pega4"), {"ok": True})

    def test_run_url_points_at_the_right_controller(self):
        url = self.pega.run_url("L10_FAT_run_00a5c0b4", 1, host="pega4")
        self.assertTrue(url.startswith("http://pega4:3000/suite_run/"), url)


class StationOfTest(unittest.TestCase):
    """Which module station a pega3 suite belongs to.

    The old test was `run_id.startswith("mlt"/"htt")`. On 2026-08-15 the only
    HTT runs on the line were debug_only_htt_2026.223.0-git78e6956e2, so the
    tab had no HTT column and said nothing about why — the run was not
    classified as engineering and excluded, it was not recognised at all.
    """

    def test_a_plain_suite_resolves(self):
        self.assertEqual(
            build_dailyexcel.station_of("mlt_2026.220.0-gitabc_run_1",
                                        "mlt_2026.220.0-gitabc"), "mlt")
        self.assertEqual(
            build_dailyexcel.station_of("htt_2026.217.0-gitdef_run_1",
                                        "htt_2026.217.0-gitdef"), "htt")

    def test_a_prefixed_suite_still_resolves(self):
        self.assertEqual(
            build_dailyexcel.station_of("debug_only_htt_2026.223.0-gitx_run_1",
                                        "debug_only_htt_2026.223.0-gitx"), "htt")

    def test_something_else_entirely_resolves_to_nothing(self):
        self.assertIsNone(build_dailyexcel.station_of("L10_FAT_run_1", "L10_FAT"))
        self.assertIsNone(build_dailyexcel.station_of("", ""))

    def test_a_leading_debug_counts_as_engineering(self):
        """Recognising the station is only safe if the exclusion also fires —
        otherwise a debug bundle lands in the station's yield."""
        self.assertTrue(build_dailyexcel.ENGINEERING.search(
            "debug_only_htt_2026.223.0-git78e6956e2"))
        self.assertTrue(build_dailyexcel.ENGINEERING.search(
            "mlt_2026.220.0-gitabc_debug"))

    def test_a_production_suite_is_not_engineering(self):
        for name in ("mlt_2026.220.0-git2f1c2f23",
                     "htt_2026.217.0-git3940b759",
                     "mlt_validation_2026.225.0-gitb937ca2c"):
            self.assertIsNone(build_dailyexcel.ENGINEERING.search(name), name)
