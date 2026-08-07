"""Walk the EOS endpoints and build the normalized run table.

    /runs  ->  /artifacts (role=suite_summary)  ->  /artifact-content

One record per run, with the run's tests folded in. Artifact fetches run on a
small thread pool because they dominate wall time; the run list itself is a
single call per level.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import config, parse
from .eos_client import EOSClient, EOSError

log = logging.getLogger(__name__)

SUMMARY_FILENAME_HINTS = ("suite_summary.json", "summary.json")


def collect(
    client: EOSClient,
    levels: Sequence[str],
    frm: str,
    to: str,
    max_workers: int = 8,
    fetch_summaries: bool = True,
) -> Dict[str, Any]:
    """Collect every run in ``[frm, to]`` for ``levels`` into one table.

    Both bounds are inclusive, per the API doc. Returns the payload later written
    to ``data/processed/runs.json``.
    """
    records: List[Dict[str, Any]] = []
    problems: List[str] = []

    for level in levels:
        log.info("listing runs: level=%s from=%s to=%s", level, frm, to)
        try:
            raw_runs = client.runs(level=level, frm=frm, to=to)
        except EOSError as exc:
            problems.append("runs({}): {}".format(level, exc))
            log.error("could not list runs for %s: %s", level, exc)
            continue

        log.info("level=%s -> %d runs", level, len(raw_runs))
        level_records = [parse.parse_run(run, level) for run in raw_runs]
        level_records = [rec for rec in level_records if rec["runId"]]

        if fetch_summaries:
            _attach_summaries(client, level_records, max_workers, problems)

        for record in level_records:
            parse.summarize_tests(record)
        records.extend(level_records)

    guessed = sum(1 for rec in records if rec.get("startFromRunId"))
    if guessed:
        log.warning(
            "%d/%d runs had no time field; start time was read from the run ID "
            "(treated as UTC) — verify hour bucketing before trusting rate metrics",
            guessed,
            len(records),
        )

    records.sort(key=lambda rec: (rec.get("startTs") or 0, rec.get("runId") or ""))
    _mark_attempts(records)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "window": {"from": frm, "to": to},
        "levels": list(levels),
        "timezone": config.timezone_name(),
        "runCount": len(records),
        "problems": problems,
        "runs": records,
    }


def _attach_summaries(
    client: EOSClient,
    records: List[Dict[str, Any]],
    max_workers: int,
    problems: List[str],
) -> None:
    """Fetch and parse each run's suite_summary.json, in parallel."""
    fetchable = [rec for rec in records if rec.get("dutSerial")]
    missing_dut = len(records) - len(fetchable)
    if missing_dut:
        log.warning("%d runs have no dutSerial; their tests cannot be fetched", missing_dut)

    if not fetchable:
        return

    workers = max(1, min(max_workers, len(fetchable)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_summary_for_run, client, rec): rec for rec in fetchable}
        done = 0
        for future in as_completed(futures):
            record = futures[future]
            done += 1
            if done % 25 == 0 or done == len(futures):
                log.info("suite summaries %d/%d", done, len(futures))
            try:
                record["tests"] = future.result()
            except EOSError as exc:
                problems.append("summary({}): {}".format(record["runId"], exc))
                log.warning("no summary for %s: %s", record["runId"], exc)


def _summary_for_run(client: EOSClient, record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Locate a run's suite_summary artifact and parse it into test records."""
    level = record["level"]
    dut = record["dutSerial"]
    run_id = record["runId"]

    artifacts = client.artifacts(
        level=level, dut_serial=dut, run_id=run_id, role=config.ROLE_SUITE_SUMMARY
    )
    rel_path = _pick_summary_path(artifacts)

    if rel_path is None:
        # Fall back to the unfiltered listing — some runs tag the role differently.
        artifacts = client.artifacts(level=level, dut_serial=dut, run_id=run_id)
        rel_path = _pick_summary_path(artifacts)

    if rel_path is None:
        log.debug("run %s exposes no suite_summary artifact", run_id)
        return []

    raw = client.artifact_content(
        level=level, dut_serial=dut, run_id=run_id, rel_path=rel_path
    )
    return parse.parse_suite_summary(raw)


def _pick_summary_path(artifacts: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Choose the suite_summary artifact from a listing."""
    by_role = [
        art
        for art in artifacts
        if str(art.get("role", "")).lower() == config.ROLE_SUITE_SUMMARY
    ]
    for candidate in (by_role or artifacts):
        rel_path = parse.pick(candidate, ("relPath", "rel_path", "path", "name"))
        if rel_path and str(rel_path).lower().endswith(SUMMARY_FILENAME_HINTS):
            return str(rel_path)
    if by_role:
        rel_path = parse.pick(by_role[0], ("relPath", "rel_path", "path", "name"))
        return str(rel_path) if rel_path else None
    return None


def _mark_attempts(records: List[Dict[str, Any]]) -> None:
    """Number each DUT's runs at a level in time order.

    ``attempt == 1`` is the DUT's first pass through that level *within the
    collected window*, which is what first-pass yield is measured on. Widen the
    window and an attempt-1 run can become attempt-2; that is inherent to FPY on
    a windowed extract, and ``docs/metrics.md`` says so.
    """
    seen: Dict[tuple, int] = {}
    for record in records:
        key = (record.get("level"), record.get("dutSerial"))
        seen[key] = seen.get(key, 0) + 1
        record["attempt"] = seen[key]


def fetch_test_log(
    client: EOSClient, record: Dict[str, Any], rel_path: str
) -> bytes:
    """Fetch one test's full trace, given a ``log_file`` from its summary entry."""
    return client.artifact_content(
        level=record["level"],
        dut_serial=record["dutSerial"],
        run_id=record["runId"],
        rel_path=rel_path,
    )


def write_runs(payload: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or config.RUNS_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    return target


def read_runs(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or config.RUNS_JSON
    if not target.exists():
        raise FileNotFoundError(
            "{} not found — run `make collect` (live API) or `make demo` "
            "(synthetic data) first.".format(target)
        )
    return json.loads(target.read_text(encoding="utf-8"))


def default_window(days: int = 1, tz_name: Optional[str] = None) -> Dict[str, str]:
    """The last ``days`` local days, expressed as the UTC instants the API wants."""
    tz = _tzinfo(tz_name or config.timezone_name())
    now_local = datetime.now(tz)
    end_local = now_local.replace(minute=59, second=59, microsecond=0)
    start_local = (end_local - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0)
    return {
        "from": start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _tzinfo(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - missing tzdata is not worth failing over
        log.warning("timezone %s unavailable; falling back to UTC", name)
        return timezone.utc
