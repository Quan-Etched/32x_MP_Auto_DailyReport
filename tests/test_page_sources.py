"""Which data bundle each page loads.

The controllers are the default source now and OCP is the second opinion, which
is a swap of two script tags — and a swap of two script tags is exactly the
change that gets made backwards during a rename and noticed a week later by
somebody quoting the wrong number. The pairing is asserted here so it cannot
drift silently.
"""

import json
import re
import subprocess
import unittest

from factory import config

DASHBOARD = config.REPO_ROOT / "dashboard"

#: page -> the one data bundle it is allowed to load.
EXPECTED = {
    "index.html": "data/pega_stations.js",      # default: the controllers
    "ocp.html": "data/stations.js",             # second opinion: OCP Logs
    "runs.html": "data/runs_pega.js",
    "allhands.html": "data/runs_pega.js",
    "rack2.html": "data/runs_pega.js",
    "ocpruns.html": "data/runs.js",
    "dailyexcel.html": "data/dailyexcel.js",
    "weekly.html": "data/weekly.js",
    "week.html": "data/weekly.js",
    "flow.html": "data/pega_stations.js",
    "doe.html": "data/outcomes.js",
}

#: Addresses that were handed out and must keep resolving.
REDIRECTS = {"direct.html": "index.html", "directruns.html": "runs.html",
             "fpy.html": "week.html",
             # Retired 2026-08-22. The comparison settled its question (a
             # cut-off time, not a disagreement about any unit) and the retest
             # page was replaced by the error-code table on the customize page.
             # Both addresses had been handed out in Slack.
             "delta.html": "dailyexcel.html",
             # Both chart pages folded into flow.html, which hosts the two
             # drawings behind a switch.
             "flowfull.html": "flow.html",
             "flowe2e.html": "flow.html",
             "retest.html": "customize.html",
             # L10 is a table on the daily tracker now, not a page.
             "l10.html": "dailyexcel.html"}


#: Pages that load more than one bundle, and why.
MULTI = {
    # Section 4 is a different question from sections 1-3 — failures joined to
    # the error-code catalogue, not runs — and its own bundle, so the run
    # bundle does not grow a second schema inside it.
    # runs_pega_light.js, not runs_pega.js: the page ships ~16 KB of controls
    # and bigdata.js fetches the 8.6 MB of runs behind the button that needs
    # them. Pinned so a well-meaning revert to the full bundle has to be a
    # deliberate edit here -- it would put the four-minute blocking load back.
    #
    # data/trace.js is deliberately NOT here: trace.js fetches the genealogy
    # itself, the first time a serial is actually being looked at. It is 1.3 MB
    # at production scale and most visits to this page never open the tree.
    "customize.html": ["data/runs_pega_light.js", "data/errors.js"],
    # The releases page hosts two analyses of the same releases: one built
    # from test logs, one from the source tree they were built from.
    "releases.html": ["data/release_source.js", "data/releases.js"],
}


def data_scripts(name):
    text = (DASHBOARD / name).read_text(encoding="utf-8")
    return re.findall(r'src="(data/[a-z0-9_]+\.js)"', text)


#: page -> the page-specific scripts that reach into its DOM. Shared scripts
#: (update.js, theme.js, nav.js, charts.js) are left out: they run on many pages
#: and each one guards for the elements it wants.
DOM_SCRIPTS = {
    "index.html": ["stations.js"],
    "ocp.html": ["stations.js"],
    "dailyexcel.html": ["dailysheet.js"],
    "weekly.html": ["weeklysummary.js"],
    "customize.html": ["customize.js", "errors.js", "customcharts.js",
                       "dutsearch.js", "searchmode.js"],
    "allhands.html": ["allhands.js"],
    "rack2.html": ["rack2.js"],
    "week.html": ["week.js"],
    # Two drawings on one page: flow.js draws the summary, flowchart.js draws
    # the end-to-end chart from flowe2e.js's data, flowswitch.js picks.
    "flow.html": ["flow.js", "flowchart.js", "flowswitch.js", "flowcsv.js"],
    "doe.html": ["doe.js"],
    "releases.html": ["releasesrc.js", "suitemap.js"],
}

