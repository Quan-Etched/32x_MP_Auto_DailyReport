"""Which suite YAML each station runs, reverse-engineered from the sw tree.

THE QUESTION
------------
The releases page can already say what a *release* contains, because a factory
suite name carries the commit it was built from and MLT and HTT each have one
file somebody wrote down. Every other station has neither. Nothing on any page
says which file in ``etched-ai/sw`` defines the L10 FAT suite, or the VBB
provisioning sequence, or what the 300 runs the line calls ``slt`` were
actually running — and the file is where a limit, a timeout and a test's
existence are decided. Asking "why did this stage change" without it means
reading a diff of results and guessing at the cause.

So this derives the whole map: for each station in the registry, the suite
config in ``host/system_test/test_configs/suite_configs/`` that produced its
runs, how we know, and how the cases that file defines compare to the cases the
logs actually show.

WHY IT HAS TO BE DERIVED
------------------------
Neither side carries the other's name. A suite config does not say which
station runs it: the closest it comes is a ``run_name``, which is a label for
an output folder. And a run does not say which file it came from: EOS reports
the test class, a controller reports the suite it ran under, and both of those
are strings a deploy step chose. ``rdqs_sweep_training`` is HTT; nothing in
either system says so, and grepping the whole sw repository for "htt" returns
nothing at all.

What does exist is a chain of small facts, each checkable, running from the
file to the string the logs carry:

``deploy_suite(suite_config=…, suite_name=…)``
    In ``host/system_test/BUILD``. The strongest link there is: it names the
    file and the ``suite_name`` the deployed suite reports under, which is
    exactly the string a log row shows. Six suites are deployed this way.
A release script that pins a path
    ``make_esvm_config._DEFAULT_SUITE_PATH`` is the suite MLT releases are
    built from, and ``make_mlt_release._SUITE_NAME`` is the name they report
    under. ``run_chip_screening.py`` pins the same file for the SLT bench, and
    ``deploy/L10/deploy_lib.DEFAULT_SUITE`` pins L10's default.
A ``suite_name`` in the file itself
    Only three suites declare one, and one of them is HTT's.
A ``run_name`` in the file
    Every suite has one. It is a folder label, not an identifier — but the VBB
    station's nine suites report under theirs verbatim.
The filename
    Last resort, and the form the pega2 controller happens to use.

Each of those is read out of the tree rather than copied into this file, so a
rename in sw shows up here as a suite that stopped matching instead of a
mapping that quietly went stale. The tier that produced each match travels with
it to the page: a mapping is only worth as much as the fact behind it, and
"the filename looked right" and "the build file says so" should never render
the same.

WHAT IT CANNOT DO
-----------------
The tree is read at HEAD, while the logs span weeks of releases. So a case the
file defines and no log shows may be new, may be unreachable, or may have run
before the window; and a case the logs show that the file does not define may
have been dropped, or may belong to a suite that has since been split. Both
sets are reported, neither is called a defect. The per-release section above
this one is the place where the comparison *is* exact, because there the file
is read at the release's own commit.
"""

from __future__ import annotations

import collections
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import config, pega, pega_collect, stations

#: Where the suite configs live, relative to the sw workspace root.
SUITE_ROOT = "host/system_test/test_configs/suite_configs"

#: The BUILD file that carries the deploy and packaging topology.
BUILD_FILE = "host/system_test/BUILD"

#: How BUILD spells a suite path: relative to its own package, not the
#: workspace. The two forms have to be converted at every crossing.
BUILD_PREFIX = "test_configs/suite_configs/"

#: The per-package documentation table, which is the only place a package is
#: tied to a named production line.
PACKAGES_DOC = "host/system_test/docs/PACKAGES.md"

#: Paths under suite_configs/ that are the harness testing itself.
NOT_A_LINE = ("demo/",)

