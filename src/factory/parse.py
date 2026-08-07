"""Normalize EOS payloads into the flat run record the metrics layer consumes.

WHY THIS FILE IS DEFENSIVE
--------------------------
``docs/api-usage.md`` pins down the *endpoints* but shows run objects elided as
``{ runId, dutSerial, ... }`` and does not spell out the schema of
``suite_summary.json``. Rather than guess one spelling and fail silently, every
field is resolved through the ``*_ALIASES`` tables below, key matching is
punctuation- and case-insensitive, and anything unresolved becomes ``None``
instead of an exception.

When you first run against live data, run ``python -m factory.cli inspect`` — it
prints the field names actually present. Add any missing spelling to the table
here; that is the single place this needs to change.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --------------------------------------------------------------------- aliases

RUN_ID_ALIASES = ("runId", "run_id", "id", "name")
DUT_ALIASES = ("dutSerial", "dut_serial", "dut", "serial", "serialNumber", "sn")
STATION_ALIASES = ("station", "stationId", "station_name", "tester", "fixture", "slot")
SUITE_ALIASES = ("suite", "suiteName", "testSuite", "suite_id")
VERSION_ALIASES = ("version", "swVersion", "buildVersion", "build", "firmwareVersion")
LEVEL_ALIASES = ("level", "testLevel", "stage")
START_ALIASES = (
    "startTime", "start_time", "startedAt", "started_at", "start",
    "timestamp", "createdAt", "created_at", "date",
)
END_ALIASES = ("endTime", "end_time", "finishedAt", "finished_at", "completedAt", "end")
DURATION_ALIASES = (
    "durationSec", "duration_sec", "duration", "durationSeconds",
    "elapsed", "elapsedSec", "runtime", "wallTime",
)
STATUS_ALIASES = ("status", "result", "outcome", "state", "verdict", "pass_fail")

# unique_id leads: EOS ships both a stable ID (CHK_BIOS_BOOT_ORDER, which also
# matches the log_file path) and a human class name (CheckBiosBootOrder). The
# stable one is the right grouping key for a Pareto.
TEST_NAME_ALIASES = (
    "unique_id", "uniqueId", "name", "testName", "test", "test_name", "id", "case", "title",
)
TEST_LOG_ALIASES = ("log_file", "logFile", "log", "logPath", "log_path", "relPath")
TEST_CODE_ALIASES = (
    "code", "errorCode", "error_code", "failureCode", "reason",
    "error", "message", "trace", "code_trace", "codeTrace",
)

#: Keys under which a suite_summary may nest its list of test entries.
TEST_LIST_ALIASES = ("tests", "results", "testResults", "cases", "items", "subtests", "entries")

# ------------------------------------------------------------------- status map

_PASS = {"pass", "passed", "ok", "success", "successful", "good", "true", "1", "p"}
_FAIL = {"fail", "failed", "failure", "bad", "false", "0", "f", "nok"}
_ERROR = {
    "error", "errored", "exception", "crash", "fatal", "aborted", "abort", "timeout",
    # EOS: the test terminated abnormally (distinct from INTERRUPTED, which means
    # it never ran). Read as an infrastructure error, so it counts against yield
    # but stays separate from a unit defect.
    # ASSUMPTION — worth confirming with the EOS team; it is rare (~0.5% of
    # entries observed) so the effect either way is small.
    "exited",
}
_SKIP = {
    "skip", "skipped", "na", "n/a", "notrun", "not_run", "none", "blocked", "ignored",
    # EOS/OCP: the suite aborted and these tests never executed. They are NOT
    # failures — counting them as such would tank yield on every aborted run —
    # and not passes either, so they leave the denominator entirely.
    "interrupted", "not_applicable", "notapplicable",
}

#: A run/test lands in exactly one of these. ``error`` is kept distinct from
#: ``fail`` because an infrastructure abort is not a unit defect — but both count
#: against yield, and the dashboard says so.
STATUSES = ("pass", "fail", "error", "skip", "unknown")


def normalize_status(value: Any) -> str:
    """Map any of the many status spellings onto one of :data:`STATUSES`."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "pass" if value else "fail"
    text = str(value).strip().lower()
    if not text:
        return "unknown"
    if text in _PASS:
        return "pass"
    if text in _FAIL:
        return "fail"
    if text in _ERROR:
        return "error"
    if text in _SKIP:
        return "skip"
    # Substring fallback for values like "FAILED (assertion)" or
    # "PASS_WITH_WARNINGS". Only tokens of four or more characters take part:
    # short ones ("na", "ok", "p") match inside unrelated words — "banana"
    # would otherwise read as a skip.
    for bucket, name in ((_ERROR, "error"), (_FAIL, "fail"), (_PASS, "pass"), (_SKIP, "skip")):
        if any(len(token) >= 4 and token in text for token in bucket):
            return name
    return "unknown"


