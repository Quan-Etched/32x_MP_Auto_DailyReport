"""Which data bundle each page loads.

The controllers are the default source now and OCP is the second opinion, which
is a swap of two script tags — and a swap of two script tags is exactly the
change that gets made backwards during a rename and noticed a week later by
somebody quoting the wrong number. The pairing is asserted here so it cannot
drift silently.
"""

import re
import unittest

from factory import config

DASHBOARD = config.REPO_ROOT / "dashboard"

#: page -> the one data bundle it is allowed to load.
EXPECTED = {
    "index.html": "data/pega_stations.js",      # default: the controllers
    "ocp.html": "data/stations.js",             # second opinion: OCP Logs
    "runs.html": "data/runs_pega.js",
    "ocpruns.html": "data/runs.js",
    "dailyexcel.html": "data/dailyexcel.js",
    "weekly.html": "data/weekly.js",
    "week.html": "data/weekly.js",
    "flow.html": "data/pega_stations.js",
    "retest.html": "data/retest.js",
}

#: Addresses that were handed out and must keep resolving.
REDIRECTS = {"direct.html": "index.html", "directruns.html": "runs.html",
             "fpy.html": "week.html",
             # L10 is a table on the daily tracker now, not a page.
             "l10.html": "dailyexcel.html"}


#: Pages that load more than one bundle, and why.
MULTI = {
    # The releases page hosts two analyses of the same releases: one built
    # from test logs, one from the source tree they were built from.
    "releases.html": ["data/release_source.js", "data/releases.js"],
}


def data_scripts(name):
    text = (DASHBOARD / name).read_text(encoding="utf-8")
    return re.findall(r'src="(data/[a-z0-9_]+\.js)"', text)


class PageSourceTest(unittest.TestCase):
    def test_each_page_loads_exactly_its_own_bundle(self):
        for page, bundle in EXPECTED.items():
            with self.subTest(page=page):
                self.assertEqual(data_scripts(page), [bundle])

    def test_pages_that_host_two_analyses_load_both(self):
        for page, bundles in MULTI.items():
            with self.subTest(page=page):
                self.assertEqual(sorted(data_scripts(page)), sorted(bundles))

    def test_the_default_view_is_the_controllers(self):
        """The landing page is the one whose numbers the daily tracker agrees
        with. Pointing it back at OCP would reopen the discrepancy."""
        self.assertEqual(data_scripts("index.html"), ["data/pega_stations.js"])

    def test_the_two_station_pages_do_not_share_a_bundle(self):
        self.assertNotEqual(data_scripts("index.html"), data_scripts("ocp.html"))

    def test_old_addresses_still_resolve(self):
        for page, target in REDIRECTS.items():
            with self.subTest(page=page):
                text = (DASHBOARD / page).read_text(encoding="utf-8")
                self.assertIn('url=' + target, text)
                self.assertIn(target, text)

    def test_no_page_links_to_a_file_that_is_not_there(self):
        for page in list(EXPECTED) + list(REDIRECTS):
            text = (DASHBOARD / page).read_text(encoding="utf-8")
            for href in re.findall(r'href="([a-z0-9_]+\.html)"', text):
                with self.subTest(page=page, href=href):
                    self.assertTrue((DASHBOARD / href).exists(), href)


