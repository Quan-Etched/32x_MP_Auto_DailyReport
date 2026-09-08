"""Which build of this repo produced a page.

WHY A PAGE NEEDS THIS
---------------------
The dashboard is published from a working copy that is rsynced by hand, so
"what is on the site" and "what is on main" drift silently and nothing on the
page says so. A reader looking at a number cannot tell whether they are seeing
the version that lists every failure on a unit or the one that listed the first,
and those give different answers to the same question.

So the header carries the release, the commit and a link to it. If the site says
``v0.4 · 0ac933d`` and the repo has moved on, that is visible rather than
inferred.

READ FROM GIT, NOT WRITTEN DOWN
-------------------------------
A version constant in a source file is a promise someone has to remember to
keep, and the first missed bump makes every later reading wrong. This asks git
instead: the nearest tag, the commit, and whether the tree was dirty when the
bundle was built. A dirty tree is worth showing — it means the published page
came from something that is not any commit at all.

Everything degrades to ``None``: a copy without git, or without history, still
builds and simply says nothing about its version rather than failing or
guessing.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional

from . import config

#: git is not on the critical path; a slow or missing one must not stall a build.
TIMEOUT = 5.0


def _git_output(*args: str) -> Optional[str]:
    """What git printed, or None if it could not be asked.

    Distinct from :func:`_git` in one way that matters: an empty answer comes
    back as "" rather than as None. `git status --porcelain` on a clean tree
    prints nothing, and reading that as "git could not say" turned a clean
    checkout into an unknown one — the published pages carried `dirty: null`
    for exactly as long as it took to notice.
    """
    try:
        result = subprocess.run(
            ("git",) + args,
            cwd=str(config.REPO_ROOT),
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git(*args: str) -> Optional[str]:
    """A git answer that has content, or None. Every caller here wants a value
    it can print, so "nothing to say" and "could not ask" are the same."""
    return _git_output(*args) or None


def web_url(remote: Optional[str]) -> Optional[str]:
    """An https URL a browser can open, from whatever form the remote takes.

    ``git@github.com:etched-ai/factory_data_analysis.git`` is not a link, and it
    is the form this repo's remote is in.
    """
    if not remote:
        return None
    url = remote.strip()
    if url.startswith("git@"):
        host, _, path = url[4:].partition(":")
        url = "https://{}/{}".format(host, path)
    elif url.startswith("ssh://git@"):
        url = "https://" + url[len("ssh://git@"):]
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url if url.startswith("http") else None


#: Paths the deploy does not ship, and so cannot make a published page wrong.
#:
#: `tools/deploy.sh` excludes these deliberately — the box's collected history
#: and generated bundles are its own, and overwriting them with a laptop's
#: would be the bug rather than the fix. The consequence for this module is
#: that a tracked file under one of them is *absent* on the box for a good
#: reason, and `git describe --dirty` cannot tell that from a modified source
#: file.
#:
#: It had been reading every published page as dirty since the box was set up:
#: two hand-exported reconciliation CSVs under dashboard/data/ and the line's
#: workbook under data/, all three committed here, none of them ever sent. A
#: flag that is permanently on says nothing, and this one is load-bearing — it
#: is how a reader is told the page in front of them came from no commit at
#: all. So it is asked of the files the deploy actually carries.
#:
#: Keep in step with the --exclude list in tools/deploy.sh.
NOT_DEPLOYED = ("data", "dashboard/data")


def _dirty() -> Optional[bool]:
    """Whether anything the deploy *ships* differs from HEAD.

    Tracked changes only: an untracked file is not a modified source, and the
    box writes several by design (its trace bundles, its own dated exports).
    None where git cannot say, which is the same answer the rest of this module
    gives in that case.
    """
    status = _git_output("status", "--porcelain", "--untracked-files=no",
                         "--", ".", *(":(exclude){}".format(path)
                                      for path in NOT_DEPLOYED))
    if status is None:
        return None
    return bool(status)


def describe() -> Dict[str, Any]:
    """Release, commit and repository, or Nones where git cannot say."""
    commit = _git("rev-parse", "--short", "HEAD")
    # --tags so a lightweight tag counts; --always so a repo with no tag at all
    # still reports the commit rather than nothing.
    described = _git("describe", "--tags", "--always", "--dirty")
    exact = _git("describe", "--tags", "--exact-match", "HEAD")
    remote = web_url(_git("remote", "get-url", "origin"))

    # `describe` reports the nearest tag plus a distance (v0.4-3-gabc1234);
    # the release is the tag part, and being past it is worth showing.
    release = None
    ahead = None
    if described:
        head = described.split("-dirty")[0]
        parts = head.split("-")
        if len(parts) >= 3 and parts[-1].startswith("g"):
            release, ahead = "-".join(parts[:-2]), parts[-2]
        elif exact:
            release = exact
        elif not described.startswith(str(commit or "")):
            release = head

    return {
        "release": release,
        "commit": commit,
        "commitsSinceRelease": int(ahead) if ahead and ahead.isdigit() else 0,
        # Asked of the deployed files rather than read off `describe`, which
        # counts paths the deploy excludes on purpose. See NOT_DEPLOYED.
        "dirty": _dirty(),
        "repo": remote,
        "commitUrl": "{}/commit/{}".format(remote, commit) if remote and commit else None,
        "releaseUrl": "{}/releases/tag/{}".format(remote, release)
                      if remote and release else None,
    }