#: ``byId('x')`` and ``getElementById('x')``, including the literal prefix of a
#: built-up id like ``byId('body-' + stage.key)``.
ELEMENT_LOOKUP = re.compile(
    r"(?:byId|getElementById)\(\s*'([A-Za-z0-9_-]+)'")


def element_ids(name):
    return set(re.findall(r'id="([^"]+)"', (DASHBOARD / name).read_text(
        encoding="utf-8")))


class DomWiringTest(unittest.TestCase):
    """Every element a page's script reaches for exists in that page.

    Renaming an element and missing one lookup does not fail loudly. The delta
    page's guard kept asking for ``#table-body`` after the single table became
    ``#body-mlt`` and ``#body-htt``: getElementById returned null, init returned,
    and the page rendered every static heading and not one row — so it looked
    built and was empty. Nothing threw, nothing 404'd, and it took a screenshot
    to notice.

    A whole-page check would need a DOM. This does not: it is a string match
    between the ids a page declares and the ids its script asks for, which is
    exactly the join that broke.
    """

    def test_every_id_a_page_script_asks_for_exists_in_the_page(self):
        for page, scripts in DOM_SCRIPTS.items():
            ids = element_ids(page)
            for script in scripts:
                source = (DASHBOARD / script).read_text(encoding="utf-8")
                for wanted in sorted(set(ELEMENT_LOOKUP.findall(source))):
                    with self.subTest(page=page, script=script, id=wanted):
                        # A built-up id ("body-" + stage) only has its prefix in
                        # the source, so it is enough that some real id starts
                        # with it — the point is that the prefix is not stale.
                        self.assertTrue(
                            wanted in ids
                            or any(one.startswith(wanted) for one in ids),
                            "{} asks for #{}, which {} does not define".format(
                                script, wanted, page))


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
        # Both drawings, because they are two files that name station keys and
        # only one of them used to be checked. flowfull.js is gone: it was a
        # subset of flowe2e.js, and both now render on flow.html.
        for name in ("flow.js", "flowe2e.js"):
            source = (DASHBOARD / name).read_text(encoding="utf-8")
            keys = re.findall(r"station:\s*'([a-z0-9_]+)'", source)
            self.assertTrue(keys, "no station keys found in " + name)
            for key in dict.fromkeys(keys):
                with self.subTest(chart=name, station=key):
                    self.assertIn(key, views)

    def test_the_asic_lane_hands_off_from_ft_not_slt(self):
        """SLT is a branch off FT, not a step on the way to a board.

        The summary chart used to run SLT -> SMT / ICT, which says every die
        goes through system level test before it reaches a board. It does not,
        and the line is deciding whether to keep SLT at all — so the chart was
        asserting the opposite of the thing under discussion.
        """
        flow = (DASHBOARD / "flow.js").read_text(encoding="utf-8")
        self.assertIn("{ from: 'ft',     to: 'smt',    route: 'across' }", flow)
        self.assertNotIn("from: 'slt',    to: 'smt'", flow)

    def test_slt_is_struck_through_and_says_where_the_data_is(self):
        """Struck, not deleted: the proposal is to skip it, not a fact that it
        was skipped. And a struck-out box with no link is a decision nobody
        outside the room can check."""
        for name in ("flow.js", "flowe2e.js"):
            source = (DASHBOARD / name).read_text(encoding="utf-8")
            slt = source[source.index("id: 'slt'"):]
            slt = slt[:slt.index("},")]
            with self.subTest(chart=name):
                self.assertIn("struck: true", slt)
                self.assertIn("go/slt-ft", slt)

    def test_the_flowchart_links_at_the_default_station_page(self):
        flow = (DASHBOARD / "flow.js").read_text(encoding="utf-8")
        self.assertIn("'index.html#station='", flow)
        self.assertNotIn("'direct.html#station='", flow)


