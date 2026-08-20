"""What a release *contains*, read from the source it was built from.

THE OTHER HALF OF THE RELEASES PAGE
-----------------------------------
The existing releases view is built from test logs: it knows what ran, how
often, and how it went. It cannot answer the question that comes first — what
was in this release at all — because a test case that was added and never
reached, or removed and so never seen again, leaves no trace in a log. "It
stopped failing" and "it stopped running" look identical from the outside.

So this reads the suite definition out of the sw repository at the exact commit
each release was built from. Every factory suite name carries it:
``mlt_2026.220.0-git2f1c2f23`` is release 2026.220.0 built at 2f1c2f23, and
that abbreviated hash resolves in etched-ai/sw. From the commit comes the suite
YAML, and from the YAML comes the list of test cases the release would run —
whether or not the line ever ran it.

Diffing consecutive releases then says which test cases a release *added* and
which it *dropped*, which is the thing nobody can currently answer without
reading two YAML files side by side.

WHERE THIS CAN RUN
------------------
Only where a clone of etched-ai/sw exists — a 2.4 GB repository the dashboard
host does not have and should not need. So the bundle is generated where the
clone is (a laptop) and committed; the box publishes what it finds. Every step
degrades to "skipped" with a reason rather than failing a build, because the
box will legitimately never be able to do this one.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import build_dailyexcel, config, pega, version

#: Where the sw clone lives. FACTORY_SW_REPO overrides.
DEFAULT_REPO = Path.home() / "project" / "sw"

#: Days of releases to profile.
DEFAULT_DAYS = 7

#: The in-tree suite each factory station's release is generated from.
#:
#: Not guessed: host/system_test/scripts/make_mlt_release.py builds the MLT
#: release from make_esvm_config's default suite, which that file pins to
#: chip/parallel/main.yaml; and the HTT suite deploys rdqs_sweep_training,
#: which is the suite name the station registry already matches HTT on.
SUITE_SOURCE = {
    "mlt": "host/system_test/test_configs/suite_configs/chip/parallel/main.yaml",
    "htt": ("host/system_test/test_configs/suite_configs/chip/hbm/"
            "rdqs_sweep_training.yaml"),
}

#: The release list compiled by hand for 10–18 Aug 2026 (the "MLT & HTT
#: Release Trains" artifact), which read versions out of each run's
#: ``log.jsonl`` rather than out of the source tree.
#:
#: Kept so the two can be compared: a release this profile finds and that list
#: does not is one that ran without producing the logs the hand count walked,
#: and the reverse is a release that ran outside this window. Marked on the
#: page rather than merged, because a hand-compiled list and a generated one
#: should never become indistinguishable.
MANUAL_LIST = {
    "mlt": ("2026.220.0", "2026.225.0"),
    "htt": ("2026.217.0", "2026.223.0", "2026.224.0", "2026.226.0"),
}

MANUAL_LIST_SOURCE = ("hand-compiled release trains, 10–18 Aug 2026, "
                      "read from each run's log.jsonl")

#: The ``2026.225.0`` inside a suite name.
VERSION = re.compile(r"(\d{4}\.\d+\.\d+)")

#: A suite name's trailing ``-git<sha>``.
COMMIT = re.compile(r"-git([0-9a-f]{7,40})\b")

#: Nodes that group other tests rather than being one. Their names are prose
#: ("Setup", "RDQS Attempt 1") or a nesting wrapper, and counting them as test
#: cases would inflate every release by its own structure.
WRAPPERS = ("ServerNestedTestCase", "SltModuleNestedTestCase")


class RepoUnavailable(RuntimeError):
    """No usable clone of sw — the only honest outcome on the dashboard host."""


def repo_path(explicit: Optional[str] = None) -> Path:
    import os

    path = Path(explicit or os.environ.get("FACTORY_SW_REPO") or DEFAULT_REPO)
    if not (path / ".git").exists():
        raise RepoUnavailable(
            "{} is not a git clone of etched-ai/sw — set FACTORY_SW_REPO, or "
            "run this where the clone is (the box does not have one)".format(path))
    return path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(("git", "-C", str(repo)) + args,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RepoUnavailable(result.stderr.strip()[:200] or "git failed")
    return result.stdout


def releases_seen(days: int = DEFAULT_DAYS) -> List[Dict[str, Any]]:
    """The releases the line actually ran, from the controllers.

    Profiling every release in the repository would describe the release train;
    profiling the ones that ran describes the factory. The second is the
    question — and it is what makes this page line up with the others.
    """
    today = datetime.now(timezone.utc).date()
    window = [(today - timedelta(days=offset)).strftime("%Y-%m-%d")
              for offset in range(days - 1, -1, -1)]

    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for day in window:
        try:
            listing = pega.day_suite_runs(day)
        except pega.PegaUnavailable:
            continue
        for entry in listing:
            suite = entry.get("suite_name") or ""
            run_id = entry.get("suite_run_id") or ""
            station = build_dailyexcel.station_of(run_id, suite)
            if station not in SUITE_SOURCE:
                continue
            found = COMMIT.search(suite)
            if not found:
                continue
            key = (station, suite)
            row = seen.setdefault(key, {
                "station": station, "suite": suite,
                "commit": found.group(1), "runs": 0,
                "firstDay": day, "lastDay": day,
            })
            row["runs"] += 1
            row["firstDay"] = min(row["firstDay"], day)
            row["lastDay"] = max(row["lastDay"], day)

    return sorted(seen.values(), key=lambda r: (r["station"], r["firstDay"],
                                                r["suite"]))


def test_cases(repo: Path, commit: str, suite_path: str) -> Dict[str, Any]:
    """Every test case the suite would run at that commit.

    Parsed with PyYAML where it is importable, because the file leans on
    anchors and aliases and a line scanner would silently miss an aliased
    sub-suite. Where it is not, a scanner reads the ``- name:`` entries
    instead: that finds every case the file *defines* but cannot expand an
    alias, so the bundle records which reader was used and the page says so.
    """
    try:
        text = _git(repo, "show", "{}:{}".format(commit, suite_path))
    except RepoUnavailable as exc:
        return {"error": str(exc), "cases": [], "reader": None}

    try:
        import yaml
    except ImportError:
        return dict(_scan(text), reader="scanner")

    try:
        tree = yaml.safe_load(text)
    except Exception as exc:                              # noqa: BLE001
        return dict(_scan(text), reader="scanner",
                    note="yaml parse failed: {}".format(str(exc)[:120]))
    return dict(_walk(tree), reader="yaml")


def _walk(tree: Any) -> Dict[str, Any]:
    """Collect leaf test cases from a suite tree, with where each one sits."""
    cases: Dict[str, Dict[str, Any]] = {}
    groups: List[str] = []

    def visit(node: Any, path: List[str]) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, path)
            return
        if not isinstance(node, dict):
            return

        for key in ("tests_to_run", "tests"):
            children = node.get(key)
            if children:
                name = node.get("name") or node.get("run_name")
                if name:
                    groups.append(name)
                visit(children, path + ([name] if name else []))

        name = node.get("name")
        # A leaf: named, no children, and a class name rather than prose.
        if (name and not node.get("tests") and not node.get("tests_to_run")
                and re.match(r"^[A-Z][A-Za-z0-9]*$", str(name))):
            entry = cases.setdefault(name, {
                "name": name, "count": 0, "wrapper": name in WRAPPERS,
                "where": " / ".join(path) if path else "",
            })
            entry["count"] += 1

        # Sub-suites appear inline under keys the schema does not fix, so any
        # nested mapping is followed rather than a hard-coded list of keys.
        for key, value in node.items():
            if key in ("tests", "tests_to_run"):
                continue
            if isinstance(value, (dict, list)):
                visit(value, path)

    visit(tree, [])
    ordered = sorted(cases.values(), key=lambda c: c["name"])
    return {"cases": ordered, "groups": sorted(set(groups)),
            "suiteName": tree.get("suite_name") if isinstance(tree, dict) else None,
            "runName": tree.get("run_name") if isinstance(tree, dict) else None}


#: The suite-tree reader, under a public name because ``suite_map`` shares it.
#:
#: Both sections of the releases page count a file's test cases, and a file
#: that came out at 59 in one and 58 in the other would be worse than not
#: having the second section at all. One reader, one count.
walk_suite = _walk


def _scan(text: str) -> Dict[str, Any]:
    """Fallback: every ``- name: ClassName`` the file mentions."""
    names = re.findall(r"^\s*-?\s*name:\s*([A-Z][A-Za-z0-9]*)\s*$", text, re.M)
    counts: Dict[str, int] = defaultdict(int)
    for name in names:
        counts[name] += 1
    suite = re.search(r"^suite_name:\s*(\S+)", text, re.M)
    run = re.search(r"^run_name:\s*(.+)$", text, re.M)
    return {
        "cases": [{"name": name, "count": counts[name],
                   "wrapper": name in WRAPPERS, "where": ""}
                  for name in sorted(counts)],
        "groups": [],
        "suiteName": suite.group(1) if suite else None,
        "runName": run.group(1).strip() if run else None,
    }


def build_bundle(days: int = DEFAULT_DAYS,
                 repo: Optional[Path] = None) -> Dict[str, Any]:
    root = repo or repo_path()
    releases = releases_seen(days)

    profiled: List[Dict[str, Any]] = []
    for release in releases:
        station = release["station"]
        source = SUITE_SOURCE[station]
        info = test_cases(root, release["commit"], source)
        cases = [c for c in info.get("cases", []) if not c["wrapper"]]
        commit_meta = _commit_meta(root, release["commit"])
        profiled.append(dict(release, **{
            "source": source,
            "reader": info.get("reader"),
            "error": info.get("error"),
            "note": info.get("note"),
            "suiteName": info.get("suiteName"),
            "runName": info.get("runName"),
            "cases": [c["name"] for c in cases],
            "caseCount": len(cases),
            "wrappers": [c["name"] for c in info.get("cases", []) if c["wrapper"]],
            "committedAt": commit_meta.get("date"),
            "subject": commit_meta.get("subject"),
            "inManualList": _in_manual_list(station, release["suite"]),
        }))

    # Which suite YAML each *station* runs, derived from the same clone. Rides
    # this bundle rather than getting one of its own: both halves are read from
    # sw, both are unbuildable on the dashboard host, and one committed file is
    # one thing to keep current instead of two that can disagree.
    from . import suite_map as _suite_map
    try:
        mapped = _suite_map.build(root)
    except Exception as exc:                              # noqa: BLE001
        mapped = {"error": str(exc)[:200], "stations": []}

    return {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "window": {"days": days},
        "repo": {"path": str(root), "head": _git(root, "rev-parse",
                                                 "--short", "HEAD").strip(),
                 "committedAt": _commit_meta(root, "HEAD").get("date"),
                 "subject": _commit_meta(root, "HEAD").get("subject")},
        "sources": SUITE_SOURCE,
        "suiteMap": mapped,
        "manualList": {"versions": {k: list(v) for k, v in MANUAL_LIST.items()},
                       "source": MANUAL_LIST_SOURCE},
        "releases": profiled,
        "diffs": _diffs(profiled),
    }


def _in_manual_list(station: str, suite: str) -> bool:
    found = VERSION.search(suite)
    return bool(found and found.group(1) in MANUAL_LIST.get(station, ()))


def _commit_meta(repo: Path, commit: str) -> Dict[str, str]:
    try:
        line = _git(repo, "log", "-1", "--format=%ad%x00%s", "--date=short",
                    commit).strip()
    except RepoUnavailable:
        return {}
    date, _, subject = line.partition("\x00")
    return {"date": date, "subject": subject}


def _diffs(profiled: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What each release added and dropped against the one before it.

    Ordered by the commit date rather than by the release number: a validation
    build and a production build can share a number, and 226 can be cut before
    225 reaches the floor.
    """
    out: List[Dict[str, Any]] = []
    by_station: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for release in profiled:
        if release.get("cases") or release.get("caseCount"):
            by_station[release["station"]].append(release)

    for station, items in by_station.items():
        items = sorted(items, key=lambda r: (r.get("committedAt") or "",
                                             r["suite"]))
        for previous, current in zip(items, items[1:]):
            before, after = set(previous["cases"]), set(current["cases"])
            if before == after:
                continue
            out.append({
                "station": station,
                "from": previous["suite"],
                "to": current["suite"],
                "added": sorted(after - before),
                "dropped": sorted(before - after),
                "unchanged": len(before & after),
            })
    return out