#: The evidence ladder, strongest first. The page renders these as the "how we
#: know" column, so the order here is the order of the legend.
TIERS: Tuple[Tuple[str, str, str], ...] = (
    ("pinned", "Pinned in a script",
     "A release or deploy script names this file as the suite it builds from, "
     "and the name it reports under."),
    ("deployed", "Deployed by BUILD",
     "host/system_test/BUILD deploys this file under the suite_name the logs "
     "carry."),
    ("declared", "Declared in the file",
     "The file's own top-level suite_name is the string the logs carry."),
    ("run_name", "Matches its run_name",
     "The file's run_name — a label for an output folder, not an identifier — "
     "is the string the logs carry."),
    ("filename", "Matches its filename",
     "Only the filename matches. The weakest link, and the form the pega2 "
     "controller uses."),
    ("registry", "Via the station registry",
     "Neither name reaches the other, but this repo's station registry maps "
     "both spellings to one station — and only one file in the tree resolves "
     "there. An assertion of ours, not a fact read out of sw."),
    ("variant", "A suffixed variant",
     "The name is a suite in the tree plus an operator's suffix "
     "(…_HSM_Failed, …_no_CDU). The base suite is the definition; what the "
     "suffix changed is not in the tree."),
)

#: Nothing sits below ``variant``. A suite the tree packages that no run names
#: is not a weaker mapping, it is the absence of one — reported as its own list
#: rather than as a tier, which would put it on the same ladder as the rest.
TIER_ORDER = {key: index for index, (key, _label, _note) in enumerate(TIERS)}

#: ``deploy_suite(bom=…, suite_config=…, suite_name=…)`` in BUILD.
DEPLOY_SUITE = re.compile(
    r'deploy_suite\(\s*'
    r'bom\s*=\s*"(?P<bom>[^"]+)"\s*,\s*'
    r'suite_config\s*=\s*"(?P<config>[^"]+)"\s*,\s*'
    r'suite_name\s*=\s*"(?P<name>[^"]+)"',
    re.S)

#: A ``"path": ":package"`` pair inside ``runner_by_suite_config_path``.
RUNNER_PAIR = re.compile(r'"([^"]+\.yaml)":\s*"(:[\w.-]+)"')

#: A row of the PACKAGES.md table: the package, then the per-line doc it ends
#: with. Read for the line label only — the rest of that table is prose.
PACKAGE_ROW = re.compile(r"^\|\s*`(?P<pkg>[\w.-]+)`[^|]*\|(?P<rest>.*)$", re.M)
PACKAGE_LINE = re.compile(r"lines/(?P<line>[\w.-]+)\.md")

#: Where a station's own release scripts pin a suite path. Each entry is
#: (file, path pattern, name pattern or literal, why) — read out of the tree so
#: a rename in sw breaks the match instead of this mapping.
PINS: Tuple[Tuple[str, str, Optional[str], str, str], ...] = (
    ("host/system_test/scripts/make_esvm_config.py",
     r'_DEFAULT_SUITE_PATH\s*=\s*\(?\s*"([^"]+)"',
     r'_SUITE_NAME\s*=\s*"([^"]+)"',
     "host/system_test/scripts/make_mlt_release.py",
     "make_mlt_release stages the release from make_esvm_config's default "
     "suite and reports it under this suite_name"),
    ("host/system_test/scripts/run_chip_screening.py",
     r'_DEFAULT_SUITE_YAML\s*=\s*\(?\s*"([^"]+)"',
     None,
     "slt",
     "run_chip_screening drives the bare-chip (SLT) and 1x-module (PV1) "
     "benches from this suite by default"),
    # Retired on master by "Delete L10_tests and retire the L10 deploy CI flow"
    # (#22886). Kept listed on purpose: L10_tests runs are still inside the log
    # window, and a pin that stops resolving is reported as a named loss rather
    # than vanishing — which is the whole reason these are read out of the tree
    # instead of transcribed.
    ("host/system_test/deploy/L10/deploy_lib.py",
     r'DEFAULT_SUITE\s*=\s*"([^"]+)"',
     None,
     "L10_tests",
     "deploy/L10/deploy_lib deploys this suite to the RMS by default"),
)

#: A release stamp and anything after it: ``mlt_2026.220.0-git2f1c2f23`` and
#: ``mlt_validation_2026.225.0-gitb937ca2c`` alike reduce to ``mlt``.
RELEASE_STAMP = re.compile(r"[-_]?\d{4}\.\d+\.\d+.*$")