if __name__ == "__main__":
    unittest.main()


class ControlsWithoutRunsTest(unittest.TestCase):
    """The customize page draws its controls before the runs exist.

    Since the two-step load the page ships ~16 KB of controls and fetches the
    8.6 MB of runs behind the RUN button. Two controls were still derived by
    scanning ``DATA.runs``, which that split leaves empty:

    * the station list, and the RUN button is disabled until a station is
      ticked — so section 2 rendered blank with no way to fill it. Nothing to
      tick, so nothing to press, so the runs never arrived, so the list stayed
      blank. The page could not be used at all.
    * the day list, captured once at load. bigdata.js fills ``runs`` *in
      place*, so a captured list stays empty for the life of the page even
      after the runs are in.

    Both now read the catalogue the light bundle carries for exactly this
    purpose — ``stationOrder``, ``stationLabels``, ``window`` — and the day
    list is recomputed rather than captured.
    """

    def script(self):
        return (DASHBOARD / "customize.js").read_text(encoding="utf-8")

    def test_the_built_in_station_list_matches_the_registry(self):
        """customize.js carries its own copy of the station list, because an
        empty section 2 is not a degraded page but an unusable one: nothing to
        tick, so the RUN button stays disabled, so the runs that would fill the
        list never load.

        A duplicate needs a guard. This is it — the copy and
        factory.stations.registry() must stay the same list, in the same order.
        """
        from factory import stations

        text = self.script()
        block = text.split("var STATIONS = [", 1)[1].split("]", 1)[0]
        got = re.findall(r"'([a-z0-9_]+)'", block)
        self.assertEqual(got, [s["key"] for s in stations.registry()])

    def test_the_built_in_labels_match_the_registry_too(self):
        """Only used when stationLabels is missing as well, but a key leaking
        into a checkbox ("vbb_provision") is the kind of thing that ships."""
        from factory import stations

        text = self.script()
        block = text.split("var STATION_NAMES = {", 1)[1].split("};", 1)[0]
        got = dict(re.findall(r"(\w+): '([^']+)'", block))
        self.assertEqual(got, {s["key"]: s["label"] for s in stations.registry()})

    def test_the_station_list_survives_a_bundle_that_names_none(self):
        """The bundle's order wins when it has one; the built-in list is the
        fallback, not a merge — otherwise a controller that genuinely stopped
        running a station would keep a dead box on the page."""
        text = self.script()
        self.assertIn(
            "var order = (DATA.stationOrder || []).length ? DATA.stationOrder : STATIONS;",
            text)

    def test_the_station_list_comes_from_the_registry_not_the_runs(self):
        """The order is the bundle's catalogue or the built-in copy of it —
        either way a catalogue, never a scan of `runs`, which the controls-only
        bundle leaves empty."""
        text = self.script()
        self.assertIn("DATA.stationOrder", text)
        self.assertIn("var order =", text)
        self.assertNotIn(
            "    var seen = {};\n"
            "    RUNS.forEach(function (run) { if (run.k) seen[run.k] = true; });",
            text)

    def test_all_is_never_offered_as_a_station(self):
        """``__all__`` is a key in stationLabels for the label lookup. Ticking
        it would be a box for a station that does not exist."""
        text = self.script()
        self.assertIn("key === '__all__'", text)

    def test_the_day_list_is_recomputed_not_captured(self):
        text = self.script()
        self.assertIn("function days() {", text)
        self.assertIn("DAYS_FOR === RUNS.length", text)
        self.assertNotIn("var DAYS = (function () {", text)

    def test_the_day_list_falls_back_to_the_bundles_window(self):
        text = self.script()
        self.assertIn("var span = DATA.window || {};", text)

    def test_an_uncounted_station_is_not_called_empty(self):
        """Before the runs arrive every count is zero. Dimming the whole list
        and titling it "no runs in the chosen days" is the page asserting
        something about a number it has not been given."""
        text = self.script()
        self.assertIn("BIGDATA.needed && BIGDATA.needed()", text)
        self.assertIn("counted when the runs arrive", text)
        self.assertNotIn("class: 'check' + (count ? '' : ' empty'),", text)

    def test_the_footer_counts_what_the_bundle_declares(self):
        """"0 unit runs in the bundle" under a page offering to export them is
        the footer contradicting the controls."""
        text = self.script()
        self.assertIn("((DATA.full || {}).counts || {}).runs", text)

    def test_the_bigdata_stub_answers_every_call_the_page_makes(self):
        """The stub stands in when bigdata.js is absent. It was missing
        `needed`, which init() calls unconditionally — a TypeError on load for
        any page that dropped the script."""
        text = self.script()
        stub = text.split("var BIGDATA = window.FactoryBigData ||", 1)[1]
        stub = stub.split("};", 1)[0]
        for call in ("ensure", "attach", "needed"):
            self.assertIn(call + ":", stub)


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


