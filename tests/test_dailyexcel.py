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



class CarriedHistoryTest(unittest.TestCase):
    """A stage the unit did not run today still shows what it did before.

    The case that found this: 268524660000006 passed MLT at 16:58 on 2026-08-20
    and came back for HTT at 00:52 on 08-21. Its 08-21 row therefore had a blank
    MLT cell — correctly, it ran no MLT that day — but no history behind it
    either, so the row could not tell "passed yesterday" from "never ran", and
    it was reported as a missing result. The MLT pass was on the 08-20 tab all
    along; the row people were reading just could not say so.

    History was only attached for stations the unit ran *that day*, which is
    exactly the wrong condition: the blank cell is the one that needs it.
    """

    #: Two stations, the shape the derived tabs use.
    COLUMNS = [{"key": key, "title": title} for key, title in (
        ("A", "Date"), ("B", "SN"), ("D", "DUT PN"),
        ("E", "MLT Results"), ("Ev", "MLT Version"),
        ("F", "MLT Failure Test Case"), ("G", "FI Test Link"),
        ("H", "HTT Results"), ("Hv", "HTT Version"),
        ("I", "HTT Failure Test Case"), ("J", "FI Test Link"),
        ("K", "Jira"))]

    def build(self):
        """One unit, HTT today and MLT yesterday, through the real row builder."""
        import unittest.mock as mock

        units = {"268524660000006": {
            "pn": "1500027-B",
            "htt": {"status": "pass", "fail": "", "short": "b1be42a0",
                    "url": "http://pega3:3000/suite_run/htt_x?slot_number=4",
                    "suite": "htt_2026.226.0-gitfe7ab71c"}}}
        versions = {"mlt": set(), "htt": {"htt_2026.226.0-gitfe7ab71c"}}
        history = {
            "mlt": {"268524660000006": [
                {"day": "2026-08-20", "status": "pass",
                 "url": "http://pega3:3000/suite_run/mlt_x?slot_number=4",
                 "suite": "mlt_2026.231.0-git91a99a1f-tpm-permanent"}]},
            "htt": {},
        }
        with mock.patch.object(build_dailyexcel, "_pega_units",
                               return_value=(units, versions, 1, {}, {})), \
             mock.patch.object(build_dailyexcel, "_seen_before",
                               return_value=history), \
             mock.patch.object(build_dailyexcel, "_derived_columns",
                               return_value=self.COLUMNS):
            return build_dailyexcel._pega_tab("2026-08-21", None)  # noqa: SLF001

    def serial_cell(self):
        tab = self.build()
        keys = [column["key"] for column in tab["columns"]]
        return tab["rows"][0][keys.index("B")], tab, keys

    def test_the_blank_stage_carries_its_history(self):
        cell, _tab, _keys = self.serial_cell()
        self.assertIn("mlt", cell.get("history") or {},
                      "the MLT pass from the day before has to reach the row")
        attempt = cell["history"]["mlt"][0]
        self.assertEqual((attempt["day"], attempt["status"]),
                         ("2026-08-20", "pass"))

    def test_the_stage_it_did_run_is_unaffected(self):
        cell, tab, keys = self.serial_cell()
        self.assertEqual(tab["rows"][0][keys.index("H")]["v"], "Passed")

    def test_the_cell_for_the_stage_it_did_not_run_stays_blank(self):
        """The fix is about history, not about inventing a verdict. A unit that
        ran no MLT today has no MLT result today, and filling one in from
        yesterday would double-count it on two days."""
        _cell, tab, keys = self.serial_cell()
        self.assertEqual(tab["rows"][0][keys.index("E")], {})

    def test_a_unit_the_line_saw_yesterday_is_not_new_input(self):
        cell, _tab, _keys = self.serial_cell()
        self.assertFalse(cell["new"])
        self.assertEqual((cell.get("seen") or {}).get("mlt"), "2026-08-20")

    def test_a_genuinely_first_visit_is_still_new(self):
        import unittest.mock as mock

        units = {"268524660000099": {
            "pn": "1500027-B",
            "mlt": {"status": "pass", "fail": "", "short": "z", "url": "u",
                    "suite": "mlt_2026.231.0"}}}
        with mock.patch.object(build_dailyexcel, "_pega_units",
                               return_value=(units, {"mlt": set(), "htt": set()},
                                             1, {}, {})), \
             mock.patch.object(build_dailyexcel, "_seen_before",
                               return_value={"mlt": {}, "htt": {}}), \
             mock.patch.object(build_dailyexcel, "_derived_columns",
                               return_value=self.COLUMNS):
            tab = build_dailyexcel._pega_tab("2026-08-21", None)  # noqa: SLF001
        keys = [column["key"] for column in tab["columns"]]
        cell = tab["rows"][0][keys.index("B")]
        self.assertTrue(cell["new"])
        self.assertNotIn("history", cell)


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

    def test_a_day_before_the_sheet_begins_is_derived(self):
        """The sheet has no opinion about a day it does not reach.

        This used to be left alone under "only days after the newest real tab",
        which conflated two different things — a hole between two tabs, which
        the line chose, and the days before the first tab, which they simply
        have not covered. The calendar made the difference visible: eight days
        with runs on pega3 sat greyed as though the line had been idle."""
        tabs = self.build([self.run_at(self.EARLIER)])["tabs"]
        self.assertEqual([t["day"] for t in tabs], ["2026-08-10", "2026-08-12"])
        self.assertTrue(tabs[0]["derived"])
        self.assertFalse(tabs[1].get("derived", False))

    def test_a_hole_between_two_real_tabs_is_still_left_alone(self):
        """The half of the old rule that was doing work. A day the line skipped
        between two days it did keep is their decision, and backfilling it would
        compete with their record rather than extend it."""
        derivable = build_dailyexcel._derivable
        self.assertFalse(derivable("2026-08-12", "2026-08-11", "2026-08-14"))
        self.assertTrue(derivable("2026-08-15", "2026-08-11", "2026-08-14"))
        self.assertTrue(derivable("2026-08-05", "2026-08-11", "2026-08-14"))

    def test_nothing_before_the_floor_is_derived(self):
        """Before it there is bring-up, not a line to report on."""
        self.assertFalse(
            build_dailyexcel._derivable("2026-07-31", "2026-08-11", "2026-08-14"))
        self.assertFalse(build_dailyexcel._derivable("2026-07-31", "", ""))

    def test_an_empty_workbook_puts_no_day_out_of_range(self):
        self.assertTrue(build_dailyexcel._derivable("2026-08-05", "", ""))

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
        {"suite_run_id": "mlt_2026.218.0-gitxyz_krish_run_deadbeef",
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
        "mlt_2026.218.0-gitxyz_krish_run_deadbeef": {"status": "passed",
            "participating": [{"dut_sn": "999", "slot_number": 0, "status": "Passed"}]},
    }

    def setUp(self):
        from factory import pega
        self.addCleanup(setattr, pega, "day_suite_runs", pega.day_suite_runs)
        self.addCleanup(setattr, pega, "suite_run", pega.suite_run)
        pega.day_suite_runs = lambda day, host=None: list(self.LISTING)
        pega.suite_run = lambda run_id, host=None: self.DETAIL[run_id]

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
        pega.day_suite_runs = lambda day, host=None: listing
        pega.suite_run = lambda run_id, host=None: detail[run_id]
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
        pega.day_suite_runs = lambda day, host=None: listing
        pega.suite_run = lambda run_id, host=None: detail[run_id]
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
        pega.day_suite_runs = lambda day, host=None: listing
        pega.suite_run = lambda run_id, host=None: detail[run_id]
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
        def boom(day, host=None):
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
        # Unreachable is tracked per host: pega4 being down says nothing about
        # pega3, and a shared flag would stop reading one that answers. The
        # bucket is named by the resolved host — `host=None` resolves to the
        # machine base_url() points at — so the literal "default" would name a
        # bucket nothing is filed under and this would test the network path by
        # accident.
        self.pega._UNREACHABLE = {self.pega._default_host_name()}
        self.assertEqual(self.pega._get("/api/test_suite_run/x", cache=True),
                         {"dut_sn": "268494130000045"})

    def test_an_uncached_path_still_fails_when_unreachable(self):
        self.pega._UNREACHABLE = {self.pega._default_host_name()}
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

    def test_a_debug_bundle_is_counted_and_flagged(self):
        """08-15's only HTT was debug_only_htt_2026.223.0-git78e6956e2, run on
        production DUTs at a production station. Those units were tested, so
        they are on the tab — and the build is recorded, because a day whose
        only HTT was a debug bundle reads differently from a normal one."""
        for name in ("debug_only_htt_2026.223.0-git78e6956e2",
                     "mlt_2026.220.0-gitabc_debug"):
            self.assertIsNone(build_dailyexcel.ENGINEERING.search(name), name)
            self.assertTrue(build_dailyexcel.DEBUG_BUILD.search(name), name)

    def test_what_is_still_not_a_line_unit(self):
        for name in ("L10_6U_FAT_krish", "DRY_RUN_mlt", "mlt_2026.220_SMOKE",
                     "test_htt_thing"):
            self.assertTrue(build_dailyexcel.ENGINEERING.search(name), name)

    def test_a_release_build_is_not_flagged_as_debug(self):
        for name in ("mlt_2026.220.0-git2f1c2f23",
                     "htt_2026.217.0-git3940b759"):
            self.assertIsNone(build_dailyexcel.DEBUG_BUILD.search(name), name)

    def test_a_production_suite_is_not_engineering(self):
        for name in ("mlt_2026.220.0-git2f1c2f23",
                     "htt_2026.217.0-git3940b759",
                     "mlt_validation_2026.225.0-gitb937ca2c"):
            self.assertIsNone(build_dailyexcel.ENGINEERING.search(name), name)