#: The spellings a deploy step or an operator adds around the base name. Each
#: is stripped so the two systems' names for one suite meet in the middle;
#: every one of them is a spelling seen in a real run.
TRIM = (
    (re.compile(r"^debug_only_", re.I), ""),
    (re.compile(r"^dry_?run_", re.I), ""),
    (re.compile(r"^(prod|check)_\d*_?", re.I), ""),
    (re.compile(r"^sohu_", re.I), ""),
    (re.compile(r"_(validation|debug|ci)$", re.I), ""),
    (re.compile(r"_\d{8}$"), ""),            # mlt_20260622 — a dated cut
    (re.compile(r"_\d{1,3}(\.\d+)?$"), ""),  # L10_6U_FAT_195 — a release number
    (re.compile(r"_6u_", re.I), "_"),        # L10_6U_FAT became L10_FAT at 220
    (re.compile(r"_?test_?suite$", re.I), ""),
    (re.compile(r"_tests?$", re.I), ""),
)

#: Levels the registry is asked about when resolving a name through it. Every
#: level any station draws from, since the name alone does not say which.
REGISTRY_LEVELS = ("l6", "module", "slt", "l10", "l11")

#: The shortest identity a variant match may be built on. ``mlt`` is three
#: characters and a prefix of nothing anyone means; ``l10_2u`` is six and is
#: exactly what ``L10_2U_SMOKE`` is a variant of.
MIN_VARIANT_STEM = 6

#: How far back to read the controllers for observed suite names.
DEFAULT_DAYS = 30


# --------------------------------------------------------------- the sw tree

#: Which ref the map describes, in order of preference.
#:
#: NOT the working tree. A laptop's clone sits on whatever branch its owner was
#: last working on — this one was two months behind master on a feature branch —
#: and a station map derived from that describes one engineer's checkout rather
#: than the line. Read at the shared ref and the answer is the same wherever it
#: is built.
REF_CANDIDATES = ("origin/master", "origin/main", "master", "main", "HEAD")


class Tree:
    """The sw tree at one ref, read through git rather than off the disk."""

    def __init__(self, repo: Path, ref: Optional[str] = None) -> None:
        self._repo = repo
        self.ref = ref or self._pick_ref()
        self.commit = self._maybe("rev-parse", "--short", self.ref) or ""
        self.head = self._maybe("rev-parse", "--short", "HEAD") or ""
        self.branch = self._maybe("rev-parse", "--abbrev-ref", "HEAD") or ""
        line = self._maybe("log", "-1", "--format=%ad%x00%s", "--date=short",
                           self.ref) or ""
        self.committed_at, _, self.subject = line.partition("\x00")

    def _pick_ref(self) -> str:
        for candidate in REF_CANDIDATES:
            if self._maybe("rev-parse", "--verify", "--quiet", candidate):
                return candidate
        return "HEAD"

    def _maybe(self, *args: str) -> Optional[str]:
        """One git command, or None. Nothing here is worth failing a build for."""
        from . import build_release_source as brs

        try:
            return brs._git(self._repo, *args).strip() or None  # noqa: SLF001
        except brs.RepoUnavailable:
            return None

    def read(self, relative: str) -> str:
        """One file's contents at the ref, or "" if it is not there."""
        return self._maybe("show", "{}:{}".format(self.ref, relative)) or ""

    def files_under(self, directory: str, suffix: str) -> List[str]:
        listing = self._maybe("ls-tree", "-r", "--name-only", self.ref, "--",
                              directory) or ""
        return sorted(line for line in listing.splitlines()
                      if line.endswith(suffix))

    def describe(self) -> Dict[str, Any]:
        return {
            "ref": self.ref, "commit": self.commit,
            "committedAt": self.committed_at or None,
            "subject": self.subject or None,
            "workingHead": self.head, "workingBranch": self.branch,
            # Worth saying out loud when it is true: it means the files on the
            # builder's disk are not the files this map describes.
            "aheadOfWorkingTree": bool(self.commit and self.head
                                       and self.commit != self.head),
        }