class SharedChartsTest(unittest.TestCase):
    """The chart library both pages draw with.

    The renderers lived inside stations.js while one page used them. The weekly
    page now draws the same three over one frozen week, and two copies of a
    chart is two answers to "what does a hollow marker mean".
    """

    def read(self, name):
        return (DASHBOARD / name).read_text(encoding="utf-8")

    def test_every_page_that_charts_loads_the_library_first(self):
        """charts.js defines window.FactoryCharts; a page that loaded it after
        its own script would find nothing there."""
        for page, user in (("index.html", "stations.js"),
                           ("ocp.html", "stations.js"),
                           ("week.html", "week.js")):
            with self.subTest(page=page):
                text = self.read(page)
                self.assertIn('src="charts.js"', text)
                self.assertLess(text.index('src="charts.js"'),
                                text.index('src="%s"' % user))

    def test_the_library_knows_nothing_about_either_page(self):
        """No DATA, no state, no refs. That separation is what made the
        extraction a move rather than a rewrite, and what keeps it one."""
        text = self.read("charts.js")
        for leak in ("__FACTORY_STATIONS__", "__FACTORY_WEEKLY__",
                     "state.", "refs.", "runsHref", "drill("):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, text)

    def test_the_renderers_are_not_also_still_in_stations(self):
        """Two copies would drift. stations.js aliases them instead."""
        text = self.read("stations.js")
        self.assertNotIn("function renderMix(", text)
        self.assertNotIn("function renderPareto(", text)
        self.assertIn("var C = window.FactoryCharts", text)


class WeekChartOrderTest(unittest.TestCase):
    """This week's shape above the rows that evidence it."""

    def test_the_charts_come_before_the_source_rows(self):
        text = (DASHBOARD / "week.html").read_text(encoding="utf-8")
        self.assertIn('id="charts"', text)
        self.assertLess(text.index('id="charts"'), text.index('wk-source'))

    def test_the_station_page_offers_a_range(self):
        text = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="rangebar"', text)
        self.assertLess(text.index('id="rangebar"'), text.index('id="stationbar"'))