class LinkTest(unittest.TestCase):
    """Every internal link resolves, and lands where it says.

    Found the hard way: the flow chart's per-box "open" links pointed at
    direct.html#station=l10_2u. direct.html became a redirect, a meta refresh
    drops the #fragment, and every one of those links landed on the station
    page with nothing selected — the boxes looked wired and went nowhere.
    """

    LINK = re.compile(r'''["'](?:href=)?([a-z0-9_]+\.html)(#[^"'\s]*)?["']''')

    def is_redirect(self, name):
        return 'http-equiv="refresh"' in (DASHBOARD / name).read_text(
            encoding="utf-8")

    def links(self):
        """(source, target, fragment) for every internal link, markup or JS."""
        found = []
        sources = sorted(DASHBOARD.glob("*.html")) + sorted(DASHBOARD.glob("*.js"))
        for src in sources:
            text = src.read_text(encoding="utf-8")
            for match in self.LINK.finditer(text):
                found.append((src.name, match.group(1), match.group(2) or ""))
        return found

    def test_every_link_target_exists(self):
        for src, target, _frag in self.links():
            with self.subTest(src=src, target=target):
                self.assertTrue((DASHBOARD / target).exists(), target)

    def test_no_link_sends_a_fragment_through_a_redirect(self):
        """A meta refresh drops it, so the reader lands on the right page with
        the wrong thing selected — which reads as a broken page."""
        for src, target, frag in self.links():
            if not frag:
                continue
            with self.subTest(src=src, target=target + frag):
                self.assertFalse(self.is_redirect(target),
                                 "{} -> {}{}".format(src, target, frag))

    def test_the_redirects_carry_a_fragment_anyway(self):
        """Belt and braces: these addresses are in Slack messages already."""
        for name in REDIRECTS:
            text = (DASHBOARD / name).read_text(encoding="utf-8")
            self.assertIn("location.hash", text, name)

    def test_flowchart_boxes_link_to_stations_that_exist(self):
        """The links are computed from station keys, so a renamed station
        silently produces a link to nothing."""
        import json
        bundle = DASHBOARD / "data" / "pega_stations.js"
        if not bundle.exists():
            self.skipTest("no station bundle built")
        views = json.loads(
            bundle.read_text().split("= ", 1)[1].rstrip().rstrip(";"))["views"]
        flow = (DASHBOARD / "flow.js").read_text(encoding="utf-8")
        keys = re.findall(r"station:\s*'([a-z0-9_]+)'", flow)
        self.assertTrue(keys, "no station keys found in flow.js")
        for key in dict.fromkeys(keys):
            with self.subTest(station=key):
                self.assertIn(key, views)

    def test_the_flowchart_links_at_the_default_station_page(self):
        flow = (DASHBOARD / "flow.js").read_text(encoding="utf-8")
        self.assertIn("'index.html#station='", flow)
        self.assertNotIn("'direct.html#station='", flow)


if __name__ == "__main__":
    unittest.main()


class RetestColumnTest(unittest.TestCase):
    """The Test History column and its F/P traces.

    Two rules were wrong here in turn. The column was drawn only in Count all,
    which switched it off on exactly the days that needed it; and a returning
    unit's DUT SN moved into the column with it, spreading the day's units over
    two headings. Now the serial always stays in DUT SN, and the column is
    drawn whenever anything on screen has a history to put in it.

    Which, since Count new became "no history anywhere", means in practice:
    populated in Count all, absent in Count new.
    """

    def script(self):
        return (DASHBOARD / "dailysheet.js").read_text(encoding="utf-8")

    def test_the_column_follows_the_data_not_the_mode(self):
        text = self.script()
        self.assertNotIn("var showHistory = countMode === 'all';", text)
        self.assertIn("var showHistory = rows.some(", text)

    def test_the_serial_stays_in_one_column(self):
        """Both cells are appended unconditionally: DUT SN renders for every
        row, and the history cell beside it is what is empty or full."""
        text = self.script()
        self.assertIn("tr.appendChild(renderCell(cell, column, wraps[position]));\n"
                      "          tr.appendChild(historyCell(cell));", text)
        self.assertNotIn("Retested DUT SN", text)
        self.assertIn("text: 'Test History'", text)

    def test_the_last_seen_note_does_not_double_up_on_the_serial(self):
        """The note under the serial and the column beside it said the same
        thing. The column keeps it, with the links; DUT SN goes back to being
        a column of serials."""
        text = self.script()
        self.assertIn("cell.seen && !historyColumn", text)
        self.assertIn("class: 'rt-when'", text)

    def test_count_new_is_units_with_no_history_anywhere(self):
        """Count new used to keep a unit that was new at *any* station, so a
        row returning to MLT and fresh to HTT sat in it carrying its MLT
        attempts. A mode read as "today's fresh material" cannot show rows
        with a history."""
        text = self.script()
        self.assertIn("return !Object.keys(serial.seen || {}).length;", text)
        self.assertNotIn("if (!seen[station]) return true;", text)

    def test_the_derived_provenance_tile_is_gone(self):
        """Its suite-run count went first, then the caveats that outlived it:
        releaseOnly() states the non-release builds on the tile that counted
        them, and renderCaption names the source under every table."""
        text = self.script()
        self.assertNotIn("Read these numbers with", text)
        self.assertNotIn("function debugNote", text)
        self.assertNotIn("function excludedNote", text)
        self.assertIn("releaseOnly(entry)", text)

    def test_the_tile_puts_passed_and_failed_on_their_own_line(self):
        """They are what the tile is read for. They used to share a reflowing
        grey paragraph with the not-run count, the mode note and the other
        population's figure."""
        text = self.script()
        self.assertIn("class: 'tile-sub tile-verdicts'", text)
        self.assertIn("class: 'tile-sub tile-unrun'", text)
        css = (DASHBOARD / "dailyexcel.css").read_text(encoding="utf-8")
        self.assertIn(".sheet-tile .tile-sub { display: block;", css)

    def test_the_marks_are_built_from_the_attempt_number(self):
        """F1 is the first attempt and it failed; the number is the unit's own
        visit count, so it cannot be the row's position in the cell."""
        text = self.script()
        self.assertIn("attempt.status === 'pass' ? 'P' : 'F'", text)
        self.assertIn("attempt.n", text)

    def test_each_mark_links_to_its_run(self):
        text = self.script()
        self.assertIn("href: attempt.url", text)

    def test_both_yields_are_rendered_without_a_button_press(self):
        """Both populations are wanted daily; neither should be behind a
        toggle."""
        self.assertIn("tile-other", self.script())