def deployed_suites(tree: Tree) -> Dict[str, Dict[str, str]]:
    """``suite_config`` path -> the ``suite_name`` and BOM BUILD deploys it as.

    The strongest link in the chain: this is the one place that names a file
    and, in the same call, the string its runs report under.
    """
    text = tree.read(BUILD_FILE)
    out: Dict[str, Dict[str, str]] = {}
    for found in DEPLOY_SUITE.finditer(text):
        out[found.group("config")] = {"suiteName": found.group("name"),
                                      "bom": found.group("bom")}
    return out


def runner_packages(tree: Tree) -> Dict[str, str]:
    """``suite_config`` path -> the ``system_test_runner`` package that runs it.

    Every production suite is in this map, including the ones no deploy step
    touches, so it is what tells a suite that never ran apart from a file
    nobody wired up at all.
    """
    text = tree.read(BUILD_FILE)
    head, _, tail = text.partition("runner_by_suite_config_path = {")
    if not tail:
        return {}
    body = tail.partition("\n    },")[0]
    return {path: package for path, package in RUNNER_PAIR.findall(body)}


def package_lines(tree: Tree) -> Dict[str, str]:
    """``package`` -> the production line its per-package doc points at.

    PACKAGES.md is the only place a package is tied to a named line (L10, L11,
    SLT, VBB, STANDALONE). Used as a label, never as a station mapping: a line
    is a family of stations, not one of them.
    """
    out: Dict[str, str] = {}
    for row in PACKAGE_ROW.finditer(tree.read(PACKAGES_DOC)):
        line = PACKAGE_LINE.search(row.group("rest"))
        if line:
            out[":" + row.group("pkg")] = line.group("line")
    return out


