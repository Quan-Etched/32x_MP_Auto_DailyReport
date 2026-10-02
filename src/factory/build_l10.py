"""L10 — FAT, SFT, RIN and 2U, from pega4.

WHY A SECOND TABLE RATHER THAN MORE COLUMNS
-------------------------------------------
The module tracker follows a *unit* through MLT and HTT. L10 follows a
*chassis* through four stages, and the two do not share a DUT: a module serial
is fifteen digits, an L10 chassis serial is twelve, and one chassis contains
many modules. On one row they would have no single subject.

So this builds a day's L10 tab in the same shape as the module one, and the
daily tracker renders it as a second table underneath. It had its own page
once; one page per controller made a reader open two tabs to answer one
question about one day.

WHAT L10 DOES NOT HAVE
----------------------
**Slots.** A module run drives eight chips in one fixture and pega3 returns a
``participating`` list; an L10 run tests one chassis and returns ``null``. So a
unit's failures are every failing leaf in the run, with no chip index to filter
on — the filtering that the module tracker *must* do would here drop everything.

**A hand-kept sheet.** There is no workbook for L10, so every tab is built from
pega4 and none of them is "the line's own record". That also means no Jira
column: the module tracker gets its ticket keys from the sheet, and inventing
one here would be a column that is always empty.

SUITE NAMES ARE A MESS, DELIBERATELY ACCOMMODATED
--------------------------------------------------
pega4 has run FAT under ``L10_FAT``, ``L10_6U_FAT`` and ``L10_6U_FAT_195``
through ``_207`` — the trailing number is a release, not a stage. SFT and RIN
the same. The patterns accept all of those spellings, because a pattern that
matches only today's name silently zeroes a station the next time the line
renames one; that has already happened once here, when release 220 dropped the
``6U_`` infix.

``L10_2U_tests`` is treated as the 2U stage. EOS calls the same thing
``L10_2U``; the evidence they are one stage is that pega4's runs carry the
production part number ``81S15V000050`` and the same chassis serials FAT uses.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import build_dailyexcel, config, pega, rootcause, version, xlsx

#: The four L10 stages, in the order the line runs them, with the spellings
#: pega4 has used for each. ``_\d+`` is a release suffix, not a different stage.
STAGES = (
    ("fat", "L10 FAT", r"^L10_(6U_)?FAT(_\d+)?$"),
    ("sft", "L10 SFT", r"^L10_(6U_)?SFT(_\d+)?$"),
    ("rin", "L10 RIN", r"^L10_(6U_)?RIN(_\d+)?$"),
    ("2u",  "L10 2U",  r"^L10_2U(_tests)?$"),
)

#: Not a stage: dev suites, debug builds, dry runs, an engineer's name, output
#: directories, ticket-named runs. Same policy as the station registry's.
ENGINEERING = re.compile(
    r"(_krish|_debug|_out_dir|_SAM|_SMOKE|_etch\d+|^DRY_?RUN|^L10_tests$)", re.IGNORECASE)

#: Stage key -> the station key the rest of the dashboard uses. The tracker
#: and the station page have to agree on a name or the two never line up.
STATION_OF = {"fat": "l10_fat", "sft": "l10_sft",
              "rin": "l10_rin", "2u": "l10_2u"}

#: Days of history to publish. The tracker answers "what happened today and
#: yesterday"; a month of tabs is what the run table is for.
DEFAULT_DAYS = 5


def _matcher():
    return [(key, label, re.compile(pattern, re.IGNORECASE))
            for key, label, pattern in STAGES]


def stage_of(suite: Optional[str]) -> Optional[str]:
    """Which L10 stage a pega4 suite name belongs to, if any."""
    name = (suite or "").strip()
    if not name or ENGINEERING.search(name):
        return None
    for key, _label, pattern in _matcher():
        if pattern.match(name):
            return key
    return None


def failure_details(detail: Dict[str, Any],
                   by_case: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                   log_codes: Optional[Dict[str, List[str]]] = None,
                   run_id: str = ""
                   ) -> List[Dict[str, str]]:
    """One record per failing leaf: test name, case id, code, time.

    Codes come from that test's ``log.jsonl`` diagnoses, every one of them.
    The run payload only keeps the diagnosis ESVM preferred. When the log
    has none, the code is NA — catalogue and payload fields are not used.
    """
    known = by_case or {}
    logged = log_codes or {}
    found: List[Dict[str, str]] = []
    seen = set()
    for case in sorted(detail.get("test_cases") or [],
                       key=lambda c: c.get("start_time") or ""):
        status = str(case.get("status") or "").lower()
        if not status.startswith(("fail", "error")):
            continue
        name = (case.get("test_name") or "").strip()
        if not name or rootcause.is_container(name):
            continue
        case_id = (case.get("test_id") or name).strip()
        if case_id in seen:
            continue
        seen.add(case_id)
        found.append({
            "test": name,
            "caseId": case_id,
            "code": _case_code(case, name, known, logged, run_id, case_id),
            "at": str(case.get("start_time") or ""),
        })
    return found


def _case_code(case: Dict[str, Any], name: str,
               by_case: Dict[str, List[Dict[str, Any]]],
               log_codes: Dict[str, List[str]],
               run_id: str, case_id: str) -> str:
    unique = case_id
    if run_id and case_id.startswith(run_id + "_"):
        unique = case_id[len(run_id) + 1:]
    logged = list(log_codes.get(unique) or log_codes.get(case_id) or [])
    if logged:
        return "\n".join(logged)
    return "NA"


def run_id_from_url(url: str) -> str:
    """pega suite_run id from an ESVM link, or empty."""
    text = (url or "").strip()
    marker = "/suite_run/"
    at = text.find(marker)
    if at < 0:
        return ""
    return text[at + len(marker):].split("?", 1)[0].strip("/")


def logged_case_code(case_id: str, run_id: str,
                     log_codes: Dict[str, List[str]]) -> str:
    return _case_code({}, "", {}, log_codes, run_id, case_id or "")


def restamp_fail_codes(report: Dict[str, Any],
                       cache: Optional[Dict[str, Dict[str, List[str]]]] = None
                       ) -> Dict[str, Any]:
    """Replace stored codes with log.jsonl diagnoses; otherwise NA.

    Old snapshots kept catalogue / payload fallbacks. Daily FA only shows a
    code when that test's log recorded one.
    """
    from . import th_logs

    store = cache if cache is not None else {}
    for row in report.get("rows") or []:
        if row.get("status") == "pass" or row.get("errorType") == "Passed":
            continue
        run_id = run_id_from_url(row.get("url") or "")
        if not run_id:
            continue
        if run_id not in store:
            found = th_logs.cached_codes_for_run(run_id)
            store[run_id] = found if found is not None else {}
        row["code"] = logged_case_code(
            row.get("caseId") or "", run_id, store[run_id])
    return report


def restamp_l10_reports(l10: Any,
                        cache: Optional[Dict[str, Dict[str, List[str]]]] = None
                        ) -> None:
    if not isinstance(l10, dict):
        return
    store = cache if cache is not None else {}
    for key in REPORT_KEY.values():
        report = l10.get(key)
        if isinstance(report, dict):
            restamp_fail_codes(report, store)


#: L10_FLOW_TEST_COVERAGE column C — one Jira family per stage, not per test.
FLOW_STAGES_PATH = config.REPO_ROOT / "errors" / "l10_flow_stages.json"

_flow_stages: Optional[Dict[str, str]] = None
_flow_index: Optional[Dict[str, str]] = None
_error_types: Optional[Dict[str, str]] = None
_error_index: Optional[Dict[str, str]] = None


def _norm_test(name: str) -> str:
    text = (name or "").strip()
    if text.endswith("TestCase"):
        text = text[:-8]
    return text.replace("MultiChip", "").lower()


def _load_flow_stages() -> Tuple[Dict[str, str], Dict[str, str]]:
    global _flow_stages, _flow_index
    if _flow_stages is not None and _flow_index is not None:
        return _flow_stages, _flow_index
    tests: Dict[str, str] = {}
    if FLOW_STAGES_PATH.exists():
        payload = json.loads(FLOW_STAGES_PATH.read_text(encoding="utf-8"))
        raw = payload.get("tests") or {}
        if isinstance(raw, dict):
            tests = {str(name): str(stage) for name, stage in raw.items()}
    index: Dict[str, str] = {}
    for name, stage in tests.items():
        index.setdefault(_norm_test(name), stage)
    _flow_stages = tests
    _flow_index = index
    return tests, index


def _load_error_types() -> Tuple[Dict[str, str], Dict[str, str]]:
    global _error_types, _error_index
    if _error_types is not None and _error_index is not None:
        return _error_types, _error_index
    tests: Dict[str, str] = {}
    if FLOW_STAGES_PATH.exists():
        payload = json.loads(FLOW_STAGES_PATH.read_text(encoding="utf-8"))
        raw = payload.get("errorTypes") or {}
        if isinstance(raw, dict):
            tests = {
                str(name): str(kind).strip().lower()
                for name, kind in raw.items()
                if str(kind).strip().lower() in ("hardware", "software")
            }
    index: Dict[str, str] = {}
    for name, kind in tests.items():
        index.setdefault(_norm_test(name), kind)
    _error_types = tests
    _error_index = index
    return tests, index


def _lookup_named(raw: str, tests: Dict[str, str],
                  index: Dict[str, str]) -> Optional[str]:
    if raw in tests:
        return tests[raw]
    folded = _norm_test(raw)
    if folded in index:
        return index[folded]
    if len(folded) >= 8:
        best = ""
        found = None
        for key, value in index.items():
            if len(key) < 8:
                continue
            if folded.startswith(key) or key.startswith(folded):
                if len(key) > len(best):
                    best, found = key, value
        if found:
            return found
    return None


def stage_of_test(name: str) -> str:
    """Coverage-sheet column C for a leaf test. Unknown names stay their own family."""
    raw = (name or "").strip()
    if not raw:
        return ""
    tests, index = _load_flow_stages()
    found = _lookup_named(raw, tests, index)
    if found:
        return found
    lower = raw.lower()
    if "c2c" in lower or "sohuping" in lower or "hostreboot" in lower \
            or ("vfio" in lower and "ping" in lower):
        return "Sohu C2C"
    if "inferencemax" in lower:
        return "InferenceMAX Run-in"
    if "llama" in lower or "huggingface" in lower:
        return "Model Registry & Inference"
    return raw


def error_type_of_test(name: str) -> str:
    """Daily FA Error Type: hardware or software, from the coverage sheet."""
    raw = (name or "").strip()
    if not raw:
        return "hardware"
    tests, index = _load_error_types()
    found = _lookup_named(raw, tests, index)
    if found in ("hardware", "software"):
        return found
    lower = raw.lower()
    if "llama" in lower or "huggingface" in lower or "inferencemax" in lower \
            or "modelregistry" in lower:
        return "software"
    return "hardware"


def as_error_type(value: str, test: str = "") -> str:
    text = (value or "").strip().lower()
    if text == "passed":
        return "Passed"
    if text in ("hardware", "software"):
        return text
    return error_type_of_test(test)


DRI_OPTIONS = ("Eason Chuang", "Jonathan Wang", "Software team")


def default_dri(error_type: str) -> str:
    if error_type == "Passed" or not error_type:
        return ""
    if error_type == "software":
        return "Software team"
    return "Eason Chuang"


def as_dri(value: str, error_type: str) -> str:
    if error_type == "Passed" or not error_type:
        return ""
    text = (value or "").strip()
    if text in DRI_OPTIONS:
        return text
    return default_dri(error_type)


def is_c2c(name: str) -> bool:
    """C2C link / PRBS / integrity / throughput / stability tests."""
    return stage_of_test(name) == "Sohu C2C" or "c2c" in (name or "").lower()


#: Daily FA reports these three stages. 2U stays on the tracker table only.
REPORT_STAGES = ("fat", "sft", "rin")
REPORT_KEY = {"fat": "fatReport", "sft": "sftReport", "rin": "rinReport"}
#: L6 files onto the same epic as L10. The label is different; the epic is not.
FA_STAGES = REPORT_STAGES + ("mlt", "htt")


def row_id(sn: str, test: str, url: str = "", at: str = "") -> str:
    """Stable identity for one failure leaf, used to file that row's Jira."""
    return "|".join([sn or "", test or "", url or "", at or ""])


