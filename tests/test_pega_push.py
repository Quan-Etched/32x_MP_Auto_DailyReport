"""tools/pega_push.sh: which cache entries get sent to the dashboard host.

The box cannot read pega3/4/5 — 46 bytes a second over a DERP relay — so the
cache is warmed on a laptop and pushed. What makes that a real mechanism rather
than a hopeful one is choosing correctly WHAT to send, and the obvious answers
are both wrong:

* everything, every hour, is 97 MB over a link that has already failed to carry
  it three times in a row;
* everything newer than the box's latest entry is *nothing*, because the box
  writes its own pega2 and pega6 entries on every build, so its newest
  timestamp is always about now. That version was written, and it would have
  silently pushed an empty delta forever.

So it goes by name: the cache is keyed by a hash of host and URL, and a name
the box does not have is an entry it does not have. Exercised here with `ssh`
stubbed on PATH, because the failure being guarded against is a delta that
looks fine and is empty.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pega_push.sh"


class PushPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

        # A repo-shaped directory: the script resolves itself from tools/.
        self.repo = self.home / "repo"
        (self.repo / "tools").mkdir(parents=True)
        (self.repo / "data" / "raw" / "pega").mkdir(parents=True)
        (self.repo / "data" / "logs").mkdir(parents=True)
        shutil.copy(SCRIPT, self.repo / "tools" / "pega_push.sh")
        shutil.copy(ROOT / "tools" / "lock.sh", self.repo / "tools" / "lock.sh")

        self.bin = self.home / "bin"
        self.bin.mkdir()

    def cache(self, *names):
        for name in names:
            (self.repo / "data" / "raw" / "pega" / name).write_text("{}")

    def stub_ssh(self, listing, ok=True):
        """A fake `ssh` that answers the box's `ls` with `listing`."""
        script = self.bin / "ssh"
        if ok:
            # A heredoc, so the names arrive as real lines. `printf "%s"` does
            # not expand backslash escapes in its argument, and a stub that
            # emitted one line of literal "\n" made every entry look missing —
            # which is a test passing for the wrong reason waiting to happen.
            body = ("cat <<'__LS__'\n" + "".join(n + "\n" for n in listing)
                    + "__LS__\nexit 0\n")
        else:
            body = "exit 255\n"
        script.write_text("#!/bin/bash\n" + body)
        script.chmod(0o755)

    def plan(self):
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env["PATH"]
        env["FACTORY_DEPLOY_HOST"] = "fake@box"
        env["FACTORY_DEPLOY_PATH"] = "repo"
        proc = subprocess.run(
            ["bash", str(self.repo / "tools" / "pega_push.sh"), "--plan"],
            capture_output=True, text=True, cwd=str(self.repo), env=env,
            timeout=60)
        return proc.stdout

    def test_it_sends_only_what_the_box_does_not_have(self):
        self.cache("aaa.json", "bbb.json", "ccc.json")
        self.stub_ssh(["aaa.json", "bbb.json"])
        out = self.plan()
        self.assertIn("data/raw/pega/ccc.json", out)
        self.assertNotIn("aaa.json", out)
        self.assertNotIn("bbb.json", out)
        self.assertIn("would send 1 entries", out)

    def test_a_box_that_is_already_current_gets_nothing(self):
        """The case the timestamp version got right by accident and the case
        it got wrong the rest of the time."""
        self.cache("aaa.json", "bbb.json")
        self.stub_ssh(["aaa.json", "bbb.json"])
        self.assertIn("nothing to send", self.plan())

    def test_a_box_newer_than_this_laptop_still_receives_what_it_lacks(self):
        """The bug that killed the timestamp approach: the box's own entries
        are newer than everything here, and it is still missing ours."""
        self.cache("mine.json")
        os.utime(self.repo / "data" / "raw" / "pega" / "mine.json",
                 (1, 1))                      # ancient, 1970
        self.stub_ssh(["theirs.json"])        # box has a different, newer set
        out = self.plan()
        self.assertIn("data/raw/pega/mine.json", out,
                      "an old local entry the box lacks must still be sent")

    def test_an_unreachable_box_falls_back_to_sending_everything(self):
        """Better a big transfer that might work than a confident empty one."""
        self.cache("aaa.json", "bbb.json")
        self.stub_ssh([], ok=False)
        out = self.plan()
        self.assertIn("data/raw/pega/aaa.json", out)
        self.assertIn("data/raw/pega/bbb.json", out)

    def test_an_empty_listing_is_treated_as_unreadable_not_as_an_empty_box(self):
        """`ls` printing nothing is far more likely to be a broken connection
        than a box with no cache at all, and the two want opposite actions."""
        self.cache("aaa.json")
        self.stub_ssh([])
        self.assertIn("data/raw/pega/aaa.json", self.plan())

    def test_it_sets_its_own_pythonpath(self):
        """launchd runs the script, not `make`.

        The Makefile exports PYTHONPATH=src, so `make pega-push` worked by hand
        while every scheduled run died on "No module named 'factory'" and
        exited 2 having sent nothing — the exact shape of a job that looks
        installed and does nothing. hourly_refresh.sh sets it for the same
        reason; found by running the script the way launchd does instead of
        the way a person does.
        """
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('export PYTHONPATH="$REPO/src"', text)
        # And before the first use of the module it needs.
        self.assertLess(text.index("export PYTHONPATH"),
                        text.index("factory.cli"))

    def test_the_plan_changes_nothing(self):
        self.cache("aaa.json")
        self.stub_ssh(["aaa.json"])
        self.plan()
        stray = [p.name for p in (self.repo / "data" / "logs").iterdir()
                 if p.name.startswith(".pega_push.theirs")]
        self.assertEqual(stray, [], "the listing scratch files are cleaned up")


if __name__ == "__main__":
    unittest.main()