def pins(tree: Tree) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Suite paths a release or deploy script names outright, and the ones gone.

    Read out of the scripts rather than copied here: if sw renames the constant
    or repoints it, the pin stops resolving and the suite falls back to a
    weaker tier. A pin transcribed into this file would keep asserting a path
    that no longer exists, which is the failure this design is built to avoid.

    The ones that stopped resolving are returned too, because a pin
    disappearing is itself a finding — it means the strongest evidence this map
    had for a station just went away, and somebody should know which constant
    moved rather than only seeing a confidence drop.
    """
    found: List[Dict[str, str]] = []
    missing: List[Dict[str, str]] = []
    for source, path_pattern, name_pattern, name_source, why in PINS:
        path = re.search(path_pattern, tree.read(source), re.S)
        name = (re.search(name_pattern, tree.read(name_source), re.S)
                if name_pattern else None)
        if not path or (name_pattern and not name):
            missing.append({
                "source": source,
                "constant": path_pattern.split(r"\s*")[0].lstrip("^"),
                "why": why,
                "gone": "the suite path" if not path else "the suite name",
            })
            continue
        suite_name = name.group(1) if name_pattern else name_source
        where = name_source if name_pattern else source
        found.append({"suiteName": suite_name, "path": path.group(1),
                      "source": source, "nameSource": where, "why": why})
    return found, missing


def suite_files(tree: Tree) -> Dict[str, Dict[str, Any]]:
    """Every production suite config in the tree, with the cases it defines.

    Parsed with the same reader the per-release profile uses. A file that
    counted 59 cases in one section of the page and 58 in the other would be
    worse than not having the second section.
    """
    from . import build_release_source as brs

    try:
        import yaml
    except ImportError:                                   # pragma: no cover
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for path in tree.files_under(SUITE_ROOT, ".yaml"):
        relative = path[len(SUITE_ROOT) + 1:]
        if relative.startswith(NOT_A_LINE):
            continue
        try:
            loaded = yaml.safe_load(tree.read(path))
        except Exception as exc:                          # noqa: BLE001
            out[relative] = {"file": relative, "error": str(exc)[:120],
                             "cases": [], "wrappers": []}
            continue
        info = brs.walk_suite(loaded)
        out[relative] = {
            "file": relative,
            "suiteName": info.get("suiteName"),
            "runName": info.get("runName"),
            "cases": [c["name"] for c in info["cases"] if not c["wrapper"]],
            "wrappers": [c["name"] for c in info["cases"] if c["wrapper"]],
            "error": None,
        }
    return out


# ------------------------------------------------------------------ matching

def normalise(name: Optional[str]) -> str:
    """One suite name, reduced to the form the two systems agree on.

    EOS reports the test class, a controller reports the suite it ran under, a
    deploy step stamps a release onto it and an operator adds a variant suffix
    — four spellings of one stage. Everything stripped here is a spelling seen
    in a real run, not a guess at what might turn up.
    """
    text = (name or "").strip()
    if not text:
        return ""
    text = RELEASE_STAMP.sub("", text)
    changed = True
    while changed:
        changed = False
        for pattern, replacement in TRIM:
            reduced = pattern.sub(replacement, text)
            if reduced != text:
                text, changed = reduced, True
    return text.strip("_").lower()


def _candidates(files: Dict[str, Dict[str, Any]],
                deployed: Dict[str, Dict[str, str]],
                pinned: List[Dict[str, str]]) -> Dict[str, List[Tuple[str, str, str]]]:
    """Normalised suite name -> [(tier, file, the fact behind it)].

    Every identity a file could plausibly be recognised by, tagged with how
    much that identity is worth.
    """
    index: Dict[str, List[Tuple[str, str, str]]] = collections.defaultdict(list)

    for pin in pinned:
        relative = pin["path"].split(SUITE_ROOT + "/", 1)[-1]
        if relative in files:
            index[normalise(pin["suiteName"])].append((
                "pinned", relative,
                "{} — {}".format(pin["nameSource"], pin["why"])))

    for path, entry in deployed.items():
        relative = path.split(BUILD_PREFIX, 1)[-1]
        if relative in files:
            index[normalise(entry["suiteName"])].append((
                "deployed", relative,
                '{} deploys it as suite_name "{}"'.format(BUILD_FILE,
                                                          entry["suiteName"])))

    for relative, entry in files.items():
        if entry.get("suiteName"):
            index[normalise(entry["suiteName"])].append((
                "declared", relative,
                'the file declares suite_name: {}'.format(entry["suiteName"])))
        if entry.get("runName"):
            index[normalise(entry["runName"])].append((
                "run_name", relative,
                'the file\'s run_name is "{}"'.format(entry["runName"])))
        stem = relative.rsplit("/", 1)[-1][: -len(".yaml")]
        index[normalise(stem)].append((
            "filename", relative, "the filename matches"))

    # One more identity per file, asserted by this repo rather than read out of
    # sw: the station its own names classify to. It is what closes the HTT gap —
    # the controller reports `htt_<release>` and the file declares
    # `rdqs_sweep_training`, and the only thing that knows those are one stage
    # is the registry. Used only where a single file resolves to the station:
    # nine VBB suites resolve to vbb_provision, and "one of nine" is not
    # evidence about which.
    resolved: Dict[str, Set[str]] = collections.defaultdict(set)
    for relative, entry in files.items():
        stem = relative.rsplit("/", 1)[-1][: -len(".yaml")]
        for identity in (entry.get("suiteName"), entry.get("runName"), stem):
            for level in REGISTRY_LEVELS:
                station = stations.classify(level, identity)
                if station in (stations.UNCLASSIFIED, stations.ENGINEERING):
                    continue
                resolved[station].add(relative)
                # The registry also documents the station key as a *prefix* —
                # `htt_rdqs_sweep_training` turned up on a real run once the
                # HTT suite started carrying one. That is a whole identity
                # rather than a bare station key, so it needs no uniqueness
                # guard.
                index[normalise("{}_{}".format(station, identity))].append((
                    "registry", relative,
                    "the registry accepts this spelling of the file's own "
                    "{} for {}".format(identity, stations.label_of(station))))
    for station, holders in resolved.items():
        if len(holders) != 1:
            continue
        relative = next(iter(holders))
        index[normalise(station)].append((
            "registry", relative,
            "the station registry resolves both this name and the file's own "
            "to {}, and only this file resolves there".format(
                stations.label_of(station))))

    # Where two files claim one name at the same tier, prefer the shallower
    # path. `server/L10/ci/L10_tests.yaml` is the CI variant of
    # `server/L10/L10_tests.yaml`, and a factory run is the second; alphabetical
    # order would pick the first for no reason at all. Both are still reported.
    for key in index:
        index[key].sort(key=lambda hit: (TIER_ORDER[hit[0]],
                                         hit[1].count("/"), hit[1]))
    return index


def _variant_of(name: str, index: Dict[str, List[Tuple[str, str, str]]]
                ) -> Optional[Tuple[str, str, str]]:
    """The suite in the tree that ``name`` is a suffixed variant of.

    ``vbb_setup_provisioning_internal_HSM_Failed`` and
    ``L11_Rack_Power_Cycle_no_CDU`` are somebody's one-off edit of a suite that
    does exist, and pointing at the base file is more use than "unknown". It is
    the weakest tier on the page and says so: the base file is the definition,
    and whatever the suffix changed was never committed.
    """
    best: Optional[Tuple[str, str, str]] = None
    for key, hits in index.items():
        if len(key) < MIN_VARIANT_STEM or not name.startswith(key + "_"):
            continue
        if best is None or len(key) > len(best[0]):
            best = (key, hits[0][1],
                    "a suffixed variant of {}, which the tree does "
                    "define".format(hits[0][1]))
    return (("variant", best[1], best[2]) if best else None)


# ------------------------------------------------------------- what actually ran

def observed(days: int = DEFAULT_DAYS) -> Dict[str, Any]:
    """The suite names and test cases the line produced, from both systems.

    Two independent readings, kept apart. The controllers are the authority on
    which physical station ran a suite — they name it — so they decide which
    station a suite name belongs to. EOS is the only one of the two whose runs
    carry test-*class* names, so it is what the case comparison is built from.
    Neither is asked to stand in for the other.
    """
    today = datetime.now(timezone.utc).date()
    window = [(today - timedelta(days=offset)).strftime("%Y-%m-%d")
              for offset in range(days - 1, -1, -1)]

    suites: Dict[Tuple[str, str], Dict[str, Any]] = {}
    problems: List[str] = []

    for host, _level, _per_slot in pega_collect.HOSTS:
        for day in window:
            try:
                listing = pega.day_suite_runs(day, host=host)
            except pega.PegaUnavailable as exc:
                problems.append("{}: {}".format(host, exc))
                break
            for entry in listing:
                name = (entry.get("suite_name") or "").strip()
                if not name:
                    continue
                station = (pega_collect.station_of(host, name)
                           or _engineering_or_none(name))
                if not station:
                    continue
                row = suites.setdefault((station, name), {
                    "station": station, "suite": name, "runs": 0,
                    "source": host, "stationIds": [], "firstDay": day,
                    "lastDay": day,
                })
                row["runs"] += 1
                row["firstDay"] = min(row["firstDay"], day)
                row["lastDay"] = max(row["lastDay"], day)
                fixture = entry.get("station_id")
                if fixture and fixture not in row["stationIds"]:
                    row["stationIds"].append(fixture)

    cases: Dict[str, Set[str]] = collections.defaultdict(set)
    eos: Dict[str, Any] = {}
    if config.RUNS_JSON.exists():
        try:
            payload = json.loads(config.RUNS_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append("runs.json: {}".format(str(exc)[:120]))
        else:
            eos = {"generatedAt": payload.get("generatedAt"),
                   "window": payload.get("window"),
                   "runs": payload.get("runCount") or len(payload.get("runs") or [])}
            for run in payload.get("runs") or []:
                station = stations.classify(run.get("level"), run.get("suite"))
                name = (run.get("suite") or "").strip()
                if name:
                    row = suites.setdefault((station, name), {
                        "station": station, "suite": name, "runs": 0,
                        "source": "eos", "stationIds": [],
                        "firstDay": None, "lastDay": None,
                    })
                    row["runs"] += 1
                for case in run.get("tests") or []:
                    display = case.get("displayName") or case.get("name")
                    if display:
                        cases[station].add(display)

    return {"suites": sorted(suites.values(),
                             key=lambda r: (r["station"], -r["runs"], r["suite"])),
            "cases": {key: sorted(value) for key, value in cases.items()},
            "eos": eos, "problems": problems, "days": days,
            "window": {"from": window[0], "to": window[-1]}}


def _engineering_or_none(name: str) -> Optional[str]:
    """Keep an engineering suite visible rather than dropping it.

    ``pega_collect.station_of`` returns None for a debug or validation build,
    deliberately — those runs must not land in a station's yield. Here they are
    worth keeping: ``L10_6U_FAT_debug`` is evidence about which file FAT runs
    from, and a suite nobody can place is a question whether it was production
    or not. They are labelled engineering, never counted as a station's.

    A name that is neither production nor recognisably engineering gets None:
    it is a suite this repo has no reading of, and inventing a bucket for it
    would hide that.
    """
    return (stations.ENGINEERING
            if pega_collect.NOT_PRODUCTION.search(name) else None)


# -------------------------------------------------------------------- bundle

def build(repo: Path, days: int = DEFAULT_DAYS,
          seen: Optional[Dict[str, Any]] = None,
          ref: Optional[str] = None) -> Dict[str, Any]:
    """The whole map: station, file, evidence, and how the cases compare."""
    tree = Tree(repo, ref)
    files = suite_files(tree)
    deployed = deployed_suites(tree)
    runners = runner_packages(tree)
    lines = package_lines(tree)
    pinned, unpinned = pins(tree)
    index = _candidates(files, deployed, pinned)
    seen = seen if seen is not None else observed(days)

    # A file can be reached by several stations (chip/parallel/main.yaml is MLT,
    # SLT and chip screening at once), so attribution is per station-and-file.
    attributed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    unmatched: List[Dict[str, Any]] = []

    for row in seen["suites"]:
        reduced = normalise(row["suite"])
        hits = index.get(reduced) or []
        best = hits[0] if hits else _variant_of(reduced, index)
        if not best:
            unmatched.append(dict(row, normalised=reduced))
            continue
        tier, relative, evidence = best
        entry = attributed.setdefault((row["station"], relative), {
            "file": relative, "tier": tier, "evidence": evidence,
            "observed": [], "runs": {},
            "alsoMatches": sorted({hit[1] for hit in hits
                                   if hit[1] != relative}),
        })
        # The strongest evidence any of a station's runs gives for this file.
        if TIER_ORDER[tier] < TIER_ORDER[entry["tier"]]:
            entry.update(tier=tier, evidence=evidence)
        entry["observed"].append({
            "suite": row["suite"], "runs": row["runs"], "source": row["source"],
            "stationIds": row.get("stationIds") or [],
        })
        # Per source, never summed. A run appears once from its controller and
        # again from EOS, under two different suite names — adding them would
        # double every count on the page and make the map look better attested
        # than it is.
        entry["runs"][row["source"]] = (entry["runs"].get(row["source"], 0)
                                        + row["runs"])

    by_station: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for (station, relative), entry in attributed.items():
        detail = files.get(relative, {})
        by_station[station].append(dict(entry, **{
            "path": "{}/{}".format(SUITE_ROOT, relative),
            "suiteName": detail.get("suiteName"),
            "runName": detail.get("runName"),
            "caseCount": len(detail.get("cases") or []),
            "cases": detail.get("cases") or [],
            "wrappers": detail.get("wrappers") or [],
            "error": detail.get("error"),
            "deployedAs": (deployed.get(BUILD_PREFIX + relative)
                           or {}).get("suiteName"),
            "runner": runners.get(BUILD_PREFIX + relative),
            "line": lines.get(runners.get(BUILD_PREFIX + relative, "")),
            "observed": sorted(entry["observed"], key=lambda o: -o["runs"]),
        }))

    registry = {station["key"]: station for station in stations.registry()}
    ordered: List[Dict[str, Any]] = []
    for key in sorted(by_station, key=lambda k: (registry.get(k, {}).get("order", 999), k)):
        suites = sorted(by_station[key],
                        key=lambda s: (TIER_ORDER[s["tier"]], -_runs(s)))
        meta = registry.get(key, {})
        # Not a station: debug builds, dry runs and suites named after whoever
        # was running them. They are kept because they are evidence about which
        # file a station runs — a `_krish` FAT run is still a FAT suite — but
        # their cases are six unrelated files pooled together, so the page must
        # not draw them a coverage bar.
        ordered.append({
            "station": key,
            "label": (meta.get("label")
                      or ("Engineering and debug"
                          if key == stations.ENGINEERING
                          else stations.label_of(key))),
            "controller": meta.get("controller") or "",
            "state": meta.get("state") or (
                stations.ENGINEERING if key == stations.ENGINEERING else ""),
            "order": meta.get("order", 999),
            "runs": _merge_runs(suites),
            "suites": suites,
            "coverage": _coverage(suites, seen["cases"].get(key) or [],
                                  key in seen["cases"]),
        })

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "suiteRoot": SUITE_ROOT,
        "tree": tree.describe(),
        "window": seen["window"],
        "days": seen["days"],
        "tiers": [{"key": key, "label": label, "note": note}
                  for key, label, note in TIERS],
        "pins": pinned,
        "pinsGone": unpinned,
        "eos": seen.get("eos") or {},
        "problems": seen.get("problems") or [],
        "stations": ordered,
        "unmatched": sorted(unmatched, key=lambda r: (r["station"], -r["runs"])),
        "unrun": _unrun(files, attributed, runners, lines),
        "counts": {
            "files": len(files),
            "attributed": len({relative for _station, relative in attributed}),
            "deployed": len(deployed),
            "pinned": len(pinned),
        },
    }


def _runs(suite: Dict[str, Any]) -> int:
    """The largest single reading of a suite's runs, for ordering only."""
    return max((suite.get("runs") or {}).values(), default=0)