class DayCalendarTest(unittest.TestCase):
    """Picking a day from a month, not from a strip of buttons.

    The strip listed only days that had data, in one line. It said nothing
    about where a day sat in the month, and a day with no tab was invisible
    because the strip simply did not draw it.
    """

    def script(self):
        return (DASHBOARD / "dailysheet.js").read_text(encoding="utf-8")

    def test_the_page_hosts_a_calendar_not_a_tab_strip(self):
        page = (DASHBOARD / "dailyexcel.html").read_text(encoding="utf-8")
        self.assertIn('id="daycal"', page)
        self.assertNotIn('id="tabbar"', page)

    def test_it_starts_where_the_line_started(self):
        self.assertIn("var CAL_FLOOR = '2026-08-01';", self.script())

    def test_a_day_with_no_tab_is_not_a_control_at_all(self):
        """A disabled button is a control that failed; a day the line did not
        work is not a control. It renders as a span."""
        text = self.script()
        self.assertIn("if (!tab) {", text)
        self.assertIn("return h('span', {", text)

    def test_the_three_kinds_of_nothing_are_told_apart(self):
        """Still to come, before the tracker starts, and the line did not test
        are different facts and the cell says which."""
        text = self.script()
        for kind in ("is-future", "is-before", "is-empty"):
            with self.subTest(kind=kind):
                self.assertIn(kind, text)


class ParetoDrilldownTest(unittest.TestCase):
    """A bar is a question, so it should be answerable.

    The chart could say "794 failures in Other" and offer no way to find out
    what they were — a tooltip with a share and one test name out of thirty,
    and no mention of which station. That is a Pareto as decoration.
    """

    def read(self, name):
        return (DASHBOARD / name).read_text(encoding="utf-8")

    def test_both_pages_have_somewhere_to_put_the_breakdown(self):
        self.assertIn('id="pareto-detail"', self.read("index.html"))
        self.assertIn('id="wk-pareto-detail"', self.read("week.html"))

    def test_the_breakdown_is_rendered_by_the_shared_library(self):
        """Two implementations would answer "which station" two ways."""
        charts = self.read("charts.js")
        self.assertIn("function renderAreaDetail(", charts)
        self.assertIn("renderAreaDetail: renderAreaDetail", charts)
        for page in ("stations.js", "week.js"):
            with self.subTest(page=page):
                self.assertIn("renderAreaDetail(", self.read(page))

    def test_the_pareto_takes_a_select_handler(self):
        charts = self.read("charts.js")
        self.assertIn("function renderPareto(plot, rows, opts) {", charts)
        self.assertIn("opts.onSelect", charts)

    def test_it_answers_where_what_and_which_units(self):
        charts = self.read("charts.js")
        for question in ("Where it failed", "What failed", "Units most affected"):
            with self.subTest(question=question):
                self.assertIn(question, charts)

    def test_the_tooltip_names_stations_rather_than_one_test(self):
        """Where a failure happens is the first thing anyone asks, and it is
        what decides who owns it."""
        self.assertIn("name: 'stations'", self.read("charts.js"))


class FlowWindowTest(unittest.TestCase):
    """The flow chart counts this week, and says how current it is."""

    def script(self):
        return (DASHBOARD / "flow.js").read_text(encoding="utf-8")

    def test_it_reads_the_week_set(self):
        text = self.script()
        self.assertIn("STATIONS.viewsWeek || STATIONS.views", text)
        self.assertIn("STATIONS.windowWeek || STATIONS.window", text)

    def test_no_reader_is_left_on_the_rolling_set(self):
        """One page, one window. A box drawn from the seven-day views beside a
        heading that says "week to date" is the drift this replaces."""
        self.assertNotIn("(STATIONS.views || {})[", self.script())

    def test_both_ends_are_shown_as_times(self):
        text = self.script()
        self.assertIn("week to date", text)
        self.assertIn("last counted", text)
        self.assertIn("function stamp(iso)", text)