def group_id(sn: str, error_type: str, url: str = "") -> str:
    """One table row: one SN, one run, one error type."""
    return "|".join([sn or "", error_type or "", url or ""])


def summarize_sft(units: Dict[str, Dict[str, Any]], day: str) -> Dict[str, Any]:
    """L10 SFT for one day. Kept as the name the tests and callers already use."""
    return summarize_stage(units, day, "sft")


def summarize_stage(units: Dict[str, Dict[str, Any]], day: str,
                    stage: str) -> Dict[str, Any]:
    """One Daily FA report: last attempt decides pass/fail.

    A later pass is a pass and is listed. A later fail is a fail; if the
    chassis passed earlier that day, that pass time is kept on the fail rows.
    """
    key = stage + build_dailyexcel.ATTEMPTS_KEY
    tested = passed = failed = 0
    failed_sns: List[str] = []
    rows: List[Dict[str, Any]] = []
    for dut in sorted(units):
        attempts = _unique_runs([
            item for item in (units[dut].get(key) or [])
            if item.get("status") in ("pass", "fail")
        ])
        if not attempts:
            continue
        attempts.sort(key=lambda item: item.get("started") or "")
        final = attempts[-1]
        tested += 1
        if final["status"] == "pass":
            passed += 1
        else:
            failed += 1
            failed_sns.append(dut)
        rows.extend(_final_rows(dut, attempts, final))
    return _finish_report(day, stage, tested, passed, failed, failed_sns, rows)