def _merge_runs(suites: List[Dict[str, Any]]) -> Dict[str, int]:
    """Runs per source across a station's suites — still never across sources."""
    total: Dict[str, int] = {}
    for suite in suites:
        for source, count in (suite.get("runs") or {}).items():
            total[source] = total.get(source, 0) + count
    return total


def _coverage(suites: List[Dict[str, Any]], seen: Iterable[str],
              readable: bool) -> Dict[str, Any]:
    """The station's YAML cases against the case names its logs carry.

    Both directions are reported and neither is called an error. The tree is at
    HEAD and the logs span weeks, so a case in one set and not the other is a
    question — new, unreachable, dropped, or simply outside the window — and
    which one it is cannot be settled from here.
    """
    from . import build_release_source as brs

    defined: Set[str] = set()
    for suite in suites:
        defined.update(suite["cases"])

    # The YAML side already drops the nesting wrappers — they are the shape of
    # the suite, not tests — but a log carries them, because a nest fails when a
    # leaf under it does. Left in, every station would report ServerNestedTestCase
    # as a case its own suite does not define, which is a bug wearing a finding's
    # clothes.
    logged = set(seen) - set(brs.WRAPPERS)
    return {
        "defined": len(defined),
        "logged": len(logged),
        "exercised": len(defined & logged),
        "dark": sorted(defined - logged),
        "extra": sorted(logged - defined),
        # EOS is the only system whose runs carry test-class names, and it
        # cannot read every level — L11 is an IAM denial. Without it there is
        # nothing to compare against, and reporting every case as unexercised
        # would read as a finding about the line when it is one about our
        # access.
        "comparable": bool(readable and logged),
    }


def _unrun(files: Dict[str, Dict[str, Any]],
           attributed: Dict[Tuple[str, str], Dict[str, Any]],
           runners: Dict[str, str], lines: Dict[str, str]) -> List[Dict[str, Any]]:
    """Production suites in the tree that no run in the window names.

    Kept because the absence is the finding: a suite BUILD packages for a line
    and the line never runs is either dead weight in the tree or a stage
    nobody is measuring, and both are worth someone's attention.
    """
    matched = {relative for _station, relative in attributed}
    out: List[Dict[str, Any]] = []
    for relative, entry in sorted(files.items()):
        if relative in matched:
            continue
        package = runners.get(BUILD_PREFIX + relative)
        out.append({
            "path": "{}/{}".format(SUITE_ROOT, relative),
            "file": relative,
            "suiteName": entry.get("suiteName"),
            "runName": entry.get("runName"),
            "caseCount": len(entry.get("cases") or []),
            "runner": package,
            "line": lines.get(package or ""),
            "packaged": bool(package),
        })
    return out