class ReleaseOnlyCountTest(unittest.TestCase):
    """The yield above the table, counted twice.

    Asked directly: "we're sure the data here doesn't have any potential errors
    like accidentally including validation runs?" On 08-14 the MLT tile read
    61.5% counting a validation campaign and 53.3% without it. The tab includes
    those runs on purpose; the tile has to say so and show both.
    """

    def tab(self, rows):
        columns = build_dailyexcel._with_version_columns([
            {"key": "A", "title": "Date"}, {"key": "B", "title": "DUT SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
            {"key": "F", "title": "MLT Failure Test Case"},
            {"key": "G", "title": "FI Test Link"},
            {"key": "H", "title": "HTT Results", "station": "htt"},
            {"key": "I", "title": "HTT Failure"}, {"key": "J", "title": "Link"},
        ])
        index = {c["key"]: i for i, c in enumerate(columns)}
        built = []
        for dut, verdict, build in rows:
            row = [{} for _ in columns]
            row[index["B"]] = {"v": dut}
            row[index["E"]] = {"v": verdict.title(), "t": verdict}
            row[index["Ev"]] = {"v": build}
            built.append(row)
        return build_dailyexcel._counts(built, columns)["E"]

    def test_release_and_everything_are_counted_separately(self):
        counts = self.tab([("A", "pass", "mlt_2026.220.0-gitabc"),
                           ("B", "fail", "mlt_2026.220.0-gitabc"),
                           ("C", "pass", "mlt_validation_2026.225.0-gitx"),
                           ("D", "pass", "mlt_validation_2026.225.0-gitx")])
        self.assertEqual((counts["pass"], counts["fail"]), (3, 1))
        self.assertEqual((counts["release"]["pass"], counts["release"]["fail"]),
                         (1, 1))

    def test_the_excluded_builds_are_named(self):
        counts = self.tab([("A", "pass", "mlt_2026.220.0-gitabc"),
                           ("C", "fail", "debug_only_mlt_2026.223.0-gitx")])
        self.assertEqual(counts["nonRelease"], ["debug_only_mlt_2026.223.0-gitx"])

    def test_a_day_of_only_release_builds_flags_nothing(self):
        """No note where there is nothing to warn about — a caveat on every
        tile is a caveat nobody reads."""
        counts = self.tab([("A", "pass", "mlt_2026.220.0-gitabc"),
                           ("B", "fail", "mlt_2026.220.0-gitabc")])
        self.assertEqual(counts["nonRelease"], [])
        self.assertEqual((counts["pass"], counts["fail"]), (1, 1))
        self.assertEqual((counts["release"]["pass"], counts["release"]["fail"]),
                         (1, 1))

    def test_a_day_with_no_release_build_at_all_reports_zero(self):
        counts = self.tab([("C", "fail", "mlt_validation_2026.225.0-gitx")])
        self.assertEqual(counts["release"]["pass"] + counts["release"]["fail"], 0)
        self.assertEqual(counts["fail"], 1)


class NewInputCountTest(unittest.TestCase):
    """New material counted apart from re-runs.

    A day's yield is read as "how did today's build go", and a unit that
    failed last Monday and is re-run today answers a different question. On
    08-16 the tab reads 87.5% at MLT and every one of those sixteen units had
    been through the station before, so the figure is not a build yield at all.
    """

    def counts(self, rows):
        columns = build_dailyexcel._with_version_columns([
            {"key": "A", "title": "Date"}, {"key": "B", "title": "DUT SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
            {"key": "F", "title": "MLT Failure Test Case"},
            {"key": "G", "title": "FI Test Link"},
            {"key": "H", "title": "HTT Results", "station": "htt"},
            {"key": "I", "title": "HTT Failure"}, {"key": "J", "title": "Link"},
        ])
        index = {c["key"]: i for i, c in enumerate(columns)}
        built = []
        for dut, verdict, seen in rows:
            row = [{} for _ in columns]
            serial = {"v": dut, "new": not seen}
            if seen:
                serial["seen"] = {"mlt": seen}
            row[index["B"]] = serial
            row[index["E"]] = {"v": verdict.title(), "t": verdict}
            row[index["Ev"]] = {"v": "mlt_2026.220.0-gitabc"}
            built.append(row)
        return build_dailyexcel._counts(built, columns)["E"]

    def test_returning_units_are_counted_out_of_the_new_tally(self):
        counts = self.counts([("A", "pass", None), ("B", "fail", None),
                              ("C", "pass", "2026-08-12")])
        self.assertEqual((counts["pass"], counts["fail"]), (2, 1))
        self.assertEqual((counts["new"]["pass"], counts["new"]["fail"]), (1, 1))
        self.assertEqual(counts["returning"], 1)

    def test_a_day_of_only_returning_units_has_no_new_yield(self):
        """The 08-16 case: 87.5% over sixteen units, none of them fresh.
        The new tally must be empty rather than repeating the full one."""
        counts = self.counts([("A", "pass", "2026-08-10"),
                              ("B", "pass", "2026-08-11")])
        self.assertEqual((counts["pass"], counts["fail"]), (2, 0))
        self.assertEqual(counts["new"]["pass"] + counts["new"]["fail"], 0)
        self.assertEqual(counts["returning"], 2)

    def test_new_and_release_filters_compose(self):
        """Two independent questions — every unit vs new input, and every
        build vs release builds. Four tallies, not three."""
        columns = build_dailyexcel._with_version_columns([
            {"key": "A", "title": "Date"}, {"key": "B", "title": "DUT SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
        ])
        index = {c["key"]: i for i, c in enumerate(columns)}
        rows = []
        for dut, verdict, seen, build in (
                ("A", "pass", None, "mlt_2026.220.0-gitabc"),
                ("B", "fail", None, "mlt_validation_2026.225.0-gitx"),
                ("C", "pass", "2026-08-12", "mlt_2026.220.0-gitabc")):
            row = [{} for _ in columns]
            serial = {"v": dut, "new": not seen}
            if seen:
                serial["seen"] = {"mlt": seen}
            row[index["B"]] = serial
            row[index["E"]] = {"v": verdict.title(), "t": verdict}
            row[index["Ev"]] = {"v": build}
            rows.append(row)
        counts = build_dailyexcel._counts(rows, columns)["E"]
        self.assertEqual((counts["pass"], counts["fail"]), (2, 1))
        self.assertEqual((counts["new"]["pass"], counts["new"]["fail"]), (1, 1))
        self.assertEqual((counts["release"]["pass"], counts["release"]["fail"]),
                         (2, 0))
        self.assertEqual(
            (counts["newRelease"]["pass"], counts["newRelease"]["fail"]), (1, 0))

    def test_the_lookback_is_published_with_the_counts(self):
        """The page states the window in prose; it must read it rather than
        name a number that can drift from the one used."""
        counts = self.counts([("A", "pass", None)])
        self.assertEqual(counts["lookback"], build_dailyexcel.NEW_INPUT_LOOKBACK)

    def test_a_unit_new_to_one_station_can_be_returning_at_another(self):
        """The columns are counted separately: a module can be fresh to HTT
        and back for a second go at MLT on the same row."""
        columns = build_dailyexcel._with_version_columns([
            {"key": "A", "title": "Date"}, {"key": "B", "title": "DUT SN"},
            {"key": "E", "title": "MLT Results", "station": "mlt"},
            {"key": "H", "title": "HTT Results", "station": "htt"},
        ])
        index = {c["key"]: i for i, c in enumerate(columns)}
        row = [{} for _ in columns]
        row[index["B"]] = {"v": "A", "new": False, "seen": {"mlt": "2026-08-12"}}
        row[index["E"]] = {"v": "Passed", "t": "pass"}
        row[index["H"]] = {"v": "Passed", "t": "pass"}
        counts = build_dailyexcel._counts([row], columns)
        self.assertEqual(counts["E"]["new"]["pass"], 0)
        self.assertEqual(counts["H"]["new"]["pass"], 1)


class RetestHistoryTest(unittest.TestCase):
    """The attempts behind a returning serial.

    "F1 P2" on a row is only worth printing if each mark opens the run it
    names. The numbering is the unit's own attempt count, so F7 means the
    seventh visit — not the seventh of the ones that fit in the cell.
    """

    def attempts(self, statuses, day="2026-08-12"):
        return [{"day": day, "status": s, "url": "http://pega3:3000/x%d" % i,
                 "suite": "mlt_2026.220.0-gitabc"}
                for i, s in enumerate(statuses)]

    def test_attempts_are_numbered_from_the_units_first(self):
        trimmed = build_dailyexcel._trim_history(self.attempts(["fail", "pass"]))
        self.assertEqual([(a["n"], a["status"]) for a in trimmed],
                         [(1, "fail"), (2, "pass")])

    def test_numbering_survives_the_trim(self):
        """A unit re-run twenty times must not have its ninth attempt
        relabelled as its first."""
        many = self.attempts(["fail"] * 20)
        trimmed = build_dailyexcel._trim_history(many)
        self.assertEqual(len(trimmed), build_dailyexcel.HISTORY_LIMIT)
        self.assertEqual(trimmed[-1]["n"], 20)
        self.assertEqual(trimmed[0]["n"],
                         20 - build_dailyexcel.HISTORY_LIMIT + 1)

    def test_every_attempt_keeps_its_own_link(self):
        trimmed = build_dailyexcel._trim_history(self.attempts(["fail", "pass"]))
        self.assertEqual(len({a["url"] for a in trimmed}), 2)

    def test_a_short_history_is_not_padded(self):
        self.assertEqual(len(build_dailyexcel._trim_history(
            self.attempts(["pass"]))), 1)


class SheetOmissionTest(unittest.TestCase):
    """Why Count all and Count new agree on a hand-kept tab.

    Because they do. pega3 recorded 59 MLT units on 08-12 and the sheet lists
    51, and all eight missing ones are units the station had seen before —
    same shape on 08-11, 100 against 87 with all thirteen omitted returning.
    The line was already keeping a new-input-only record by hand, so its own
    tabs cannot show the difference the rebuilt ones do.
    """

    def test_a_tab_records_what_the_sheet_left_out(self):
        from factory import build_dailyexcel as bd
        tab = {
            "day": "2026-08-12",
            "columns": bd._with_version_columns([
                {"key": "A", "title": "Date"}, {"key": "B", "title": "DUT SN"},
                {"key": "E", "title": "MLT Results", "station": "mlt"},
                {"key": "F", "title": "F"}, {"key": "G", "title": "G"},
                {"key": "H", "title": "HTT Results", "station": "htt"},
                {"key": "I", "title": "I"}, {"key": "J", "title": "J"},
            ]),
            "rows": [],
        }
        index = {c["key"]: i for i, c in enumerate(tab["columns"])}
        for dut in ("A", "B"):
            row = [{} for _ in tab["columns"]]
            row[index["B"]] = {"v": dut}
            tab["rows"].append(row)

        units = {"A": {"mlt": {"status": "pass"}},
                 "B": {"mlt": {"status": "pass"}},
                 "C": {"mlt": {"status": "fail"}}}   # ran, not on the sheet

        original = bd._seen_before
        try:
            bd._seen_before = lambda day, lookback=10: {
                "mlt": {"C": [{"day": "2026-08-11", "status": "fail",
                               "url": "http://pega3:3000/x", "suite": "mlt"}]},
                "htt": {}}
            out = bd._add_sheet_versions(tab, units)
        finally:
            bd._seen_before = original

        self.assertEqual(out["sheetOmits"]["mlt"],
                         {"units": 1, "returning": 1, "ranThatDay": 3})

    def test_a_tab_that_omits_nothing_carries_no_note(self):
        from factory import build_dailyexcel as bd
        tab = {
            "day": "2026-08-12",
            "columns": bd._with_version_columns([
                {"key": "A", "title": "Date"}, {"key": "B", "title": "DUT SN"},
                {"key": "E", "title": "MLT Results", "station": "mlt"},
            ]),
            "rows": [],
        }
        index = {c["key"]: i for i, c in enumerate(tab["columns"])}
        row = [{} for _ in tab["columns"]]
        row[index["B"]] = {"v": "A"}
        tab["rows"].append(row)

        original = bd._seen_before
        try:
            bd._seen_before = lambda day, lookback=10: {"mlt": {}, "htt": {}}
            out = bd._add_sheet_versions(tab, {"A": {"mlt": {"status": "pass"}}})
        finally:
            bd._seen_before = original
        self.assertNotIn("sheetOmits", out)


class L10OnTheDailyTrackerTest(unittest.TestCase):
    """L10 beside the module stages, from the day it started testing.

    A second table rather than more columns: a chassis is not a module, one
    chassis holds many of them, and a row carrying both would have no single
    subject.
    """

    def test_every_published_day_is_looked_at(self):
        """With no standalone L10 page left, a date floor here would be a
        floor on where L10 can be seen at all — 08-11, 08-12 and 08-14 all had
        chassis on pega4 and would simply vanish."""
        for day in ("2026-08-11", "2026-08-12", "2026-08-14", "2026-08-18"):
            self.assertGreaterEqual(day, build_dailyexcel.L10_FROM)

    def test_a_day_with_no_l10_runs_gets_no_table(self):
        """The floor is the data, not the calendar."""
        from factory import build_l10

        original = build_l10._day
        try:
            build_l10._day = lambda day: None
            self.assertIsNone(build_dailyexcel._l10_for("2026-08-15"))
        finally:
            build_l10._day = original

    def test_the_l10_tab_is_built_by_the_l10_tracker(self):
        """Imported rather than reimplemented: the stage matching, the pega4
        host and the four-column shape all live there, and a second copy would
        be a second answer to "did FAT pass today"."""
        from factory import build_l10

        called = {}

        def fake_day(day):
            called["day"] = day
            return {"day": day, "rows": [[{}]], "columns": [], "counts": {}}

        original = build_l10._day
        try:
            build_l10._day = fake_day
            out = build_dailyexcel._l10_for("2026-08-18")
        finally:
            build_l10._day = original
        self.assertEqual(called["day"], "2026-08-18")
        self.assertEqual(out["day"], "2026-08-18")

    def test_a_day_pega4_cannot_answer_for_is_no_table(self):
        """An unreachable controller must not fail the module tracker's
        build; the day simply has no L10 section."""
        from factory import build_l10

        original = build_l10._day
        try:
            build_l10._day = lambda day: (_ for _ in ()).throw(RuntimeError("down"))
            self.assertIsNone(build_dailyexcel._l10_for("2026-08-18"))
        finally:
            build_l10._day = original


class SerialHeadingTest(unittest.TestCase):
    """Every daily table heads its serial column ``SN``.

    Each was naming its own subject there — "DUT SN" over modules, "Chassis SN"
    over L10, "Rack SN" over L11 — which made one column at three levels look
    like three different things. The subject is stated above each table, where
    it belongs.

    The module table is the one that cannot be fixed at its source: its titles
    come from the line's workbook, so the override happens after the tabs are
    assembled and the workbook reader stays a faithful reader.
    """

    def tab(self, title):
        return {"columns": [{"key": "A", "title": "Date"},
                            {"key": "B", "title": title},
                            {"key": "C", "title": "DUT PN"}]}

    def test_a_sheet_heading_is_overridden(self):
        tab = self.tab("DUT SN")
        build_dailyexcel._serial_heading(tab)
        self.assertEqual(tab["columns"][1]["title"], "SN")

    def test_the_two_tables_underneath_are_covered_too(self):
        tab = self.tab("DUT SN")
        tab["l10"] = self.tab("Chassis SN")
        tab["l11"] = self.tab("Rack SN")
        build_dailyexcel._serial_heading(tab)
        for table in (tab, tab["l10"], tab["l11"]):
            self.assertEqual(table["columns"][1]["title"], "SN")

    def test_no_other_column_is_touched(self):
        tab = self.tab("DUT SN")
        build_dailyexcel._serial_heading(tab)
        self.assertEqual([c["title"] for c in tab["columns"]],
                         ["Date", "SN", "DUT PN"])

    def test_a_tab_with_no_l10_or_l11_is_fine(self):
        tab = self.tab("DUT SN")
        build_dailyexcel._serial_heading(tab)          # must not raise
        self.assertEqual(tab["columns"][1]["title"], "SN")


class HostIdentityTest(unittest.TestCase):
    """One machine, one identity — the bug of 2026-08-27.

    ``pega.day_suite_runs(day)`` and ``pega.day_suite_runs(day, host="pega3")``
    build the same URL, and pega.py used to treat them as two names. A single
    timeout under the unnamed call marked "default" dead for the rest of the
    process while every pega3-named call carried on working, so the daily
    tracker — the only caller using the unnamed form — silently fell back to a
    cached listing hours old. The 08-27 tab was built from six runs when pega3
    had fifteen, reported nothing excluded, and its note said it had been
    rebuilt from pega3.

    Two things keep it fixed, and both are asserted: the names resolve to one
    identity, and every caller says which host it means.
    """

    def test_the_unnamed_host_resolves_to_the_named_one(self):
        from factory import pega
        self.assertEqual(pega.base_url(None), pega.base_url("pega3"))
        self.assertEqual("pega3", pega._default_host_name())   # noqa: SLF001

    def test_a_failure_under_either_name_stops_both(self):
        """The behaviour, not the helper.

        Checking that `_default_host_name()` returns "pega3" passes even if
        `_get` never calls it — which is exactly the state the bug was in. So
        this marks the machine unreachable under its explicit name and requires
        the unnamed call to know: same machine, same verdict.
        """
        from factory import pega
        before = set(pega._UNREACHABLE)                       # noqa: SLF001
        try:
            pega._UNREACHABLE.add("pega3")                    # noqa: SLF001
            with self.assertRaises(pega.PegaUnavailable) as caught:
                pega._get("/api/nothing", cache=False, host=None)  # noqa: SLF001
            # The short-circuit's own words. Asserting on "pega3" alone was
            # useless: the fallthrough path raises with the URL in it, and the
            # URL contains pega3 whichever bucket the call landed in.
            self.assertIn("unreachable earlier in this run",
                          str(caught.exception),
                          "host=None was bucketed apart from pega3, so a "
                          "timeout under one name leaves the other running")
        finally:
            pega._UNREACHABLE.clear()                         # noqa: SLF001
            pega._UNREACHABLE.update(before)                  # noqa: SLF001

    def test_the_cache_key_does_not_depend_on_the_environment(self):
        """Resolving host=None to a name inside the key looked tidy and was
        wrong: the key would then depend on FACTORY_PEGA_URL, so a cache
        written before that variable changed could not be found after, and
        every existing cache file would be orphaned by the rename. Sharing is
        achieved by callers naming their host, not by rewriting the key."""
        import os
        from factory import pega
        path = "/api/history/data-analysis/suite-runs?start=x&end=y"
        first = pega._cache_path(path, None)                  # noqa: SLF001
        previous = os.environ.get("FACTORY_PEGA_URL")
        os.environ["FACTORY_PEGA_URL"] = "http://pega4:3000"
        try:
            self.assertEqual(first,
                             pega._cache_path(path, None))    # noqa: SLF001
        finally:
            if previous is None:
                os.environ.pop("FACTORY_PEGA_URL", None)
            else:
                os.environ["FACTORY_PEGA_URL"] = previous

    def test_every_pega_call_names_its_host(self):
        """A caller that does not name its host is a caller whose failures are
        bucketed apart from everybody else's."""
        import re
        from factory import config
        pattern = re.compile(r"pega\.(day_suite_runs|suite_run)\(([^)]*)\)")
        offenders = []
        for source in sorted((config.REPO_ROOT / "src" / "factory").glob("*.py")):
            if source.name == "pega.py":
                continue
            for found in pattern.finditer(source.read_text(encoding="utf-8")):
                if "host=" not in found.group(2):
                    offenders.append("{}: {}".format(source.name,
                                                     found.group(0)))
        self.assertEqual([], offenders)

    def test_a_stale_listing_is_recorded(self):
        """The tab has to be able to say its listing came from the cache. A
        stale answer presented as a fresh one is what this page exists to
        avoid."""
        from factory import build_dailyexcel, pega
        self.assertTrue(hasattr(pega, "fell_back"))
        source = (build_dailyexcel.__file__).replace(".pyc", ".py")
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('"staleListing": pega.fell_back("pega3")', text)