def is_failure(status: str) -> bool:
    """True when a status counts against yield. ``skip`` does not."""
    return status in ("fail", "error")


# ------------------------------------------------------------------- key lookup

def _normkey(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def pick(source: Any, aliases: Sequence[str], default: Any = None) -> Any:
    """Return the first alias present in ``source``, matched loosely on the key.

    ``dutSerial``, ``dut_serial`` and ``DUT-Serial`` are all the same key here.
    """
    if not isinstance(source, dict):
        return default
    for alias in aliases:
        if alias in source and source[alias] not in (None, ""):
            return source[alias]
    lookup = {_normkey(k): v for k, v in source.items()}
    for alias in aliases:
        value = lookup.get(_normkey(alias))
        if value not in (None, ""):
            return value
    return default


# -------------------------------------------------------------------- timestamps

_RUN_ID_TIMESTAMP = re.compile(r"(\d{8})[_-](\d{6})")


def parse_timestamp(value: Any) -> Optional[int]:
    """Coerce a timestamp of unknown shape into UTC epoch seconds.

    Accepts epoch seconds/millis (int, float, or numeric string) and ISO-8601
    with ``Z``, an explicit offset, or none (naive is read as UTC).
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        # Anything past ~year 2286 in seconds is really milliseconds.
        return int(number / 1000 if number > 1e11 else number)
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return parse_timestamp(float(text))
    iso = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def timestamp_from_run_id(run_id: str) -> Optional[int]:
    """Recover a start time from the ``..._20260803_094406`` suffix in a run ID.

    The doc's example run IDs carry a local wall-clock stamp. This is the
    last-resort fallback when the run object has no usable time field; it is read
    as UTC, so a run dated this way can land in the wrong hour bucket. The
    collector logs a warning when it has to rely on this.
    """
    if not run_id:
        return None
    match = _RUN_ID_TIMESTAMP.search(str(run_id))
    if not match:
        return None
    return parse_timestamp("{}_{}".format(match.group(1), match.group(2)))


def parse_duration(value: Any) -> Optional[float]:
    """Coerce a duration into seconds. Accepts numbers and ``HH:MM:SS``/``1m30s``."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().lower()
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return float(text)
    if ":" in text:
        parts = text.split(":")
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return None
        seconds = 0.0
        for number in numbers:
            seconds = seconds * 60 + number
        return seconds
    match = re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", text)
    if match:
        scale = {"h": 3600.0, "m": 60.0, "s": 1.0}
        return sum(float(number) * scale[unit] for number, unit in match)
    return None


# ------------------------------------------------------------------ suite summary

def extract_test_entries(payload: Any) -> List[Dict[str, Any]]:
    """Pull the list of test entries out of a parsed suite_summary.json.

    Handles the three shapes seen in the wild: a bare list, a wrapper object with
    a list under one of :data:`TEST_LIST_ALIASES`, and a mapping of test name to
    entry.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return []

    nested = pick(payload, TEST_LIST_ALIASES)
    if isinstance(nested, list):
        return [entry for entry in nested if isinstance(entry, dict)]
    if isinstance(nested, dict):
        return _entries_from_mapping(nested)

    # A mapping of name -> entry, with no wrapper key.
    dict_values = [value for value in payload.values() if isinstance(value, dict)]
    if dict_values and len(dict_values) == len(payload):
        return _entries_from_mapping(payload)
    return []


def _entries_from_mapping(mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = []
    for name, entry in mapping.items():
        if isinstance(entry, dict):
            merged = dict(entry)
            merged.setdefault("name", name)
            entries.append(merged)
    return entries


def parse_suite_summary(raw: Any) -> List[Dict[str, Any]]:
    """Parse suite_summary.json bytes/text/object into normalized test records.

    Returns ``[{"name", "status", "durationSec", "logFile", "code"}, ...]``.
    """
    payload = raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            payload = json.loads(bytes(raw).decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return []
    elif isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []

    tests = []
    for entry in extract_test_entries(payload):
        name = pick(entry, TEST_NAME_ALIASES)
        if name is None:
            continue
        code = pick(entry, TEST_CODE_ALIASES)
        # The event stream keys its steps by the human name, while `name` above
        # is the stable ID — keep both so durations can be joined on.
        display = pick(entry, ("test_name", "testName", "name", "title"))
        tests.append(
            {
                "name": str(name),
                "displayName": str(display) if display is not None else None,
                "status": normalize_status(pick(entry, STATUS_ALIASES)),
                "durationSec": parse_duration(pick(entry, DURATION_ALIASES)),
                "logFile": pick(entry, TEST_LOG_ALIASES),
                "code": _short_code(code),
            }
        )
    return tests


# --------------------------------------------------------------- event stream

#: OCP TestRun status/result vocabulary used by the `event_stream` artifact.
_OCP_STATUS = {"COMPLETE": "pass", "ERROR": "error", "SKIP": "skip"}
_OCP_RESULT = {"PASS": "pass", "FAIL": "fail", "NOT_APPLICABLE": "unknown"}


def parse_event_stream(raw: Any) -> Dict[str, Any]:
    """Extract run timing and verdict from the OCP `log.jsonl` event stream.

    ``/runs`` gives only ``startedAt`` — no end time, no duration, no status —
    so this artifact is the sole source of cycle time and of a run-level verdict.

    Returns ``{"startTs", "endTs", "durationSec", "status", "stepDurations"}``,
    with ``None`` for anything the stream does not contain. A truncated stream
    (the run crashed mid-write) parses as far as it can rather than raising.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", "replace")
    if not isinstance(raw, str):
        return _empty_event_summary()

    first_ts = last_ts = None
    start_ts = end_ts = None
    status = None
    step_starts: Dict[str, Any] = {}
    step_durations: Dict[str, float] = {}

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # a partially written final line is expected, not fatal
        if not isinstance(event, dict):
            continue

        ts = parse_timestamp(event.get("timestamp"))
        if ts is not None:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)

        run_artifact = event.get("testRunArtifact") or {}
        if "testRunStart" in run_artifact:
            start_ts = ts
        if "testRunEnd" in run_artifact:
            end_ts = ts
            status = _ocp_verdict(run_artifact.get("testRunEnd") or {})

        step_artifact = event.get("testStepArtifact") or {}
        step_id = step_artifact.get("testStepId")
        if step_id is None:
            continue
        if "testStepStart" in step_artifact:
            name = (step_artifact.get("testStepStart") or {}).get("name")
            step_starts[step_id] = (name, ts)
        elif "testStepEnd" in step_artifact and step_id in step_starts:
            name, began = step_starts.pop(step_id)
            if name and began is not None and ts is not None and ts >= began:
                step_durations[name] = float(ts - began)

    start = start_ts if start_ts is not None else first_ts
    end = end_ts if end_ts is not None else last_ts
    duration = float(end - start) if start is not None and end is not None and end >= start else None

    return {
        "startTs": start,
        "endTs": end,
        "durationSec": duration,
        "status": status,
        "stepDurations": step_durations,
    }


