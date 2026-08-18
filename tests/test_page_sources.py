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
    "l10.html": "data/l10daily.js",
    "weekly.html": "data/weekly.js",
    "week.html": "data/weekly.js",
    "flow.html": "data/pega_stations.js",
    "retest.html": "data/retest.js",
}

#: Addresses that were handed out and must keep resolving.
REDIRECTS = {"direct.html": "index.html", "directruns.html": "runs.html",
             "fpy.html": "week.html"}


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
    """The Retested DUT SN column and its F/P traces.

    It was drawn only in Count all, on the assumption that Count new has no
    returning units to put in it. A row is kept as new input when it is new at
    *any* station, so on 08-16 all sixteen shown rows are returning to MLT and
    fresh to HTT — their earlier attempts existed and the one column that shows
    them was switched off by the mode.
    """

    def script(self):
        return (DASHBOARD / "dailysheet.js").read_text(encoding="utf-8")

    def test_the_column_follows_the_data_not_the_mode(self):
        text = self.script()
        self.assertNotIn("var splitSerial = countMode === 'all';", text)
        self.assertIn("var splitSerial = rows.some(", text)

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