class TableZoomTest(unittest.TestCase):
    """Zooming the tables, on the gesture a spreadsheet uses.

    The sheet is thirteen columns wide and the L10 one is nineteen, so both
    stay wider than the screen they are read on. The only way to reach the HTT
    column was the horizontal scrollbar, which the line reported as the most
    awkward thing about the page: in Excel you press a key and the table
    shrinks until you can see all of it.
    """

    def page(self):
        return (DASHBOARD / "dailyexcel.html").read_text(encoding="utf-8")

    def script(self):
        return (DASHBOARD / "dailysheet.js").read_text(encoding="utf-8")

    def style(self):
        return (DASHBOARD / "dailyexcel.css").read_text(encoding="utf-8")

    def test_the_control_is_on_the_page(self):
        page = self.page()
        for element in ("zoom-out", "zoom-in", "zoom-level",
                        "zoom-fit", "zoom-reset", "zoom-note"):
            with self.subTest(element=element):
                self.assertIn('id="%s"' % element, page)

    def test_it_zooms_rather_than_scales(self):
        """zoom is a layout operation, so the table really becomes narrower and
        the scroll container has less to scroll. transform would shrink only
        the paint and leave the scrollport believing it was full width."""
        style = self.style()
        self.assertIn(".sheet-table { zoom: var(--sheet-zoom, 1); }", style)
        # The declaration, not the comment above it explaining why not, and
        # not text-transform, which the sticky header legitimately sets.
        declarations = [line.split("/*")[0] for line in style.splitlines()]
        self.assertFalse([d for d in declarations
                          if re.search(r"(^|[\s;{])transform\s*:", d)])

    def test_one_value_drives_every_table(self):
        """Set on the root element, so the module, L10 and L11 tables cannot
        end up at three different sizes on one page."""
        self.assertIn(
            "document.documentElement.style.setProperty('--sheet-zoom'",
            self.script())

    def test_the_shortcut_needs_shift(self):
        """Cmd+/- is the browser's own page zoom and still works: it shrinks
        the tiles and the prose too, which is sometimes what a reader wants.
        Taking it over would remove that and pick a fight with a shortcut every
        browser reserves. Cmd+Shift+/- is what the line asked for and is free."""
        text = self.script()
        self.assertIn(
            "if (!(event.metaKey || event.ctrlKey) || !event.shiftKey || event.altKey) {",
            text)

    def test_the_keys_are_matched_by_physical_code(self):
        """event.key for the shifted characters is layout-dependent; the code
        is the physical key, so this survives a keyboard that does not put +
        and - where a US one does."""
        text = self.script()
        for code in ("'Minus'", "'Equal'", "'Digit0'"):
            with self.subTest(code=code):
                self.assertIn(code, text)

    def test_fit_measures_at_full_size(self):
        """The table carries min-width:100%, so at any zoom where it already
        fits, scrollWidth equals clientWidth — a ratio taken there would report
        "fitted" at every level. Reading the natural width first is the only
        measurement that means anything."""
        text = self.script()
        self.assertIn("function fitZoom() {\n    setZoom(1);", text)

    def test_fit_says_so_when_it_could_not_fit(self):
        """A control that promises to fit and quietly does not is worse than
        one that says how far it got. L10 needs 44% at a full-screen window and
        the floor is 50%."""
        text = self.script()
        self.assertIn("still scrolls", text)
        self.assertIn("zoomNote(", text)

    def test_the_level_survives_a_reload(self):
        """Somebody who found the level at which their day fits on one screen
        should not have to find it again every morning."""
        self.assertIn("factory.daily.zoom", self.script())