#: The committed copy.
#:
#: dashboard/data/ is generated output: gitignored, and excluded from the
#: deploy rsync so a build on the box cannot be clobbered by a laptop's. This
#: bundle is the one thing in there that the box *cannot* generate, so a copy
#: lives outside that directory, is committed, travels with the code, and is
#: copied into place at build time. Without it the section would be
#: permanently empty on the published site and full on the laptop, which is
#: the worst of both.
COMMITTED_COPY = config.REPO_ROOT / "release_profile" / "release_source.js"


def _render(bundle: Dict[str, Any]) -> str:
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    return (
        "// Generated by `python -m factory.cli release-source` — do not edit.\n"
        "// Built where a clone of etched-ai/sw exists; committed so the\n"
        "// dashboard host can publish it without one.\n"
        "window.__FACTORY_RELEASE_SOURCE__ = {};\n".format(body))


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "release_source.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = _render(bundle)
    target.write_text(text, encoding="utf-8")

    if path is None:
        COMMITTED_COPY.parent.mkdir(parents=True, exist_ok=True)
        COMMITTED_COPY.write_text(text, encoding="utf-8")
    return target


def install_committed(dest: Optional[Path] = None) -> Optional[Path]:
    """Put the committed copy where the page looks, if there is one.

    What the dashboard host runs: it has no clone to profile from, so it
    publishes whatever the last laptop build committed.
    """
    if not COMMITTED_COPY.exists():
        return None
    target = dest or (config.DASHBOARD_DATA_DIR / "release_source.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(COMMITTED_COPY.read_text(encoding="utf-8"),
                      encoding="utf-8")
    return target
