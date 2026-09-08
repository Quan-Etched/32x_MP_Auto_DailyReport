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


class DirtyTest(unittest.TestCase):
    """Whether a published page came from a real commit.

    The flag had been on for every page the box ever published, which is the
    same as being off. `git describe --dirty` counts any tracked difference,
    and the deploy excludes `data/` and `dashboard/data/` on purpose — the
    box's collected history and its generated bundles are its own. Three files
    committed here and never sent (two reconciliation CSVs and the line's
    workbook) therefore read on the box as a modified tree for ever.

    So the question is asked of the files the deploy actually carries.
    """

    def setUp(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from factory import config

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.addCleanup(setattr, config, "REPO_ROOT", config.REPO_ROOT)
        config.REPO_ROOT = self.root

        def git(*args):
            subprocess.run(("git",) + args, cwd=str(self.root), check=True,
                           capture_output=True)

        git("init", "-q")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        for path in ("data", "dashboard/data"):
            (self.root / path).mkdir(parents=True)
            (self.root / path / "kept.csv").write_text("a\n", encoding="utf-8")
        git("add", "-A")
        git("-c", "commit.gpgsign=false", "commit", "-qm", "first")

    def test_a_clean_checkout_is_clean(self):
        self.assertFalse(version._dirty())

    def test_a_file_the_deploy_never_sends_does_not_dirty_the_tree(self):
        """Deleted, which is exactly how it looks on the box: committed here,
        excluded from the rsync, so absent there."""
        (self.root / "dashboard" / "data" / "kept.csv").unlink()
        (self.root / "data" / "kept.csv").write_text("b\n", encoding="utf-8")
        self.assertFalse(version._dirty(),
                         "an excluded path is excluded on purpose")

    def test_a_modified_source_file_does(self):
        (self.root / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
        self.assertTrue(version._dirty(),
                        "this is the case the flag exists for")

    def test_an_untracked_file_is_not_a_modified_source(self):
        """The box writes several by design — its trace bundles, its own dated
        exports — and none of them is code that came from no commit."""
        (self.root / "src" / "scratch.txt").write_text("hi\n", encoding="utf-8")
        self.assertFalse(version._dirty())

    def test_the_exclusions_match_what_the_deploy_excludes(self):
        """Two lists, one meaning. If deploy.sh stops sending a path and this
        does not know, every page goes back to reporting a dirty tree."""
        from pathlib import Path
        script = (Path(__file__).resolve().parents[1]
                  / "tools" / "deploy.sh").read_text(encoding="utf-8")
        for path in version.NOT_DEPLOYED:
            self.assertIn("--exclude '{}/'".format(path), script,
                          "{} is not excluded by the deploy".format(path))


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