class TableWidthTest(unittest.TestCase):
    """A table's header count must match what its script appends per row.

    The failure mode is silent and total: add a <th> to the markup and forget
    the matching appendChild, and every cell after it shifts one column left for
    every row in the table. Nothing throws, the page renders, and the retest
    rate appears under "Bonepile recovery". This caught nothing when written —
    it is here because the bonepile column was the fourth column added to this
    table and the first three were added by hand on both sides.
    """

    #: page, table id, and the function in the script that builds one row.
    TABLES = [
        ("week.html", "steps-table", "dashboard/week.js", "renderSteps"),
    ]

    def test_header_count_matches_the_cells_appended(self):
        for page, table_id, script, _func in self.TABLES:
            text = (DASHBOARD / page).read_text(encoding="utf-8")
            # the <thead> of that table, and the <th> in it
            start = text.index('id="' + table_id + '"')
            head = text[start:text.index("</thead>", start)]
            headers = re.findall(r"<th\b", head)

            source = (config.REPO_ROOT / script).read_text(encoding="utf-8")
            body = source[source.index("function renderSteps"):]
            body = body[:body.index("\n  function ", 1)]

            # One count per kind of row the function builds, not one for the
            # function: renderSteps builds two — the reported externals (WST,
            # FT) and the measured stations — and only one of them was updated
            # when the bonepile column went in. Splitting on the `var tr =`
            # that starts each row is what surfaces that.
            chunks = body.split("var tr = h('tr'")[1:]
            self.assertTrue(chunks, "no rows built in " + script)
            for index, chunk in enumerate(chunks):
                appends = re.findall(r"\btr\.appendChild\(", chunk)
                with self.subTest(page=page, table=table_id, row_kind=index):
                    self.assertEqual(
                        len(headers), len(appends),
                        "{} declares {} columns; row kind {} in {} appends {} "
                        "cells — every cell after the mismatch shifts left"
                        .format(table_id, len(headers), index, script,
                                len(appends)))


class HashOwnershipTest(unittest.TestCase):
    """Three scripts write one address bar, and they must not erase each other.

    customize.js owns the range keys, searchmode.js owns `mode`, dutsearch.js
    owns `dut`. customize.js writes its hash from scratch on every render, so
    without carrying the other two through, opening a shared
    #mode=dut&dut=... link had the range view drop both on first paint — the
    link worked for about a millisecond. That is the bug this pins.
    """

    OWNED = {
        "customize.js": ["from", "to", "stations", "types", "ran"],
        "searchmode.js": ["mode"],
        "dutsearch.js": ["dut"],
    }

    def source(self, name):
        return (DASHBOARD / name).read_text(encoding="utf-8")

    def test_customize_carries_the_keys_it_does_not_own(self):
        text = self.source("customize.js")
        writer = text[text.index("function writeHash"):]
        writer = writer[:writer.index("\n  }")]
        for key in self.OWNED["searchmode.js"] + self.OWNED["dutsearch.js"]:
            with self.subTest(key=key):
                self.assertIn("'" + key + "'", writer,
                              "writeHash drops " + key + ", so a shared link "
                              "carrying it loses it on the first render")

    def test_each_script_reads_the_key_it_owns(self):
        for name, keys in self.OWNED.items():
            text = self.source(name)
            for key in keys:
                with self.subTest(script=name, key=key):
                    self.assertIn(key + "=", text)