def _empty_event_summary() -> Dict[str, Any]:
    return {
        "startTs": None, "endTs": None, "durationSec": None,
        "status": None, "stepDurations": {},
    }


def _ocp_verdict(test_run_end: Dict[str, Any]) -> str:
    """Fold OCP's two-field outcome (status + result) into one verdict.

    ``status`` describes whether the harness completed; ``result`` describes
    whether the unit passed. An infrastructure ERROR wins over the result field,
    which in that case is reported as NOT_APPLICABLE.
    """
    status = str(test_run_end.get("status", "")).upper()
    result = str(test_run_end.get("result", "")).upper()
    if status in ("ERROR", "SKIP"):
        return _OCP_STATUS[status]
    if result in _OCP_RESULT:
        return _OCP_RESULT[result]
    return _OCP_STATUS.get(status, "unknown")


def _short_code(value: Any) -> Optional[str]:
    """Trim a failure code/message to a groupable label."""
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    return text[:120] if text else None


# --------------------------------------------------------------------- run record

def parse_run(run: Dict[str, Any], level: str) -> Dict[str, Any]:
    """Normalize one entry from ``/runs`` into the fields the metrics layer needs.

    Test-level fields are filled in later by the collector, once the run's
    suite_summary has been fetched.
    """
    run_id = pick(run, RUN_ID_ALIASES)
    start = parse_timestamp(pick(run, START_ALIASES))
    start_from_id = False
    if start is None:
        start = timestamp_from_run_id(run_id)
        start_from_id = start is not None

    end = parse_timestamp(pick(run, END_ALIASES))
    duration = parse_duration(pick(run, DURATION_ALIASES))
    if duration is None and start is not None and end is not None and end >= start:
        duration = float(end - start)

    return {
        "runId": str(run_id) if run_id is not None else None,
        "level": str(pick(run, LEVEL_ALIASES, level) or level).lower(),
        "dutSerial": _as_str(pick(run, DUT_ALIASES)),
        "station": _as_str(pick(run, STATION_ALIASES)),
        "suite": _as_str(pick(run, SUITE_ALIASES)),
        "version": _as_str(pick(run, VERSION_ALIASES)),
        "startTs": start,
        "endTs": end,
        "durationSec": duration,
        "status": normalize_status(pick(run, STATUS_ALIASES)),
        "startFromRunId": start_from_id,
        "tests": [],
    }


def _as_str(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return str(value)


def summarize_tests(record: Dict[str, Any]) -> Dict[str, Any]:
    """Fold a run's parsed tests into run-level counts, status, and failure list.

    A run's status is taken from the API when the API gave one; otherwise it is
    derived — any failing test fails the run.
    """
    tests: Iterable[Dict[str, Any]] = record.get("tests") or []
    tests = list(tests)

    counts = {status: 0 for status in STATUSES}
    for test in tests:
        counts[test.get("status", "unknown")] = counts.get(test.get("status", "unknown"), 0) + 1

    failures = [
        {
            "test": test["name"],
            # The CamelCase class name is what the root-cause rules were written
            # against, so it has to survive into the failure record.
            "display": test.get("displayName"),
            "code": test.get("code"),
            "log": test.get("logFile"),
        }
        for test in tests
        if is_failure(test.get("status", "unknown"))
    ]

    if record.get("status") in (None, "unknown") and tests:
        record["status"] = "fail" if failures else "pass"

    if record.get("durationSec") is None and tests:
        known = [test["durationSec"] for test in tests if test.get("durationSec") is not None]
        if known:
            record["durationSec"] = float(sum(known))

    record["testCounts"] = counts
    record["failures"] = failures
    return record
