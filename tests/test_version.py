"""Build provenance shown on the page.

The interesting part is not `git describe` — it is turning whatever form a
remote takes into something a browser can open. This repo's origin is
`git@github.com:...`, which is not a link.
"""

import unittest

from factory import version


class WebUrlTest(unittest.TestCase):
    def test_scp_style_ssh_remote_becomes_a_browsable_url(self):
        self.assertEqual(
            version.web_url("git@github.com:etched-ai/factory_data_analysis.git"),
            "https://github.com/etched-ai/factory_data_analysis")

    def test_ssh_scheme_remote_becomes_a_browsable_url(self):
        self.assertEqual(
            version.web_url("ssh://git@github.com/etched-ai/analysis.git"),
            "https://github.com/etched-ai/analysis")

    def test_https_remote_is_left_alone_apart_from_the_suffix(self):
        self.assertEqual(
            version.web_url("https://github.com/etched-ai/analysis.git"),
            "https://github.com/etched-ai/analysis")

    def test_a_path_remote_is_not_a_link_and_says_so(self):
        # A local clone has no web address; inventing one would produce a link
        # that 404s for everyone who clicks it.
        self.assertIsNone(version.web_url("/srv/git/analysis.git"))
        self.assertIsNone(version.web_url(None))
        self.assertIsNone(version.web_url(""))


class DescribeTest(unittest.TestCase):
    def test_it_describes_this_checkout_without_raising(self):
        got = version.describe()
        for field in ("release", "commit", "dirty", "repo", "commitUrl"):
            self.assertIn(field, got)
        self.assertIsInstance(got["dirty"], bool)
        self.assertIsInstance(got["commitsSinceRelease"], int)

    def test_a_tree_without_git_still_builds(self):
        # A copy shipped without history must publish a page, not fail one.
        self.addCleanup(setattr, version, "_git", version._git)
        version._git = lambda *args: None
        got = version.describe()
        self.assertIsNone(got["commit"])
        self.assertIsNone(got["release"])
        self.assertIsNone(got["commitUrl"])
        self.assertFalse(got["dirty"])

    def test_commit_url_needs_both_a_remote_and_a_commit(self):
        self.addCleanup(setattr, version, "_git", version._git)
        version._git = lambda *args: "abc1234" if args[0] == "rev-parse" else None
        self.assertIsNone(version.describe()["commitUrl"])


if __name__ == "__main__":
    unittest.main()