def _pass_time(attempts: Sequence[Dict[str, Any]]) -> str:
    times = [item.get("started") or "" for item in attempts
             if item.get("status") == "pass"]
    return next((item for item in reversed(times) if item), "")


def _pass_row(dut: str, index: int, attempt: Dict[str, Any]) -> Dict[str, Any]:
    url = attempt.get("url") or ""
    at = attempt.get("started") or ""
    return {
        "id": group_id(dut, "Passed", url),
        "sn": dut,
        "errorType": "Passed",
        "test": "",
        "caseId": "",
        "at": at,
        "passAt": at,
        "code": "",
        "url": url,
        "jira": "",
        "dri": "",
        "attempt": index,
        "final": "pass",
        "status": "pass",
    }


def _final_rows(dut: str, attempts: Sequence[Dict[str, Any]],
                final: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Only the last attempt. Pass rows have no DRI / Jira."""
    pass_at = _pass_time(attempts)
    index = len(attempts)
    if final.get("status") == "pass":
        return [_pass_row(dut, index, final)]
    rows = _fail_rows(dut, index, "fail", final)
    for row in rows:
        row["passAt"] = pass_at
    return rows


def _fail_rows(dut: str, index: int, final: str,
               attempt: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for item in attempt.get("failures") or []:
        test = (item.get("test") or "").strip()
        if not test:
            continue
        at = item.get("at") or attempt.get("started") or ""
        url = attempt.get("url") or ""
        error_type = error_type_of_test(test)
        rows.append({
            "id": row_id(dut, test, url, at),
            "sn": dut,
            "errorType": error_type,
            "test": test,
            "caseId": (item.get("caseId") or test).strip(),
            "at": at,
            "code": (item.get("code") or "NA").strip() or "NA",
            "url": url,
            "jira": item.get("jira") or attempt.get("jira") or "",
            "dri": as_dri(item.get("dri") or "", error_type),
            "attempt": index,
            "final": final,
            "status": attempt.get("status") or "",
        })
    return rows


def _finish_report(day: str, stage: str, tested: int, passed: int,
                   failed: int, failed_sns: Sequence[str],
                   rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    kinds: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        test = row.get("test") or ""
        if not test:
            continue
        bucket = kinds.setdefault(test, {
            "test": test, "caseIds": [], "sns": [],
        })
        case_id = row.get("caseId") or test
        if case_id and case_id not in bucket["caseIds"]:
            bucket["caseIds"].append(case_id)
        if row.get("final") == "fail" and row.get("sn") \
                and row["sn"] not in bucket["sns"]:
            bucket["sns"].append(row["sn"])
    return {
        "day": day,
        "stage": stage,
        "station": STATION_OF.get(stage) or stage,
        "tested": tested,
        "passed": passed,
        "failed": failed,
        "yield": (passed / tested) if tested else None,
        "failedSns": list(failed_sns),
        "rows": list(rows),
        "kinds": [kinds[name] for name in sorted(kinds)],
    }


def _unique_runs(attempts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same ESVM URL (or the same start time) is one run, not two rows."""
    found: List[Dict[str, Any]] = []
    seen = set()
    for item in attempts:
        run = item.get("url") or item.get("started") or ""
        if run in seen:
            continue
        if run:
            seen.add(run)
        found.append(item)
    return found


def expand_fail_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn a stored report into one-row-per-failure, old or new shape.

    Yesterday's snapshot wrote one row per suite run, with tests joined by
    ``; ``. The table needs one leaf per row. Already-expanded rows pass
    through with an id filled in if they lost it.
    """
    found: List[Dict[str, Any]] = []
    for row in report.get("rows") or []:
        if row.get("status") == "pass" or row.get("errorType") == "Passed":
            item = dict(row)
            item["errorType"] = "Passed"
            item["dri"] = ""
            item["jira"] = item.get("jira") or ""
            item["id"] = item.get("id") or group_id(
                item.get("sn") or "", "Passed", item.get("url") or "")
            found.append(item)
            continue
        if row.get("errorType") or (
                row.get("test") and not row.get("tests")):
            item = dict(row)
            error_type = as_error_type(
                item.get("errorType") or "", item.get("test") or "")
            item["errorType"] = error_type
            item.setdefault("caseId", item.get("test") or "")
            item.setdefault("code", item.get("code") or "NA")
            item["id"] = item.get("id") or row_id(
                item.get("sn") or "", item.get("test") or "",
                item.get("url") or "", item.get("at") or "")
            item["dri"] = as_dri(item.get("dri") or "", error_type)
            if item.get("test"):
                found.append(item)
            continue
        tests = list(row.get("tests") or [])
        if not tests:
            tests = [part.strip() for part in
                     str(row.get("test") or "").split(";") if part.strip()]
        codes = [part.strip() for part in str(row.get("code") or "").split(";")]
        case_ids = list(row.get("caseIds") or [])
        for index, test in enumerate(tests):
            if not test:
                continue
            at = row.get("at") or ""
            url = row.get("url") or ""
            found.append({
                "id": row_id(row.get("sn") or "", test, url, at),
                "sn": row.get("sn") or "",
                "errorType": as_error_type(row.get("errorType") or "", test),
                "test": test,
                "caseId": case_ids[index] if index < len(case_ids) else test,
                "at": at,
                "code": codes[index] if index < len(codes) and codes[index]
                else (row.get("code") or "NA"),
                "url": url,
                "jira": row.get("jira") or "",
                "dri": as_dri(
                    row.get("dri") or "",
                    as_error_type(row.get("errorType") or "", test)),
                "attempt": row.get("attempt") or "",
                "final": row.get("final") or "",
                "status": row.get("status") or "",
            })
    return found


def group_fail_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same SN + run + error type is one table row; test cases stack."""
    order: List[str] = []
    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = group_id(row.get("sn") or "", row.get("errorType") or "",
                       row.get("url") or "")
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "id": key,
                "sn": row.get("sn") or "",
                "errorType": row.get("errorType") or "",
                "tests": [],
                "codes": [],
                "at": row.get("at") or "",
                "passAt": row.get("passAt") or "",
                "url": row.get("url") or "",
                "jira": row.get("jira") or "",
                "dri": as_dri(row.get("dri") or "",
                              row.get("errorType") or ""),
                "attempt": row.get("attempt") or "",
                "final": row.get("final") or "",
                "status": row.get("status") or "",
            }
            buckets[key] = bucket
            order.append(key)
        test = (row.get("test") or "").strip()
        if test and test not in bucket["tests"]:
            bucket["tests"].append(test)
        code = (row.get("code") or "").strip()
        for part in code.splitlines():
            part = part.strip()
            if part and part not in bucket["codes"]:
                bucket["codes"].append(part)
        if row.get("jira"):
            bucket["jira"] = row["jira"]
        if row.get("passAt"):
            bucket["passAt"] = row["passAt"]
        at = row.get("at") or ""
        if at and (not bucket["at"] or at < bucket["at"]):
            bucket["at"] = at
    found = []
    for key in order:
        bucket = buckets[key]
        bucket["test"] = ", ".join(bucket["tests"])
        if bucket.get("errorType") == "Passed":
            bucket["code"] = ""
        else:
            real = [code for code in bucket["codes"] if code != "NA"]
            bucket["codes"] = real or ["NA"]
            bucket["code"] = "\n".join(bucket["codes"])
        found.append(bucket)
    return found


