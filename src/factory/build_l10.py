"""The L10 daily tracker — FAT, SFT, RIN and 2U, from pega4.

WHY A SECOND TRACKER RATHER THAN MORE COLUMNS ON THE FIRST
----------------------------------------------------------
The module tracker follows a *unit* through MLT and HTT. L10 follows a
*chassis* through four stages, and the two do not share a DUT: a module serial
is fifteen digits, an L10 chassis serial is twelve, and one chassis contains
many modules. Putting them on one page would invite a reader to scan across a
row that has no single subject.

Same format, same renderer, different subject.

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

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, pega, rootcause, version, xlsx

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
    """Date, unit, part, then three columns per stage.

    No Jira column: its keys come from the module line's hand-kept sheet, and
    L10 has no sheet. An always-empty column is worse than an absent one.
    """
    columns = [
        {"key": "A", "title": "Date", "width": None},
        {"key": "B", "title": "Chassis SN", "width": 16.0},
        {"key": "C", "title": "DUT PN", "width": 14.0},
    ]
    index = 3
    for _key, label, _pattern in STAGES:
        for suffix, width in (("Results", 11.0), ("Failure Test Case", 34.0),
                              ("FI Test Link", 10.0)):
            columns.append({
                "key": xlsx.column_letters(index),
                "title": "{} {}".format(label, suffix) if suffix != "FI Test Link"
                         else "FI Test Link",
                "width": width,
            })
            index += 1
    return columns


def _day(day: str) -> Optional[Dict[str, Any]]:
    try:
        listing = pega.day_suite_runs(day, host="pega4")
    except pega.PegaUnavailable:
        return None

    columns = _columns()
    index = {column["key"]: position for position, column in enumerate(columns)}
    slot_of = {key: xlsx.column_letters(3 + position * 3)
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
            # Latest attempt wins, as on the module tracker: one row per unit
            # per day, showing where it ended up rather than where it started.
            previous = unit.get(stage)
            if previous and previous["started"] >= started:
                continue
            unit[stage] = {
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

    rows = []
    for dut, unit in sorted(units.items(), key=sort_key):
        row = [{} for _ in columns]
        row[index["A"]] = {"v": day}
        row[index["B"]] = {"v": dut}
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
            if got["fail"]:
                row[offset + 1] = {"v": got["fail"]}
            row[offset + 2] = {"v": got["short"], "h": got["url"]}
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
    }


def _counts(rows, columns) -> Dict[str, Any]:
    """Pass/fail per stage, for the tiles above the table."""
    counts = {}
    for position, (key, label, _pattern) in enumerate(STAGES):
        column = xlsx.column_letters(3 + position * 3)
        offset = xlsx.column_index(column)
        tally = {"pass": 0, "fail": 0, "blank": 0}
        for row in rows:
            tone = (row[offset] or {}).get("t")
            tally[tone if tone in tally else "blank"] += 1
        counts[column] = dict(tally, title="{} Results".format(label))
    return counts


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "l10daily.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    # Same global as the module tracker: one page loads one bundle, and sharing
    # the name lets both pages run the identical renderer.
    target.write_text(
        "// Generated by `python -m factory.cli l10` — do not edit.\n"
        "window.__FACTORY_DAILY_EXCEL__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target
