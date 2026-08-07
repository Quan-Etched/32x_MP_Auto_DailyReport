"""Fetch bookkeeping: when we last *asked*, and when the answer last *changed*.

Two different questions, and conflating them is how a dashboard lies:

``lastFetchAt``   the last time the collector ran and the API answered. Proves
                  the pipeline is alive.
``lastUpdateAt``  the last time the data actually changed. Proves the *line* is
                  alive.

A green "updated 3 minutes ago" on an hourly job that has been re-fetching the
same 40 runs since Friday is worse than no timestamp at all. So the content is
hashed, and ``lastUpdateAt`` only advances when the hash moves.

Tracked per station as well as globally, because "MLT has not produced a run in
9 hours" is exactly the signal a line lead wants, and it is invisible in a
global timestamp while any other station is busy.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import config

log = logging.getLogger(__name__)

STATE_PATH = config.PROCESSED_DIR / "fetch_state.json"

#: How many fetch outcomes to keep for the sparkline / audit trail.
HISTORY_LIMIT = 200


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_hash(runs: Sequence[Dict[str, Any]]) -> str:
    """Stable digest of everything that would change what the dashboard shows.

    Deliberately excludes generation timestamps and collection order — a fetch
    that returns identical data must produce an identical hash, or every hourly
    run would look like an update.
    """
    material = sorted(
        "{}|{}|{}|{}|{}|{}".format(
            run.get("runId"),
            run.get("status"),
            run.get("endTs"),
            run.get("durationSec"),
            (run.get("testCounts") or {}).get("fail", 0),
            len(run.get("failures") or []),
        )
        for run in runs
    )
    digest = hashlib.sha256()
    for line in material:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:16]


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or STATE_PATH
    if not target.exists():
        return {
            "schemaVersion": 1,
            "lastFetchAt": None,
            "lastFetchStatus": None,
            "lastFetchError": None,
            "lastUpdateAt": None,
            "contentHash": None,
            "consecutiveNoChange": 0,
            "totalFetches": 0,
            "stations": {},
            "history": [],
        }
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("fetch state at %s unreadable (%s); starting fresh", target, exc)
        return load(Path("/nonexistent"))


def save(state: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return target


def record_failure(error: str, path: Optional[Path] = None) -> Dict[str, Any]:
    """A fetch that never got an answer. Advances neither timestamp."""
    state = load(path)
    stamp = now_iso()
    state["lastFetchAttemptAt"] = stamp
    state["lastFetchStatus"] = "error"
    state["lastFetchError"] = error[:500]
    state["totalFetches"] = state.get("totalFetches", 0) + 1
    state.setdefault("history", []).append(
        {"at": stamp, "status": "error", "changed": False, "runs": None}
    )
    state["history"] = state["history"][-HISTORY_LIMIT:]
    save(state, path)
    return state


def record_fetch(
    payload: Dict[str, Any],
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Record a successful fetch and decide whether it changed anything.

    Returns the new state, with ``changed`` set for the caller.
    """
    state = load(path)
    stamp = now_iso()
    runs: List[Dict[str, Any]] = payload.get("runs", [])
    digest = content_hash(runs)

    changed = digest != state.get("contentHash")
    state["lastFetchAt"] = stamp
    state["lastFetchAttemptAt"] = stamp
    state["lastFetchStatus"] = "ok"
    state["lastFetchError"] = None
    state["totalFetches"] = state.get("totalFetches", 0) + 1
    state["runCount"] = len(runs)
    state["window"] = payload.get("window")

    if changed:
        state["previousUpdateAt"] = state.get("lastUpdateAt")
        state["lastUpdateAt"] = stamp
        state["contentHash"] = digest
        state["consecutiveNoChange"] = 0
    else:
        state["consecutiveNoChange"] = state.get("consecutiveNoChange", 0) + 1

    state["stations"] = _station_state(state.get("stations") or {}, runs, stamp)
    state["levelErrors"] = payload.get("levelErrors") or {}

    state.setdefault("history", []).append(
        {"at": stamp, "status": "ok", "changed": changed, "runs": len(runs)}
    )
    state["history"] = state["history"][-HISTORY_LIMIT:]
    state["changed"] = changed

    save(state, path)
    return state


def _station_state(
    previous: Dict[str, Any], runs: Sequence[Dict[str, Any]], stamp: str
) -> Dict[str, Any]:
    """Per-station hashes, so one busy station cannot mask nine quiet ones."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(run.get("stationKey") or "unclassified", []).append(run)

    updated: Dict[str, Any] = {}
    # Keep stations that have gone quiet; dropping them would erase the very
    # fact that they stopped producing.
    for key in set(previous) | set(grouped):
        bucket = grouped.get(key, [])
        digest = content_hash(bucket) if bucket else None
        before = previous.get(key, {})
        entry = {
            "runs": len(bucket),
            "contentHash": digest,
            "lastUpdateAt": before.get("lastUpdateAt"),
            "lastRunTs": max((r["startTs"] for r in bucket if r.get("startTs")), default=None),
        }
        if digest is not None and digest != before.get("contentHash"):
            entry["lastUpdateAt"] = stamp
        updated[key] = entry
    return updated


def summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """The subset the dashboard header renders."""
    return {
        "lastFetchAt": state.get("lastFetchAt"),
        "lastFetchAttemptAt": state.get("lastFetchAttemptAt"),
        "lastFetchStatus": state.get("lastFetchStatus"),
        "lastFetchError": state.get("lastFetchError"),
        "lastUpdateAt": state.get("lastUpdateAt"),
        "consecutiveNoChange": state.get("consecutiveNoChange", 0),
        "totalFetches": state.get("totalFetches", 0),
        "stations": state.get("stations", {}),
        "history": (state.get("history") or [])[-48:],
    }