def _station_for_stage(stage: str) -> Optional[str]:
    """Tracker column station for a Daily FA stage, including L6 MLT and HTT."""
    if stage in ("mlt", "htt"):
        return stage
    return STATION_OF.get(stage)


def report_from_table(l10: Dict[str, Any], stage: str) -> Optional[Dict[str, Any]]:
    """Coarse report from the tracker table when the stage report is absent.

    Only the latest attempt is on the row. Error codes are NA until the
    tracker is rebuilt from pega with leaf detail. The same walk builds an
    L6 MLT or HTT report from the module table.
    """
    station = _station_for_stage(stage)
    if not station:
        return None
    columns = l10.get("columns") or []
    result_at = sn_at = -1
    for index, column in enumerate(columns):
        if column.get("key") == "B":
            sn_at = index
        title = column.get("title") or ""
        if column.get("station") == station and column.get("kind") != "version" \
                and "Results" in title:
            result_at = index
    fail_at = link_at = -1
    if result_at >= 0:
        for index in range(result_at + 1, len(columns)):
            title = columns[index].get("title") or ""
            if fail_at < 0 and "Failure Test Case" in title:
                fail_at = index
            if title.startswith("FI Test Link"):
                link_at = index
                break
    if result_at < 0:
        return None
    day = l10.get("day") or ""
    tested = passed = failed = 0
    failed_sns: List[str] = []
    rows: List[Dict[str, Any]] = []

    def cell(row: Sequence[Any], at: int) -> Dict[str, Any]:
        if at < 0 or at >= len(row):
            return {}
        slot = row[at]
        return slot if isinstance(slot, dict) else {}

    for row in l10.get("rows") or []:
        tone = cell(row, result_at).get("t")
        sn = str(cell(row, sn_at).get("v") or "").strip()
        fail_names = [part.strip() for part in
                      str(cell(row, fail_at).get("v") or "").split("\n")
                      if part.strip()]
        link = str(cell(row, link_at).get("h") or "")
        history = ((cell(row, sn_at).get("history") or {}).get(station)) or []
        attempts = [item for item in history if item.get("day") == day]
        if not attempts and tone in ("pass", "fail"):
            attempts = [{
                "n": 1,
                "status": tone,
                "url": link,
                "failures": [
                    {"test": name, "caseId": name, "code": "NA", "at": ""}
                    for name in fail_names
                ] if tone == "fail" else [],
            }]
        if tone not in ("pass", "fail"):
            last = attempts[-1].get("status") if attempts else ""
            if last in ("pass", "fail"):
                tone = last
            else:
                continue
        if not attempts:
            continue
        tested += 1
        if tone == "pass":
            passed += 1
        elif tone == "fail":
            failed += 1
            if sn:
                failed_sns.append(sn)
        seen = set()
        unique: List[Dict[str, Any]] = []
        attempts = sorted(attempts, key=lambda item: item.get("n") or 0)
        for index, attempt in enumerate(attempts, start=1):
            url = attempt.get("url") or ""
            run = url or attempt.get("started") or "#{}".format(index)
            if run in seen:
                continue
            seen.add(run)
            failures = list(attempt.get("failures") or [])
            tests = [item.get("test") or "" for item in failures if item.get("test")]
            if not tests and attempt.get("status") == "fail" and (
                    attempt is attempts[-1] or not url or url == link):
                tests = list(fail_names)
                failures = [{"test": name, "caseId": name, "code": "NA",
                             "at": ""} for name in tests]
            unique.append(dict(attempt, failures=failures, url=url,
                               started=attempt.get("started") or ""))
        if unique:
            rows.extend(_final_rows(sn, unique, unique[-1]))
    report = _finish_report(day, stage, tested, passed, failed, failed_sns, rows)
    report["coarse"] = True
    return report


