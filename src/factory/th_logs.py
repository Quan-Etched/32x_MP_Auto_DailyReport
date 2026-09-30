"""Every TH error code a failed test recorded, read from its ``log.jsonl``.

ESVM's own page keeps one diagnosis per test: the harness writes several
``diagnosis`` records into ``log.jsonl``, and the controller stores the
preferred one on ``error_message``. Daily FA needs the rest of them too.
The review host cannot reach pega, so the daily rebuild downloads the logs
here, on a machine that can, and the codes travel in ``dailyfa.js``.

Only ``log.jsonl`` is read, and only its tail when the file is large. That
is the same file and the same window ESVM uses: the diagnosis is at the end,
and a head-truncated read would drop it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import config, pega

log = logging.getLogger(__name__)

#: Last bytes scanned. Matches ESVM ``_MAX_LOG_BYTES``: the diagnosis is at
#: the end of the file, and a multi-hundred-megabyte transcript is not what
#: the daily bundle is for.
_MAX_LOG_BYTES = 8 * 1024 * 1024

#: How far below a run root a nested suite's log.jsonl can sit.
_MAX_DEPTH = 8

#: Directories walked per run. A fanout is a handful; this stops a stray
#: tree from turning one failed chassis into a crawl.
_MAX_DIRS = 200

_TH_RE = re.compile(
    r"\b(TH-[A-Z0-9]{2,6}-\d{4})(?:-S(\d{1,2})Q(\d{1,2}))?\b",
    re.IGNORECASE,
)
_FILE_ID_RE = re.compile(r"\[([^\]]+)\]\s*$")

LOG_ROOT = config.RAW_DIR / "pega-logs"

#: Skip a pega fetch for failed runs before this day. Cached codes still
#: apply. Override with ``TH_LOGS_FROM``; empty means every day.
_DEFAULT_FROM = "2026-09-25"


class _Diag(NamedTuple):
    unique_id: Optional[str]
    codes: Tuple[str, ...]
    order: int


class _Index(NamedTuple):
    diagnoses: Tuple[_Diag, ...]
    unique_ids: frozenset
    artifact_dirs: Dict[str, str]


def th_codes(text: str) -> List[str]:
    """Every ``TH-…`` token in ``text``, in order, without duplicates."""
    found: List[str] = []
    for match in _TH_RE.finditer(text or ""):
        identity = match.group(1).upper()
        if match.group(2) is not None and match.group(3) is not None:
            form = "{}-S{}Q{}".format(identity, match.group(2), match.group(3))
        else:
            form = identity
        if form not in found:
            found.append(form)
    return found


def parse_log(text: str) -> _Index:
    """Diagnoses in one ``log.jsonl``, each tied to the step's ``unique_id``.

    The id lives on the step's log-file artifact (``Log file for Test Case:
    <Class> [<unique_id>]``), a different record from the diagnosis, joined
    only by ``testStepId``.
    """
    unique_ids: Dict[str, str] = {}
    artifact_dirs: Dict[str, str] = {}
    pending: List[Tuple[Optional[str], str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        artifact = record.get("testStepArtifact")
        if not isinstance(artifact, dict):
            continue
        raw_step = artifact.get("testStepId")
        step_id = str(raw_step) if raw_step is not None else None
        if step_id is not None and step_id not in unique_ids:
            file_artifact = artifact.get("file")
            if isinstance(file_artifact, dict):
                match = _FILE_ID_RE.search(
                    str(file_artifact.get("description") or ""))
                if match:
                    unique_ids[step_id] = match.group(1).strip()
                    uri = str(file_artifact.get("uri") or "").strip()
                    if uri:
                        artifact_dirs[step_id] = str(PurePosixPath(uri).parent)
        diagnosis = artifact.get("diagnosis")
        if not isinstance(diagnosis, dict):
            continue
        verdict = diagnosis.get("verdict")
        if not isinstance(verdict, str) or not verdict.strip():
            continue
        pending.append((step_id, verdict.strip()))

    diagnoses = tuple(
        _Diag(
            unique_id=unique_ids.get(step_id) if step_id is not None else None,
            codes=tuple(th_codes(verdict)),
            order=order,
        )
        for order, (step_id, verdict) in enumerate(pending)
        if th_codes(verdict)
    )
    return _Index(
        diagnoses=diagnoses,
        unique_ids=frozenset(unique_ids.values()),
        artifact_dirs={
            unique_id: artifact_dirs[step_id]
            for step_id, unique_id in unique_ids.items()
            if step_id in artifact_dirs
        },
    )


def _log_files(root: Path) -> Tuple[Path, ...]:
    """Every ``log.jsonl`` under ``root``, deepest first."""
    found: List[Path] = []
    if not root.is_dir():
        return ()
    for depth in range(_MAX_DEPTH + 1):
        pattern = "/".join(["*"] * depth + ["log.jsonl"]) if depth else "log.jsonl"
        found.extend(root.glob(pattern))
    return tuple(sorted(found, key=lambda path: (-len(path.parts), str(path))))


def _index(path: Path) -> _Index:
    try:
        size = path.stat().st_size
    except OSError:
        return _Index((), frozenset(), {})
    try:
        data = path.read_bytes()
    except OSError:
        return _Index((), frozenset(), {})
    if size > _MAX_LOG_BYTES:
        data = data[-_MAX_LOG_BYTES:]
        newline = data.find(b"\n")
        if newline >= 0:
            data = data[newline + 1:]
    return parse_log(data.decode("utf-8", errors="replace"))


def _logs_in(scope: Path, logs: Sequence[Path]) -> Tuple[Path, ...]:
    try:
        resolved = scope.resolve()
    except OSError:
        return ()
    inside = []
    for path in logs:
        try:
            if path.resolve().is_relative_to(resolved):
                inside.append(path)
        except OSError:
            continue
    return tuple(inside)


def _lookups(unique_id: str, logs: Sequence[Path]
             ) -> List[Tuple[str, Tuple[Path, ...]]]:
    """``(id, logs)`` pairs, most specific first.

    A nested test is ``<parent>_<child>`` in the outer run and ``<child>``
    in the nested suite's own log. The bare child is only looked up inside
    that parent's artifact directory, so one chip's ``lane_repair`` is not
    another's.
    """
    lookups: List[Tuple[str, Tuple[Path, ...]]] = []
    if unique_id:
        lookups.append((unique_id, tuple(logs)))
    parents: List[Tuple[int, str, Path]] = []
    for path in logs:
        index = _index(path)
        for parent in index.unique_ids:
            if not unique_id.startswith(parent + "_"):
                continue
            rel = index.artifact_dirs.get(parent)
            if not rel:
                continue
            parents.append((len(parent), parent, path.parent / rel))
    parents.sort(key=lambda item: (-item[0], item[1], str(item[2])))
    seen = set()
    for length, _parent, scope in parents:
        child = unique_id[length + 1:]
        key = (child, str(scope))
        if not child or key in seen:
            continue
        seen.add(key)
        scoped = _logs_in(scope, logs)
        if scoped:
            lookups.append((child, scoped))
    return lookups


def _codes_in(logs: Sequence[Path], unique_id: str) -> List[str]:
    found: List[str] = []
    for path in logs:
        for diag in _index(path).diagnoses:
            if diag.unique_id != unique_id:
                continue
            for code in diag.codes:
                if code not in found:
                    found.append(code)
    return found


def codes_under(root: Path, unique_id: str) -> List[str]:
    """Every TH code recorded for ``unique_id`` in the logs under ``root``."""
    logs = _log_files(root)
    if not logs or not unique_id:
        return []
    for candidate, scoped in _lookups(unique_id, logs):
        found = _codes_in(scoped, candidate)
        if found:
            return found
    return []


def codes_in_run(root: Path) -> Dict[str, List[str]]:
    """unique_id -> every TH code the logs record for that step.

    Also keys ``<parent>_<child>``. That is the id on the outer run's row;
    the nested log only knows ``<child>``.
    """
    logs = _log_files(root)
    wanted: List[str] = []
    for path in logs:
        for unique_id in _index(path).unique_ids:
            if unique_id not in wanted:
                wanted.append(unique_id)
    for path in logs:
        index = _index(path)
        for parent, rel in index.artifact_dirs.items():
            for nested in _logs_in(path.parent / rel, logs):
                if nested == path:
                    continue
                for child in _index(nested).unique_ids:
                    paired = "{}_{}".format(parent, child)
                    if paired not in wanted:
                        wanted.append(paired)
    out: Dict[str, List[str]] = {}
    for unique_id in wanted:
        found = codes_under(root, unique_id)
        if found:
            out[unique_id] = found
    return out


def _run_dir(run_id: str, host: str) -> Path:
    safe = re.sub(r"[^\w.\-]+", "_", run_id).strip("._") or "run"
    return LOG_ROOT / host / safe


def _marker(root: Path) -> Path:
    return root / "codes.json"


def _fetch(path: str, host: Optional[str]) -> bytes:
    url = "{}{}".format(pega.base_url(host), path)
    try:
        with urllib.request.urlopen(url, timeout=pega.TIMEOUT) as response:
            return _tail(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise pega.PegaUnavailable("{}: {}".format(url, exc)) from exc


def _tail(response) -> bytes:
    """The body, or its last ``_MAX_LOG_BYTES`` when it is longer."""
    buf = bytearray()
    truncated = False
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > _MAX_LOG_BYTES:
            del buf[:-_MAX_LOG_BYTES]
            truncated = True
    if truncated:
        newline = buf.find(b"\n")
        if newline >= 0:
            del buf[:newline + 1]
    return bytes(buf)


def _browse(run_id: str, host: Optional[str], rel: str) -> dict:
    query = urllib.parse.urlencode({"path": rel}) if rel else ""
    path = "/api/suite_run/{}/browse{}".format(
        urllib.parse.quote(run_id, safe=""),
        ("?" + query) if query else "")
    payload = pega._get(path, cache=False, host=host)  # noqa: SLF001
    return payload if isinstance(payload, dict) else {}


def _download_tree(run_id: str, host: str, root: Path) -> bool:
    """Save every ``log.jsonl`` under the run. False when the walk failed."""
    pending = [""]
    seen = 0
    saved = 0
    try:
        while pending and seen < _MAX_DIRS:
            rel = pending.pop(0)
            seen += 1
            try:
                listing = _browse(run_id, host, rel)
            except pega.PegaUnavailable as exc:
                log.info("browse skipped for %s %s (%s)", run_id, rel or ".", exc)
                continue
            for item in listing.get("files") or []:
                name = str(item.get("filename") or "")
                if name != "log.jsonl":
                    continue
                query = urllib.parse.urlencode({"path": rel}) if rel else ""
                remote = "/api/suite_run/{}/browse/log.jsonl/raw{}".format(
                    urllib.parse.quote(run_id, safe=""),
                    ("?" + query) if query else "")
                try:
                    body = _fetch(remote, host)
                except pega.PegaUnavailable as exc:
                    log.info("log.jsonl skipped for %s %s (%s)",
                             run_id, rel or ".", exc)
                    continue
                parts = PurePosixPath(rel).parts if rel else ()
                local = root.joinpath(*parts, "log.jsonl")
                if ".." in local.parts:
                    continue
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(body)
                saved += 1
            if rel.count("/") >= _MAX_DEPTH:
                continue
            for item in listing.get("directories") or []:
                child = str(item.get("path") or "").strip().strip("/")
                if child and ".." not in PurePosixPath(child).parts:
                    pending.append(child)
    except pega.PegaUnavailable as exc:
        log.info("log.jsonl for %s not downloaded (%s)", run_id, exc)
        return False
    log.info("saved %d log.jsonl for %s", saved, run_id)
    return True


_disk_codes: Dict[str, Optional[Dict[str, List[str]]]] = {}


def cached_codes_for_run(run_id: str, host: Optional[str] = None
                         ) -> Optional[Dict[str, List[str]]]:
    """Codes already on disk for this run, or None if it was never fetched."""
    if not run_id:
        return None
    who = host or "pega4"
    key = who + ":" + run_id
    if key in _disk_codes:
        return _disk_codes[key]
    root = _run_dir(run_id, who)
    logs = _log_files(root)
    if logs:
        found: Optional[Dict[str, List[str]]] = codes_in_run(root)
    elif _marker(root).is_file():
        try:
            cached = json.loads(_marker(root).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found = {}
        else:
            if isinstance(cached, dict):
                found = {str(name): [str(code) for code in values]
                         for name, values in cached.items()
                         if isinstance(values, list)}
            else:
                found = {}
    else:
        found = None
    _disk_codes[key] = found
    return found


def codes_for_run(run_id: str, host: Optional[str] = None,
                  day: Optional[str] = None) -> Dict[str, List[str]]:
    """TH codes in this run, keyed by harness ``unique_id``.

    A finished run is downloaded once. Later daily rebuilds read the local
    copy. A failed download is not cached, so the next rebuild tries again.
    Days before ``TH_LOGS_FROM`` (default 2026-09-25) are not fetched.
    """
    if not run_id:
        return {}
    found = cached_codes_for_run(run_id, host)
    if found is not None:
        if found:
            who = host or "pega4"
            root = _run_dir(run_id, who)
            marker = _marker(root)
            if _log_files(root) and not marker.is_file():
                try:
                    root.mkdir(parents=True, exist_ok=True)
                    marker.write_text(json.dumps(found, indent=2),
                                      encoding="utf-8")
                except OSError as exc:
                    log.info("could not cache codes for %s (%s)", run_id, exc)
        return found
    if not pega.enabled():
        return {}
    who = host or "pega4"
    root = _run_dir(run_id, who)
    since = os.environ.get("TH_LOGS_FROM", _DEFAULT_FROM)
    if day and since and day < since:
        return {}
    if not _download_tree(run_id, who, root):
        return {}
    found = codes_in_run(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        _marker(root).write_text(json.dumps(found, indent=2), encoding="utf-8")
    except OSError as exc:
        log.info("could not cache codes for %s (%s)", run_id, exc)
    return found