class FlowKindTest(unittest.TestCase):
    """Process stations are not test stations, and the difference is the point.

    A test station judges the DUT: it fails, the unit is held, the failure is in
    the yield. A process station judges the process — the bake, the provisioning
    write, the board build — and when it fails an engineer fixes the line and
    the unit goes round again. Counting those against DUT yield charges the unit
    for the line's problem, so the two must stay distinguishable in the data
    that draws the chart and in the CSV that comes out of it.
    """

    PROCESS = ("tim", "flash", "bft", "pdb")

    def source(self):
        return (DASHBOARD / "flowe2e.js").read_text(encoding="utf-8")

    def node(self, node_id):
        text = self.source()
        at = text.index("id: '" + node_id + "'")
        return text[at:text.index("},", at)]

    def test_the_four_process_stations_are_marked(self):
        for node_id in self.PROCESS:
            with self.subTest(node=node_id):
                self.assertIn("kind: 'process'", self.node(node_id))

    def test_ck_is_gone(self):
        """A checkpoint no controller reported and no unit was held at. A box
        for it put a stage on the chart that existed nowhere else."""
        text = self.source()
        self.assertNotIn("id: 'ck'", text)
        self.assertNotIn("to: 'ck'", text)
        self.assertNotIn("'pdb_ck'", text)

    def test_the_renderer_and_the_stylesheet_know_the_kind(self):
        chart = (DASHBOARD / "flowchart.js").read_text(encoding="utf-8")
        css = (DASHBOARD / "flow.css").read_text(encoding="utf-8")
        self.assertIn("'process'", chart, "the legend must name it")
        self.assertIn(".k-process", css, "an unstyled kind draws as nothing")

    def test_every_node_the_csv_ships_has_a_type(self):
        """The CSV maps node.kind to a Station Type column; a kind with no
        mapping would ship a blank type or a raw internal word."""
        csv_source = (DASHBOARD / "flowcsv.js").read_text(encoding="utf-8")
        mapped = set(re.findall(r"(\w+): '(?:Test|Process|Build|Pack)'",
                                csv_source))
        # NODES only. EDGES uses `kind` too, for how a wire is drawn — "dashed"
        # and "lead" are line styles, not station types, and sweeping the whole
        # file picks them up and asks the CSV to name them.
        text = self.source()
        nodes = text[text.index("var NODES = ["):text.index("var EDGES = [")]
        used = set(re.findall(r"kind: '(\w+)'", nodes))
        self.assertTrue(used, "no kinds found in the chart")
        self.assertEqual(set(), used - mapped,
                         "chart uses kinds the CSV cannot name")