def _result_column(columns: Sequence[Any], station: str) -> int:
    for index, column in enumerate(columns):
        if not isinstance(column, dict):
            continue
        title = column.get("title") or ""
        if column.get("station") == station and column.get("kind") != "version" \
                and "Results" in title:
            return index
    return -1


def report_from_verdicts(tab: Dict[str, Any], stage: str
                         ) -> Optional[Dict[str, Any]]:
    """One station's Daily FA report from the result cells on the tracker row.

    The cell is the verdict the daily tracker already quotes. A same-day
    attempt that exists only in the history strip is not a result.
    """
    station = _station_for_stage(stage)
    if not station:
        return None
    columns = tab.get("columns") or []
    result_at = _result_column(columns, station)
    if result_at < 0:
        return None
    sn_at = next((index for index, column in enumerate(columns)
                  if isinstance(column, dict) and column.get("key") == "B"), -1)
    jira_at = next((index for index, column in enumerate(columns)
                    if isinstance(column, dict) and column.get("title") == "Jira"),
                   -1)
    fail_at = link_at = -1
    for index in range(result_at + 1, len(columns)):
        column = columns[index]
        if not isinstance(column, dict):
            continue
        title = column.get("title") or ""
        if fail_at < 0 and "Failure Test Case" in title:
            fail_at = index
        if title.startswith("FI Test Link"):
            link_at = index
            break

    def cell(row: Sequence[Any], at: int) -> Dict[str, Any]:
        if at < 0 or at >= len(row) or not isinstance(row[at], dict):
            return {}
        return row[at]

    tested = passed = failed = 0
    failed_sns: List[str] = []
    rows: List[Dict[str, Any]] = []
    day = tab.get("day") or ""
    for row in tab.get("rows") or []:
        tone = cell(row, result_at).get("t")
        if tone not in ("pass", "fail"):
            continue
        sn = str(cell(row, sn_at).get("v") or "").strip()
        link = str(cell(row, link_at).get("h") or "")
        fail_names = [part.strip() for part in
                      str(cell(row, fail_at).get("v") or "").split("\n")
                      if part.strip()]
        times = _case_times(link) if tone == "fail" else {}
        attempt = {
            "status": tone,
            "url": link,
            "started": times.get("") or "",
            "failures": [
                {"test": name, "caseId": name, "code": "NA",
                 "at": times.get(name) or times.get("") or ""}
                for name in fail_names
            ] if tone == "fail" else [],
        }
        tested += 1
        if tone == "pass":
            passed += 1
        else:
            failed += 1
            if sn:
                failed_sns.append(sn)
        leaves = _final_rows(sn, [attempt], attempt)
        ticket = _sheet_jira(cell(row, jira_at)) if tone == "fail" else ""
        if ticket:
            for item in leaves:
                item["jira"] = ticket
        rows.extend(leaves)
    if not tested:
        return None
    report = _finish_report(day, stage, tested, passed, failed, failed_sns, rows)
    report["coarse"] = True
    return report


def _sheet_jira(cell: Dict[str, Any]) -> str:
    """The tracker's own Jira cell, as a browse URL. Empty if it has no key."""
    keys = cell.get("j") if isinstance(cell.get("j"), list) else []
    key = str(keys[0]).strip() if keys else ""
    if not key:
        found = build_dailyexcel.JIRA_KEY.search(str(cell.get("v") or ""))
        key = found.group(1) if found else ""
    if not key:
        return ""
    from . import links
    return "{}/{}".format(links.jira_base().rstrip("/"), key)


def _case_times(url: str) -> Dict[str, str]:
    """Start time of each failing test in a cached suite run.

    Key ``""`` is the run's own start. Nothing is fetched: a missing cache
    leaves the Test time column blank rather than blocking the page on pega.
    """
    run_id = run_id_from_url(url)
    if not run_id:
        return {}
    host = ""
    named = re.search(r"//(?:.*?)?(pega\d+)", url or "", re.IGNORECASE)
    if named:
        host = named.group(1).lower()
    detail = pega._read_cache("/api/test_suite_run/" + run_id, host or None)
    if not isinstance(detail, dict):
        return {}
    times: Dict[str, str] = {}
    started = str(detail.get("start_time") or "")
    if started:
        times[""] = started
    for case in detail.get("test_cases") or []:
        name = str(case.get("test_name") or "").strip()
        at = str(case.get("start_time") or "")
        if name and at and name not in times:
            times[name] = at
    return times


