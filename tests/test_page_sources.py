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


def data_scripts(name):
    text = (DASHBOARD / name).read_text(encoding="utf-8")
    return re.findall(r'src="(data/[a-z0-9_]+\.js)"', text)


class PageSourceTest(unittest.TestCase):
    def test_each_page_loads_exactly_its_own_bundle(self):
        for page, bundle in EXPECTED.items():
            with self.subTest(page=page):
                self.assertEqual(data_scripts(page), [bundle])

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


if __name__ == "__main__":
    unittest.main()