class NavTest(unittest.TestCase):
    """The tab row must be the same row on every page.

    It used to omit the link to the page you were on, which is defensible in the
    abstract — a link to where you already are is a dead control — and wrong in
    practice: the row was a different row on every page, and a reader looking
    for "Weekly tracker" while standing on the weekly page concluded it had been
    removed. A marked-as-current tab costs one slot and makes the set stable.
    """

    def source(self):
        return (DASHBOARD / "nav.js").read_text(encoding="utf-8")

    def block(self, name):
        text = self.source()
        at = text.index("var " + name + " = [")
        return text[at:text.index("\n  ];", at)]

    def links(self, name=None):
        """Every destination the nav offers. Both blocks by default: a page
        behind More is folded, not removed, and a test that read only the
        visible row would call a folded page unreachable."""
        names = [name] if name else ["LINKS", "MORE"]
        out = []
        for each in names:
            out.extend(re.findall(r"\['([^']+)',\s*'([^']+)'",
                                  self.block(each)))
        return out

    def test_every_page_with_a_masthead_renders_the_nav(self):
        for page in sorted(DASHBOARD.glob("*.html")):
            text = page.read_text(encoding="utf-8")
            if "masthead" not in text:
                continue                       # a redirect stub
            with self.subTest(page=page.name):
                self.assertIn('id="nav"', text)
                self.assertIn('src="nav.js"', text)

    #: A DOM small enough to run nav.js against, so this tests what the page
    #: does rather than what its source says. Checking for the absence of one
    #: particular line let a differently-spelled `return` back in.
    SHIM = """
var KNOWN_IDS = ['nav'];
function El(t){ this.tag=t; this.attrs={}; this.kids=[]; this._text=''; }
Object.defineProperty(El.prototype,'textContent',{
  get:function(){ return this._text; },
  set:function(v){ this._text = String(v); }});
Object.defineProperty(El.prototype,'innerHTML',{
  get:function(){ return ''; }, set:function(v){ if(!v) this.kids=[]; }});
El.prototype.setAttribute=function(k,v){ this.attrs[k]=v; };
El.prototype.appendChild=function(n){ this.kids.push(n); return n; };
var REG={};
var document={ createElement:function(t){ return new El(t); },
  getElementById:function(id){
    return KNOWN_IDS.indexOf(id)===-1 ? null : (REG[id]||(REG[id]=new El('nav')));
  },
  addEventListener:function(){} };
var location={ pathname:'/%s', hash:'' };
"""

    def render_nav(self, page):
        """nav.js's own output for a page, as (label, is_current) pairs."""
        harness = (self.SHIM % page) + self.source() + """
JSON.stringify(document.getElementById('nav').kids.map(function (a) {
  return [a.textContent.replace(' \u2192',''),
          /current/.test(a.attrs['class'] || '')];
}));
"""
        try:
            got = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", harness],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest("no JavaScript runtime: {}".format(exc))
        if got.returncode:
            self.fail("nav.js would not run: " + got.stderr)
        return json.loads(got.stdout)

    def test_the_current_page_appears_and_is_marked(self):
        """The behaviour, not the spelling. Every page must render a tab for
        itself, marked current — that is the property that keeps the row the
        same row everywhere."""
        for page, label in (("index.html", "Station yield"),
                            ("weekly.html", "Weekly tracker"),
                            ("doe.html", "Result types"),
                            ("flow.html", "Test flow")):
            rendered = self.render_nav(page)
            names = [name for name, _ in rendered]
            marked = [name for name, current in rendered if current]
            with self.subTest(page=page):
                self.assertIn(label, names,
                              page + " does not render its own tab")
                self.assertEqual([label], marked,
                                 "exactly one tab should be marked current")

    def test_the_row_is_the_same_row_everywhere(self):
        """Bar the per-page exclusions, which are deliberate and listed."""
        base = [name for name, _ in self.render_nav("index.html")]
        for page in ("weekly.html", "doe.html", "flow.html", "rack2.html"):
            with self.subTest(page=page):
                self.assertEqual(base, [n for n, _ in self.render_nav(page)])

    def test_the_majors_are_all_there(self):
        """The pages people asked to always see. A page reachable only from one
        other page is a page nobody finds."""
        targets = [href for href, _ in self.links()]
        for wanted in ("index.html", "weekly.html", "dailyexcel.html",
                       "customize.html", "customize.html#section=errors",
                       "flow.html", "doe.html", "releases.html", "rack2.html"):
            with self.subTest(target=wanted):
                self.assertIn(wanted, targets)

    def test_the_reference_pages_are_folded_not_dropped(self):
        """Releases, Hourly, Requests and OCP live behind More — the row was
        thirteen tabs and wrapped on a laptop. Folded, so still one click from
        every page, which is the thing that must not regress."""
        folded = [href for href, _ in self.links("MORE")]
        self.assertEqual(["releases.html", "hourly.html", "requests.html",
                          "ocp.html"], folded)
        visible = [href for href, _ in self.links("LINKS")]
        for href in folded:
            with self.subTest(page=href):
                self.assertNotIn(href, visible, "in both rows at once")

    def test_the_daily_reading_stays_visible(self):
        """What must not end up behind a click: the pages people open to see
        how the line is doing, as opposed to answer a specific question."""
        visible = [href for href, _ in self.links("LINKS")]
        for wanted in ("index.html", "weekly.html", "dailyexcel.html",
                       "customize.html#section=errors", "flow.html",
                       "doe.html"):
            with self.subTest(page=wanted):
                self.assertIn(wanted, visible)

    def test_every_target_exists(self):
        for href, label in self.links():
            page = href.split("#")[0]
            with self.subTest(link=label):
                self.assertTrue((DASHBOARD / page).exists(),
                                label + " points at " + page + ", which is not "
                                "in dashboard/")

    def test_the_error_codes_deep_link_brings_its_own_answer(self):
        """That section sits inside the RUN-gated output, so a bare fragment
        would land on a page where the table it names is invisible."""
        customize = (DASHBOARD / "customize.js").read_text(encoding="utf-8")
        self.assertIn("section=errors", customize,
                      "customize.js must recognise the deep link")
        self.assertIn("deepLink", customize)