def _cell_tone(row: Sequence[Any], at: int) -> str:
    if at < 0 or at >= len(row):
        return ""
    slot = row[at]
    if not isinstance(slot, dict):
        return ""
    return slot.get("t") or ""


def combined_module_yield(tab: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Units that passed both, over units that entered MLT.

    Not MLT% × HTT%. A module can pass MLT and never reach HTT, and HTT's
    own population includes modules that did not pass MLT that day.
    """
    columns = tab.get("columns") or []
    mlt_at = _result_column(columns, "mlt")
    htt_at = _result_column(columns, "htt")
    if mlt_at < 0:
        return None
    tested = passed = no_htt = 0
    for row in tab.get("rows") or []:
        mlt = _cell_tone(row, mlt_at)
        htt = _cell_tone(row, htt_at)
        if mlt not in ("pass", "fail"):
            continue
        tested += 1
        if mlt == "pass" and htt not in ("pass", "fail"):
            no_htt += 1
        if mlt == "pass" and htt == "pass":
            passed += 1
    if not tested:
        return None
    return {
        "passed": passed,
        "tested": tested,
        "yield": passed / tested,
        "noHtt": no_htt,
    }


def l6_from_tab(tab: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """L6 MLT and HTT reports for one day, from the module tracker table."""
    columns = tab.get("columns") if isinstance(tab, dict) else None
    if not any(isinstance(column, dict) and column.get("station") in ("mlt", "htt")
               for column in columns or []):
        return None
    sheet = dict(tab)
    sheet["day"] = tab.get("day") or ""
    mlt = report_from_verdicts(sheet, "mlt")
    htt = report_from_verdicts(sheet, "htt")
    if mlt is None and htt is None:
        return None
    return {
        "mltReport": mlt,
        "httReport": htt,
        "combined": combined_module_yield(sheet),
    }


def normalize_report(report: Optional[Dict[str, Any]],
                     stage: str) -> Optional[Dict[str, Any]]:
    """Idempotent: expand old run-rows and stamp stage / station."""
    if not report:
        return None
    out = dict(report)
    out["stage"] = out.get("stage") or stage
    out["station"] = out.get("station") or STATION_OF.get(stage) or ""
    out["rows"] = expand_fail_rows(out)
    return out


def sft_csv(report: Dict[str, Any]) -> str:
    """Failure table as CSV. One row per failing leaf."""
    return stage_csv(report)


def stage_csv(report: Dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["sn", "errorType", "test", "testedAt", "errorCode",
                     "pegaUrl", "dri", "jira"])
    for row in group_fail_rows(expand_fail_rows(report)):
        writer.writerow([
            row.get("sn") or "", row.get("errorType") or "",
            row.get("test") or "", row.get("at") or "",
            row.get("code") or "", row.get("url") or "",
            as_dri(row.get("dri") or "", row.get("errorType") or ""),
            row.get("jira") or "",
        ])
    return buffer.getvalue()


def unit_failures(detail: Dict[str, Any]) -> str:
    """Every test case that failed in the run, oldest first, one per line.

    No slot filtering: an L10 run is one chassis, so every failure in it is that
    chassis's. Containers are still skipped — a nest fails because a leaf under
    it did, and the leaf is the signature worth reading.
    """
    seen: List[str] = []
    for case in sorted(detail.get("test_cases") or [],
                       key=lambda c: c.get("start_time") or ""):
        status = str(case.get("status") or "").lower()
        if not status.startswith(("fail", "error")):
            continue
        name = (case.get("test_name") or "").strip()
        if not name or rootcause.is_container(name) or name in seen:
            continue
        seen.append(name)
    return "\n".join(seen)


# --------------------------------------------------------------------- build

def build_bundle(days: int = DEFAULT_DAYS) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    tabs = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        tab = _day(day)
        if tab:
            tabs.append(tab)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "source": {
            "workbook": "pega4 · L10 stations pt2_l10_station6 / 7",
            "controller": pega.base_url().replace("pega3", "pega4"),
            "url": "",
            "tabsInWorkbook": len(tabs),
            "modifiedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
        "tabs": tabs,
        # No cross-reference is performed for L10 — there is no sheet to check
        # against — so the page must not print a "0 of N resolve" note that
        # would read as a failure rather than as an absence.
        "crossref": {"matched": 0, "duts": 0},
        "links": {"jiraBase": None, "ocp": {}},
        "warnings": [],
    }


def _columns() -> List[Dict[str, Any]]:
    """Date, chassis, part, then four columns per stage.

    The same shape as the module tracker — result, version, failure, link —
    so the two pages read alike and share one renderer and one tally. The
    version column is what lets a reader tell an L10_FAT_207 run from an
    L10_FAT one without opening the link.

    No Jira column: its keys come from the module line's hand-kept sheet, and
    L10 has no sheet. An always-empty column is worse than an absent one.
    """
    columns = [
        {"key": "A", "title": "Date", "width": None},
        # Just "SN". It read "Chassis SN", then "DUT SN", and the heading is
        # the wrong place for the argument either way: the three daily tables
        # are read together, and each naming its own subject in the column head
        # made one column at three levels look like three different things. The
        # section heading above the table says L10 and counts chassis, which is
        # where the subject belongs. build_dailyexcel._serial_heading does the
        # same for the module table, whose title comes from the workbook.
        {"key": "B", "title": "SN", "width": 16.0},
        {"key": "C", "title": "DUT PN", "width": 14.0},
    ]
    index = 3
    for key, label, _pattern in STAGES:
        station = STATION_OF[key]
        columns.append({
            "key": xlsx.column_letters(index), "title": "{} Results".format(label),
            "width": 11.0, "station": station,
        })
        columns.append({
            "key": xlsx.column_letters(index + 1),
            "title": "{} Version".format(label), "width": 26.0,
            "kind": "version", "station": station,
        })
        columns.append({
            "key": xlsx.column_letters(index + 2),
            "title": "{} Failure Test Case".format(label), "width": 34.0,
        })
        columns.append({
            "key": xlsx.column_letters(index + 3), "title": "FI Test Link",
            "width": 10.0,
        })
        index += 4
    return columns


def stage_index(first: str, last: str
                ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """Every attempt each stage made over a whole span, read once.

    The per-tab walk this replaces re-read the same runs for every day the
    tracker published — affordable only while the history reached 30 days and
    the tracker began in August. Over the controllers' full retention it was
    tens of seconds per tab.
    """
    return build_dailyexcel.attempt_index(
        "pega4", [key for key, _l, _p in STAGES],
        lambda entry: stage_of(entry.get("suite_name")),
        lambda run_id, slot: pega.run_url(run_id, slot, host="pega4"),
        first, last)


def _seen_before(day: str, lookback: Optional[int] = None
                 ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """Every attempt each L10 stage made on a chassis before ``day``.

    Same rule as the module tracker, so "new input" means the same thing on
    both pages: a chassis the stage had not seen in the ten days before this
    one. Keyed by stage rather than by station so the caller can look up with
    the key it already has.
    """
    # Late-bound rather than a default argument: the reach is derived from
    # pega.HISTORY_FROM, and a default freezes it at import, so moving the
    # floor left this function reaching a distance nothing else used.
    if lookback is None:
        lookback = build_dailyexcel.NEW_INPUT_LOOKBACK

    # FACTORY_PEGA=0 means no controllers, here as well as on the module
    # tracker — build_dailyexcel._seen_before has always had this guard and
    # these two never did. It went unnoticed while the reach was 30 days of
    # mostly-cached listings; deepening it to the history floor on 2026-09-08
    # turned the same path into 144 live requests inside a test suite that
    # believed it had switched the integration off.
    if not pega.enabled():
        return {key: {} for key, _label, _pattern in STAGES}

    start = datetime.strptime(day, "%Y-%m-%d").date()
    first = max(pega.HISTORY_FROM,
                (start - timedelta(days=lookback)).strftime("%Y-%m-%d"))
    last = (start - timedelta(days=1)).strftime("%Y-%m-%d")
    return build_dailyexcel.slice_before(
        stage_index(first, last), day, lookback)


def _day(day: str, history_index: Optional[Dict[str, Any]] = None
         ) -> Optional[Dict[str, Any]]:
    """One day's L10 tab.

    ``index`` is the span read once by the caller (see :func:`stage_index`);
    without one this reads the history it needs itself, which is what a
    standalone call does.
    """
    # Switched off means switched off. The call site cannot know: it guards
    # the shared span read with pega.enabled() and then asks for the day
    # anyway, so the guard belongs here, where the request is made.
    if not pega.enabled():
        return None
    try:
        listing = pega.day_suite_runs(day, host="pega4")
    except pega.PegaUnavailable:
        return None

    from . import build_errors
    codes = build_errors.by_case(build_errors.catalogue())

    columns = _columns()
    index = {column["key"]: position for position, column in enumerate(columns)}
    slot_of = {key: xlsx.column_letters(3 + position * 4)
               for position, (key, _l, _p) in enumerate(STAGES)}

    units: Dict[str, Dict[str, Any]] = {}
    runs_seen = 0
    for entry in listing:
        stage = stage_of(entry.get("suite_name"))
        if not stage:
            continue
        run_id = entry.get("suite_run_id") or ""
        try:
            detail = pega.suite_run(run_id, host="pega4")
        except pega.PegaUnavailable:
            continue
        runs_seen += 1
        started = entry.get("start_time") or ""

        for part in pega.participants(detail):
            unit = units.setdefault(part["dut"], {
                "pn": entry.get("dut_part_number") or "",
            })
            # Every attempt of the day, recorded before the guard below can
            # drop this run. The row keeps one; the Test History strip beside
            # it keeps all of them. On 09-01 268645440002 failed FAT at 13:21
            # and passed at 15:26 — the row is the pass, and without this the
            # 13:21 failure appears nowhere on the page.
            if part["status"] in ("pass", "fail"):
                attempt = {
                    "day": day,
                    "status": part["status"],
                    "url": pega.run_url(run_id, part["slot"], host="pega4"),
                    "suite": entry.get("suite_name") or "",
                    "started": started,
                }
                # Daily FA needs the leaf list for FAT, SFT and RIN — every
                # attempt, not just the latest. The tracker row still shows
                # only the last verdict.
                if stage in REPORT_STAGES and part["status"] == "fail":
                    # One download per failed run, during the daily rebuild.
                    # The codes from every diagnosis land in dailyfa.js; the
                    # review host never fetches the log itself.
                    from . import th_logs
                    attempt["failures"] = failure_details(
                        detail, codes,
                        th_logs.codes_for_run(run_id, host="pega4", day=day),
                        run_id)
                unit.setdefault(stage + build_dailyexcel.ATTEMPTS_KEY,
                                []).append(attempt)

            # Latest attempt wins, as on the module tracker: one row per unit
            # per day, showing where it ended up rather than where it started.
            previous = unit.get(stage)
            if previous and previous["started"] >= started:
                continue
            unit[stage] = {
                "suite": entry.get("suite_name") or "",
                "status": part["status"],
                "fail": unit_failures(detail) if part["status"] == "fail" else "",
                "url": pega.run_url(run_id, part["slot"], host="pega4"),
                "short": run_id.rsplit("_run_", 1)[-1],
                "started": started,
            }

    if not units:
        return None

    def sort_key(item):
        dut, unit = item
        bad = any((unit.get(k) or {}).get("status") == "fail" for k, _l, _p in STAGES)
        return (bad, dut)

    history = (build_dailyexcel.slice_before(
                   history_index, day, build_dailyexcel.NEW_INPUT_LOOKBACK)
               if history_index is not None else _seen_before(day))

    rows = []
    for dut, unit in sorted(units.items(), key=sort_key):
        row = [{} for _ in columns]
        row[index["A"]] = {"v": day}
        serial: Dict[str, Any] = {"v": dut}
        for key, _label, _pattern in STAGES:
            if key not in unit:
                continue
            station = STATION_OF[key]
            past = (history.get(key) or {}).get(dut) or []
            today = build_dailyexcel._day_attempts(unit, key)
            # New input is still decided on the days before this one; the
            # strip is what carries today.
            if past:
                serial.setdefault("seen", {})[station] = past[-1]["day"]
            if past or len(today) > 1:
                serial.setdefault("history", {})[station] = \
                    build_dailyexcel._numbered_history(past, today)
        serial["new"] = "seen" not in serial
        row[index["B"]] = serial
        if unit.get("pn"):
            row[index["C"]] = {"v": unit["pn"]}
        for key, _label, _pattern in STAGES:
            got = unit.get(key)
            if not got:
                continue
            base = slot_of[key]
            offset = xlsx.column_index(base)
            if got["status"] in ("pass", "fail"):
                row[offset] = {"v": "Passed" if got["status"] == "pass" else "Failed",
                               "t": got["status"]}
            row[offset + 1] = {"v": got["suite"]}
            if got["fail"]:
                row[offset + 2] = {"v": got["fail"]}
            row[offset + 3] = {"v": got["short"], "h": got["url"]}
        rows.append(row)

    tab = {
        "name": "{} (from pega4)".format(day),
        "label": day[5:],
        "day": day,
        "claimedUnits": None,
        "derived": True,
        "derivedFrom": {
            "runs": runs_seen,
            "source": "pega4",
            "versions": {},
            "note": "Rebuilt from pega4, which drives the L10 stations.",
        },
        "columns": columns,
        "rows": rows,
        "counts": _counts(rows, columns),
        "crossref": {"matched": 0, "duts": len(units)},
    }
    for stage in REPORT_STAGES:
        tab[REPORT_KEY[stage]] = summarize_stage(units, day, stage)
    return tab


def _counts(rows, columns) -> Dict[str, Any]:
    """Pass/fail per stage — the module tracker's tally, reused.

    Shared rather than reimplemented: it produces the new-input and
    release-only breakdowns the page's Count all button needs, and two copies
    of that arithmetic would be two chances to count a day differently on two
    pages of one dashboard.
    """
    return build_dailyexcel._counts(rows, columns)


def open_sync_days(now: Optional[datetime] = None) -> List[str]:
    """UTC today, yesterday, and the factory-local today — the days still moving."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    utc_day = moment.astimezone(timezone.utc).date()
    try:
        from zoneinfo import ZoneInfo
        local_day = moment.astimezone(ZoneInfo(config.timezone_name())).date()
    except Exception:  # noqa: BLE001
        local_day = utc_day
    days = {utc_day, utc_day - timedelta(days=1), local_day}
    return [item.strftime("%Y-%m-%d") for item in sorted(days)]


def parse_day(value: Any) -> Optional[str]:
    """A YYYY-MM-DD string, or None if it is not a calendar day."""
    text = str(value or "").strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def refresh_days(days: Sequence[str],
                 drop: bool = True) -> Dict[str, Optional[Dict[str, Any]]]:
    """Re-read L10 for these days from pega4, dropping stale day listings."""
    wanted = []
    for day in days:
        parsed = parse_day(day)
        if parsed and parsed not in wanted:
            wanted.append(parsed)
    if not wanted:
        return {}
    if not pega.enabled():
        return {day: None for day in wanted}
    if drop:
        try:
            pega.drop_listings(min(wanted), max(wanted), hosts=("pega4",))
        except OSError:
            pass
    return {day: _day(day) for day in wanted}


def merge_l10_into_bundle(
        bundle: Dict[str, Any],
        l10_by_day: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Stamp refreshed L10 tabs into the daily tracker, adding missing days."""
    tabs = list(bundle.get("tabs") or [])
    by_day = {tab.get("day"): tab for tab in tabs if tab.get("day")}
    template = next((tab for tab in reversed(tabs) if tab.get("columns")), None)
    added: List[str] = []
    updated: List[str] = []
    for day, l10 in l10_by_day.items():
        if not l10:
            continue
        tab = by_day.get(day)
        if tab is None:
            tab = _l10_only_module_tab(day, template)
            tabs.append(tab)
            by_day[day] = tab
            added.append(day)
        tab["l10"] = l10
        updated.append(day)
    tabs.sort(key=lambda tab: tab.get("day") or "")
    bundle["tabs"] = tabs
    bundle["generatedAt"] = datetime.now(timezone.utc).replace(
        microsecond=0).isoformat()
    return {"added": added, "updated": updated}


def _l10_only_module_tab(day: str,
                         template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A clickable calendar day that has L10 but no module-sheet row yet."""
    columns = list((template or {}).get("columns") or [
        {"key": "A", "title": "Date"},
        {"key": "B", "title": "SN"},
    ])
    return {
        "name": "{} (from pega4)".format(day),
        "label": day[5:],
        "day": day,
        "derived": True,
        "claimedUnits": None,
        "columns": columns,
        "rows": [],
        "counts": {},
        "crossref": {"matched": 0, "duts": 0},
    }
