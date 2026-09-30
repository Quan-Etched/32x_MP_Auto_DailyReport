#!/usr/bin/env python3
"""Rebuild Daily FA from the controllers and copy it to the review server.

The review host cannot reach pega, so the bundles have to be built on a
machine that can and then copied. ``python -m factory.cli dailyexcel`` writes
``dashboard/data/dailyexcel.js`` and ``dailyfa.js``. That rebuild downloads
each failed run's ``log.jsonl`` and puts every TH error code into the Daily
FA rows. This copies both bundles to ``REVIEW_HOST`` (the same target as
``make review-data``).

    python tools/review_refresh.py

A log is appended to ``data/logs/review_refresh.log``. Exit 1 means the
rebuild failed; exit 3 means the rebuild worked and the copy did not.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "data" / "logs" / "review_refresh.log"
BUNDLES = (
    REPO / "dashboard" / "data" / "dailyexcel.js",
    REPO / "dashboard" / "data" / "dailyfa.js",
)

HOST = os.environ.get(
    "REVIEW_HOST", "quan@production-failure-analysis.usw2.i.etched.com")
REMOTE_DIR = os.environ.get("REVIEW_DIR", "factory_data_analysis")


def _log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write("{} {}\n".format(stamp, line))
    print(line, flush=True)


def _run(argv: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    _log("$ " + " ".join(argv))
    proc = subprocess.run(
        argv,
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
    )
    text = (proc.stdout or "") + (proc.stderr or "")
    if text.strip():
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    _log("exit {}".format(proc.returncode))
    return proc


def refresh() -> int:
    """Rebuild both bundles, then copy them. Returns a process exit code."""
    env = os.environ.copy()
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"]
                               if env.get("PYTHONPATH") else "")
    _log("---- refresh start ----")
    built = _run([sys.executable, "-m", "factory.cli", "dailyexcel"], env)
    if built.returncode != 0:
        return 1
    missing = [path.name for path in BUNDLES if not path.is_file()]
    if missing:
        _log("missing after build: {}".format(", ".join(missing)))
        return 1
    remote = "{}:{}/dashboard/data/".format(HOST, REMOTE_DIR)
    copied = _run([
        "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
        *[str(path) for path in BUNDLES],
        remote,
    ])
    if copied.returncode != 0:
        return 3
    _log("---- refresh ok ----")
    return 0


def main() -> int:
    return refresh()


if __name__ == "__main__":
    sys.exit(main())
