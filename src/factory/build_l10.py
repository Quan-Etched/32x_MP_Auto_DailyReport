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
                   by_case: Optional[Dict[str, List[Dict[str, Any]]]] = None
                   ) -> List[Dict[str, str]]:
    """One record per failing leaf: test name, case id, code, time.

    The code is the one the run itself recorded. When the run has none and
    the catalogue names exactly one code for that test, that code is used.
    Several catalogue codes, or none, is ``NA`` — picking one would invent
    a diagnosis the run did not make.
    """
    known = by_case or {}
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
            "code": _case_code(case, name, known),
            "at": str(case.get("start_time") or ""),
        })
    return found


def _case_code(case: Dict[str, Any], name: str,
               by_case: Dict[str, List[Dict[str, Any]]]) -> str:
    for key in ("error_code", "errorCode", "code", "failure_code"):
        value = case.get(key)
        if value:
            return str(value).strip()
    codes = []
    for entry in by_case.get(name) or []:
        code = str(entry.get("code") or "").strip()
        if code and code not in codes:
            codes.append(code)
    if len(codes) == 1:
        return codes[0]
    return "NA"


#: L10_FLOW_TEST_COVERAGE column C — one Jira family per stage, not per test.
FLOW_STAGES_PATH = config.REPO_ROOT / "errors" / "l10_flow_stages.json"

_flow_stages: Optional[Dict[str, str]] = None
_flow_index: Optional[Dict[str, str]] = None


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


def stage_of_test(name: str) -> str:
    """Coverage-sheet column C for a leaf test. Unknown names stay their own family."""
    raw = (name or "").strip()
    if not raw:
        return ""
    tests, index = _load_flow_stages()
    if raw in tests:
        return tests[raw]
    folded = _norm_test(raw)
    if folded in index:
        return index[folded]
    if len(folded) >= 8:
        best = ""
        found = ""
        for key, stage in index.items():
            if len(key) < 8:
                continue
            if folded.startswith(key) or key.startswith(folded):
                if len(key) > len(best):
                    best, found = key, stage
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


def is_c2c(name: str) -> bool:
    """C2C link / PRBS / integrity / throughput / stability tests."""
    return stage_of_test(name) == "Sohu C2C" or "c2c" in (name or "").lower()


def summarize_sft(units: Dict[str, Dict[str, Any]], day: str) -> Dict[str, Any]:
    """L10 SFT for one day, one CSV row per suite run.

    A later pass replaces an earlier fail: the chassis passed. A later fail
    does not add a second failed chassis. Passes are in the CSV too. The same
    ESVM run is written once — one SN, one attempt, one time, one URL.
    """
    key = "sft" + build_dailyexcel.ATTEMPTS_KEY
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
        for index, attempt in enumerate(attempts, start=1):
            rows.append(_run_row(dut, index, final["status"], attempt))
    kinds: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        for test, case_id in zip(row.get("tests") or [],
                                 row.get("caseIds") or []):
            if not test:
                continue
            bucket = kinds.setdefault(test, {
                "test": test, "caseIds": [], "sns": [],
            })
            if case_id and case_id not in bucket["caseIds"]:
                bucket["caseIds"].append(case_id)
            if row.get("final") == "fail" and row["sn"] not in bucket["sns"]:
                bucket["sns"].append(row["sn"])
    return {
        "day": day,
        "station": "l10_sft",
        "tested": tested,
        "passed": passed,
        "failed": failed,
        "yield": (passed / tested) if tested else None,
        "failedSns": failed_sns,
        "rows": rows,
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


def _run_row(dut: str, index: int, final: str,
             attempt: Dict[str, Any]) -> Dict[str, Any]:
    failures = list(attempt.get("failures") or [])
    tests = [item.get("test") or "" for item in failures if item.get("test")]
    codes = [(item.get("code") or "NA") for item in failures if item.get("test")]
    case_ids = [item.get("caseId") or "" for item in failures if item.get("test")]
    return {
        "sn": dut,
        "attempt": index,
        "final": final,
        "status": attempt.get("status") or "",
        "test": "; ".join(tests),
        "tests": tests,
        "code": "; ".join(codes),
        "caseIds": case_ids,
        "at": attempt.get("started") or (failures[0].get("at") if failures else ""),
        "url": attempt.get("url") or "",
        "c2c": any(is_c2c(name) for name in tests),
        "jira": attempt.get("jira") or "",
    }


def sft_csv(report: Dict[str, Any]) -> str:
    """One row per suite run: pass or fail. No case id — that is Jira's."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["sn", "attempt", "final", "test", "errorCode",
                     "testedAt", "esvmUrl", "jira"])
    for row in report.get("rows") or []:
        writer.writerow([
            row.get("sn") or "", row.get("attempt") or "",
            row.get("final") or "", row.get("test") or "",
            row.get("code") or "", row.get("at") or "",
            row.get("url") or "", row.get("jira") or "",
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
                # Only SFT keeps the leaf list. The other stages already show
                # their latest failure on the row; the report needs every
                # attempt, and only for the station it counts.
                if stage == "sft" and part["status"] == "fail":
                    attempt["failures"] = failure_details(detail, codes)
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

    return {
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
        "sftReport": summarize_sft(units, day),
    }


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
