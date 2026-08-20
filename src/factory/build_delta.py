"""The hand-kept sheet against this repo's own reading of the same day.

WHY A THIRD VIEW OF ONE DAY
---------------------------
The daily tracker page has two kinds of tab. Some are a faithful copy of a tab
the line wrote; the rest are rebuilt from the controllers for days the exported
workbook does not carry. Both are shown as *the* tracker, and where the line
keeps its own tab for a day the repo has also rebuilt, nobody has ever put the
two side by side.

They do not agree. On 2026-08-20 the sheet holds 78 units and the controllers
hold 107; the MLT yield comes out within a point either way, and the HTT yield
differs by six. A page that shows one of those numbers without the other is
quoting a yield whose population nobody has checked.

So this compares them, unit by unit, and says which side each figure came from.

WHAT IT IS NOT
--------------
Not a correction. Neither side is treated as truth: the sheet is the line's own
judgement of what passed, written by the people who were standing at the
fixture, and the controllers are the machine's record of what it ran. Each knows
something the other does not, and both have been wrong. Every row here says what
the two say and classifies *why* they differ; where the difference can be
settled from the controllers, it says so, and where it cannot, it says that
instead.

The classes, and what each one means:

``population``
    The unit is on one side only. Almost always the sheet missing units the
    controllers ran — a tab written during a shift does not have the evening's
    runs in it.
``status``
    The pass/fail verdicts differ, blank included. The most consequential class,
    because it is the one that moves a yield.
``case-missing``
    The sheet says a unit failed and names nothing. An empty failure cell beside
    "Failed" is the one thing that column must never say.
``case-prose``
    The sheet names something that is not a test case ("chip not enumerated by
    RPC proxy"). A human summary, and more use than a class name to whoever
    wrote it — but it cannot be counted, grouped or linked.
``case-fixture``
    The sheet attributes a failure the controller recorded at *fixture* level,
    with no slot, to an individual unit. PcieSetupTestCase failing once for the
    whole tray is not eight units failing PcieSetupTestCase, and this is the
    single largest class of real error found so far.
``case-nest-only``
    The controller recorded only the nesting wrapper for this slot, so the
    online cell says SltModuleNestedTestCase and means "something failed here".
    The sheet often carries the actual leaf, read out of the run log. Here the
    *sheet* holds what the dashboard cannot see.
``case-subset`` / ``case-extra``
    One side's list is contained in the other's. Usually the sheet recording the
    first failure where the controller recorded all of them.
``case-conflict``
    Neither list contains the other and the controllers do not explain it. Left
    for a person.

THE CUT TIME IS HALF THE ANSWER
-------------------------------
A sheet is written by somebody watching a shift, and it stops when they do. The
08-20 tab was cut at 23:00 with the line still running until 02:00, which on its
own accounts for most of the population gap — the controllers are not holding
units the sheet lost, they are holding units that ran after the sheet was put
down. ``diff/delta.json`` records that cut, and the page leads with it, because
"29 units missing" and "29 units ran after the sheet was cut" are the same
number and completely different news.

The same file records what was *reported* off the tab at that cut — the figures
someone posted to Slack. That is a third reading, kept beside the other two and
never merged into either: it is the number people acted on, and where it no
longer matches the tab it was read from, the tab has moved since. On 08-20 the
HTT figures still match it exactly and the MLT figures have gained eight rows,
which dates the sheet's last edit more precisely than its file timestamp does.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import build_dailyexcel, chips, config, pega, rootcause, version, xlsx

#: Where the hand-kept workbook to compare against lives.
DEFAULT_DIR = config.REPO_ROOT / "diff"

#: The tab-to-gid map and the sheet URL, beside the workbook it describes.
CONFIG_NAME = "delta.json"

#: A tab name that starts with a month-day, as the line writes them
#: ("08-20 MLT  HTT Run"). Used for the label and as a cross-check on the
#: configured day, never to discover tabs — see below.
TAB_DAY = re.compile(r"^\s*(\d{2})-(\d{2})\b")

#: A test-case class name: CamelCase, no spaces. Anything else in a failure
#: cell is prose — worth keeping, impossible to count.
CASE_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")

#: How the sheet and the controllers spell one verdict.
VERDICT = {
    "pass": "pass", "passed": "pass", "p": "pass",
    "fail": "fail", "failed": "fail", "f": "fail",
    "abort": "abort", "aborted": "abort", "error": "abort",
    "skip": "blank", "n/a": "blank", "na": "blank", "-": "blank", "": "blank",
}

#: Which sheet column is which, matched on the header text rather than on a
#: letter. The line moves columns; it does not rename them.
HEADERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("sn", ("dut sn", "dut serial", "sn")),
    ("asic", ("asic sn",)),
    ("pn", ("dut pn",)),
    ("mlt", ("mlt results", "mlt result")),
    ("mltCase", ("mlt failure test case", "mlt failure")),
    ("mltLink", ("fi test link",)),          # first one belongs to MLT
    ("htt", ("htt results", "htt result")),
    ("httCase", ("htt failure test case", "htt failure")),
    ("httLink", ("fi test link",)),          # second one belongs to HTT
    ("note", ("note",)),
    ("jira", ("jira",)),
    ("bonepile", ("bonepile",)),
)

STATIONS = (("mlt", "MLT"), ("htt", "HTT"))


class NoWorkbook(RuntimeError):
    """No hand-kept workbook to compare against — the section stays empty."""


# ------------------------------------------------------------------ the sheet

def workbook_path(explicit: Optional[str] = None) -> Path:
    """The workbook to compare against: newest .xlsx in diff/.

    Deliberately a different directory from daily/. That one holds the export
    the dashboard *publishes*; this one holds an export somebody is checking it
    against, and pointing both at one file would make the comparison compare a
    thing with itself.
    """
    chosen = explicit or os.environ.get("FACTORY_DIFF_XLSX", "").strip()
    if chosen:
        path = Path(chosen).expanduser()
        if not path.exists():
            raise NoWorkbook("FACTORY_DIFF_XLSX points at {}".format(path))
        return path

    candidates = sorted(DEFAULT_DIR.glob("*.xlsx"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise NoWorkbook(
            "no .xlsx in {} — put the hand-kept export there to compare the "
            "published day against it".format(DEFAULT_DIR))
    return candidates[0]


def settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """The sheet URL and per-tab gid, or empty where nobody has recorded them."""
    note = (path or DEFAULT_DIR) / CONFIG_NAME
    if not note.exists():
        return {}
    try:
        return json.loads(note.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _header_map(row: Sequence[xlsx.Cell]) -> Dict[str, str]:
    """Sheet column letters, keyed by what this module calls them.

    The two ``FI Test Link`` columns are told apart by position: the first
    follows MLT's failure column and the second HTT's, which is the only thing
    that distinguishes them — they have the same heading.
    """
    titles = [(cell.column,
               re.sub(r"\s+", " ", (cell.value or "").split("\n")[0]).strip().lower())
              for cell in row]
    found: Dict[str, str] = {}
    used: set = set()
    for key, wanted in HEADERS:
        for column, title in titles:
            if column in used or not title:
                continue
            if title in wanted:
                found[key] = column
                used.add(column)
                break
    return found


def _verdict(text: str) -> str:
    return VERDICT.get((text or "").strip().lower(), (text or "").strip().lower())


def _serial(text: str) -> str:
    """The serial as the line writes it, out of however Excel stored it.

    The sheet keeps DUT SN as a *number*, so the reader gets
    ``2.68524700000105E14`` and the sheet itself shows ``2.68525E+14`` to
    whoever opens it. Fifteen digits still round-trip through a float exactly,
    so nothing is lost yet — but a sixteen-digit serial would lose its last
    digit silently, and that is worth saying out loud on the page rather than
    discovering from a mismatch.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if "E" in text.upper():
        try:
            import decimal
            return str(int(decimal.Decimal(text)))
        except Exception:                                 # noqa: BLE001
            return text
    return text.split(".")[0]


def _cases(text: str) -> List[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def sheet_rows(book: xlsx.Workbook, tab: str,
               header_row: int = 1) -> Dict[str, Any]:
    """One tab's unit rows, plus what the tab itself says about its shape.

    ``header_row`` because these tabs are not one shape: some carry a title line
    above the headings. Getting it wrong finds no columns and reports every unit
    as "not run", which reads as a catastrophic day rather than as a parse
    failure — so it is configured per tab rather than sniffed.
    """
    sheet = book.sheet(tab)
    if len(sheet.rows) < header_row:
        return {"rows": [], "columns": {}, "trailing": 0, "day": None,
                "error": "{!r} has fewer than {} rows".format(tab, header_row)}

    columns = _header_map(sheet.rows[header_row - 1])
    if "sn" not in columns:
        return {"rows": [], "columns": columns, "trailing": 0, "day": None,
                "error": "no DUT SN column on row {} of {!r} — set headerRow "
                         "in diff/delta.json if the headings are lower "
                         "down".format(header_row, tab)}

    def at(row: Sequence[xlsx.Cell], key: str) -> str:
        column = columns.get(key)
        if not column:
            return ""
        for cell in row:
            if cell.column == column:
                return (cell.value or "").strip()
        return ""

    rows: List[Dict[str, Any]] = []
    trailing = 0
    day = None
    for index, row in enumerate(sheet.rows):
        if index < header_row:
            continue
        serial = _serial(at(row, "sn"))
        if not serial:
            # The line pre-numbers rows it has not filled in yet. Counted, not
            # listed: "22 rows waiting" is a fact about the tab, and treating
            # them as units would invent 22 blank results.
            if any(cell.value for cell in row):
                trailing += 1
            continue
        entry = {"row": index + 1, "sn": serial,
                 "asic": at(row, "asic"), "pn": at(row, "pn"),
                 "note": at(row, "note"), "jira": at(row, "jira"),
                 "bonepile": at(row, "bonepile"),
                 "raw": at(row, "sn")}
        for key, _label in STATIONS:
            entry[key] = _verdict(at(row, key))
            entry[key + "Case"] = _cases(at(row, key + "Case"))
            entry[key + "Link"] = at(row, key + "Link")
        rows.append(entry)
        day = day or _row_day(row, columns)
    return {"rows": rows, "columns": columns, "trailing": trailing, "day": day}


def _row_day(row: Sequence[xlsx.Cell], columns: Dict[str, str]) -> Optional[str]:
    for cell in row:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", (cell.value or "").strip()):
            return cell.value.strip()
    return None


def tab_day(name: str, rows: Dict[str, Any], configured: Dict[str, Any]) -> Optional[str]:
    """Which day a tab is about — the configured answer, or a fallback.

    The configured day wins outright, and in practice it is always set. The
    fallbacks exist for a tab somebody adds without one, and they are ordered
    the way they are because of what went wrong when they were not: a Retest
    tab's Date column holds the date of the run being *retested*, so reading
    the day out of the rows filed "08-13 Retest" under 08-11. The tab name is
    the more reliable of the two, and the year comes from the sheet's own dates
    since the name has none.
    """
    if configured.get("day"):
        return configured["day"]
    found = TAB_DAY.match(name)
    if found:
        year = (rows.get("day") or "")[:4] or str(datetime.now(timezone.utc).year)
        return "{}-{}-{}".format(year, found.group(1), found.group(2))
    return rows.get("day")


# ------------------------------------------------------------------- the page

def published_rows(tab: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The dashboard's own row for each unit, in this module's vocabulary."""
    keys = [column["key"] for column in tab.get("columns") or []]
    by_title = {column["key"]: (column.get("title") or "").strip().lower()
                for column in tab.get("columns") or []}

    def key_for(*wanted: str) -> Optional[str]:
        for key, title in by_title.items():
            if title in wanted:
                return key
        return None

    field = {
        "sn": key_for("sn", "dut sn"),
        "pn": key_for("dut pn"),
        "mlt": key_for("mlt results"),
        "mltVer": key_for("mlt version"),
        "htt": key_for("htt results"),
        "httVer": key_for("htt version"),
        "jira": key_for("jira"),
    }
    # The two failure columns and the two link columns share their titles with
    # each other, so they are taken in order like the sheet's are.
    fails = [key for key in keys if by_title.get(key, "").endswith("failure test case")]
    links = [key for key in keys if by_title.get(key, "") == "fi test link"]
    field["mltCase"], field["httCase"] = (fails + [None, None])[:2]
    field["mltLink"], field["httLink"] = (links + [None, None])[:2]

    out: List[Dict[str, Any]] = []
    for row in tab.get("rows") or []:
        cells = {key: cell for key, cell in zip(keys, row)}

        def value(name: str) -> str:
            key = field.get(name)
            cell = cells.get(key) if key else None
            return str((cell or {}).get("v", "") or "").strip()

        serial = value("sn")
        if not serial:
            continue
        # Fresh material or a unit that has been here before. The tracker
        # already works this out — it has to, so its Count new mode can drop
        # returning units from a day's yield — and it records the answer on the
        # serial cell: ``new`` for a first visit, ``seen``/``history`` per stage
        # for one that is back. Recomputing it here from the run table would be
        # a second implementation of the same question, and the two would
        # disagree within a week.
        sn_cell = cells.get(field.get("sn")) or {}
        seen_at = sn_cell.get("seen") or {}
        history = sn_cell.get("history") or {}

        entry = {"sn": serial, "pn": value("pn"), "jira": value("jira")}
        for key, _label in STATIONS:
            entry[key + "Fresh"] = not seen_at.get(key)
            entry[key + "Seen"] = seen_at.get(key) or ""
            entry[key + "Attempts"] = len(history.get(key) or [])
            entry[key] = _verdict(value(key))
            entry[key + "Case"] = _cases(value(key + "Case"))
            entry[key + "Ver"] = value(key + "Ver")
            cell = cells.get(field.get(key + "Link")) if field.get(key + "Link") else None
            # ``h`` is what the tracker bundle calls a cell's link target. Named
            # for brevity in a bundle that carries thousands of them, and worth
            # spelling out here because reaching for "href" gets an empty string
            # and no error.
            entry[key + "Url"] = (cell or {}).get("h") or ""
        out.append(entry)
    return out


def published_bundle() -> Optional[Dict[str, Any]]:
    """The tracker bundle the page is actually serving, if one is built.

    Read rather than rebuilt, and not only to save the slowest step in the
    build. The question this page answers is "does the sheet agree with what the
    dashboard is showing" — so the right thing to compare against is the bundle
    on disk, not a fresh one that may already differ from it. A rebuild would
    quietly compare the sheet against a dashboard nobody has seen.

    ``make build`` hands its own bundle in directly, so this is the standalone
    path only.
    """
    path = config.DASHBOARD_DATA_DIR / "dailyexcel.js"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


# ---------------------------------------------------------------- classifying

def _classify_cases(local: List[str], online: List[str],
                    verdict: str) -> Optional[str]:
    """Why two failure lists differ, or None when they do not."""
    if local == online:
        return None
    left, right = set(local), set(online)
    if not left and right:
        return "case-missing" if verdict == "fail" else "case-extra"
    if left and not right:
        return "case-prose" if any(not CASE_NAME.match(n) for n in local) \
            else "case-conflict"
    if any(not CASE_NAME.match(name) for name in local):
        return "case-prose"
    if right and all(rootcause.is_container(name) for name in online):
        return "case-nest-only"
    if left < right:
        return "case-subset"
    if right < left:
        return "case-extra"
    if not (left & right):
        return "case-conflict"
    return "case-overlap"


def _fixture_level(url: str, names: Sequence[str]) -> Optional[List[str]]:
    """Which of ``names`` the controller recorded with no slot at all.

    The single most common real error in the sheet: a failure that belongs to
    the whole fixture written onto every unit in it. PcieSetupTestCase failing
    once for a tray of eight is not eight units failing PcieSetupTestCase, and
    the controller says so — it files that case under no slot.

    Cheap enough to ask: only conflict rows reach here, the run detail is the
    same one the tracker already fetched, and it is served from disk.
    """
    run = re.search(r"/suite_run/([^?/#]+)", url or "")
    if not run or not names:
        return None
    try:
        detail = pega.suite_run(run.group(1), host="pega3")
    except pega.PegaUnavailable:
        return None
    loose = {(case.get("test_name") or "").strip()
             for case in detail.get("test_cases") or []
             if str(case.get("status") or "").lower().startswith(("fail", "error"))
             and chips.chip_of(case.get("test_id") or "") is None}
    hits = [name for name in names if name in loose]
    return hits or None


def compare(local: List[Dict[str, Any]], online: List[Dict[str, Any]],
            adjudicate: bool = True) -> Dict[str, Any]:
    """Every unit on either side, with what the two say and why they differ."""
    by_local = {row["sn"]: row for row in local}
    by_online = {row["sn"]: row for row in online}

    units: List[Dict[str, Any]] = []
    for serial in sorted(set(by_local) | set(by_online)):
        mine, theirs = by_local.get(serial), by_online.get(serial)
        entry: Dict[str, Any] = {
            "sn": serial,
            "row": (mine or {}).get("row"),
            "where": "both" if mine and theirs else ("local" if mine else "online"),
            "deltas": [],
        }
        if not (mine and theirs):
            side = "local" if mine else "online"
            entry["deltas"].append({
                "field": "unit", "kind": "population", "side": side,
                "local": "present" if mine else "—",
                "online": "present" if theirs else "—",
                "station": None,
            })
            for key, _label in STATIONS:
                source = mine or theirs
                entry[key] = {"local": (mine or {}).get(key, ""),
                              "online": (theirs or {}).get(key, ""),
                              "localCase": (mine or {}).get(key + "Case") or [],
                              "onlineCase": (theirs or {}).get(key + "Case") or [],
                              "version": (theirs or {}).get(key + "Ver", ""),
                              "url": (source or {}).get(key + "Link")
                                     or (theirs or {}).get(key + "Url", ""),
                              "fresh": (theirs or {}).get(key + "Fresh", True),
                              "seen": (theirs or {}).get(key + "Seen", ""),
                              "attempts": (theirs or {}).get(key + "Attempts", 0)}
            units.append(entry)
            continue

        for key, label in STATIONS:
            local_v, online_v = mine[key], theirs[key]
            local_c, online_c = mine[key + "Case"], theirs[key + "Case"]
            entry[key] = {"local": local_v, "online": online_v,
                          "localCase": local_c, "onlineCase": online_c,
                          "version": theirs.get(key + "Ver", ""),
                          "url": mine.get(key + "Link") or theirs.get(key + "Url", ""),
                          # Only the controllers can answer this — the sheet has
                          # no column for it — so it comes from one side alone
                          # and is labelled as the dashboard's answer.
                          "fresh": theirs.get(key + "Fresh", True),
                          "seen": theirs.get(key + "Seen", ""),
                          "attempts": theirs.get(key + "Attempts", 0)}
            if local_v != online_v:
                entry["deltas"].append({
                    "field": label + " result", "kind": "status", "station": key,
                    "local": local_v or "blank", "online": online_v or "blank",
                    "side": None,
                })
            kind = _classify_cases(local_c, online_c, online_v)
            if kind:
                delta = {"field": label + " failure case", "kind": kind,
                         "station": key, "local": local_c, "online": online_c,
                         "side": None}
                if adjudicate and kind in ("case-conflict", "case-overlap"):
                    loose = _fixture_level(entry[key]["url"], local_c)
                    if loose:
                        delta["kind"] = "case-fixture"
                        delta["fixture"] = loose
                entry["deltas"].append(delta)
        units.append(entry)
    return {"units": units}


def _tally(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    counts = {"pass": 0, "fail": 0, "abort": 0, "blank": 0}
    for row in rows:
        counts[row.get(key) if row.get(key) in counts else "blank"] += 1
    graded = counts["pass"] + counts["fail"]
    counts["graded"] = graded
    counts["yield"] = round(100.0 * counts["pass"] / graded, 1) if graded else None
    return counts


# -------------------------------------------------------------------- bundle

def build_bundle(payload: Optional[Dict[str, Any]] = None,
                 path: Optional[str] = None,
                 adjudicate: bool = True) -> Dict[str, Any]:
    """The comparison, one entry per day the hand-kept workbook has a tab for."""
    book_path = workbook_path(path)
    book = xlsx.Workbook(book_path)
    note = settings()
    configured = note.get("tabs") or {}

    daily = payload or published_bundle() or build_dailyexcel.build_bundle()
    published = {tab.get("day"): tab for tab in daily.get("tabs") or []
                 if tab.get("day")}

    days: List[Dict[str, Any]] = []
    # Configured tabs only, never every tab whose name starts with a date.
    #
    # Walking the workbook was tried first and it produced confident wrong
    # numbers. These tabs are not one shape: some put their header on row 2, so
    # the columns went unfound and every unit came out "not run"; a Retest tab's
    # Date column carries the date of the run being retested, so "08-13 Retest"
    # was filed under 08-11. Both failures look exactly like a finding.
    #
    # So a comparison exists when somebody has said which day a tab is about and
    # where its header is. One line of config per tab, and the page can be
    # trusted on the tabs it does show.
    for name, setting in configured.items():
        if name not in book.sheet_names():
            days.append({"day": setting.get("day"), "tab": name,
                         "gid": setting.get("gid"), "units": [], "kinds": {},
                         "missing": "no tab named {!r} in {}".format(
                             name, book_path.name)})
            continue
        sheet = sheet_rows(book, name, header_row=setting.get("headerRow", 1))
        day = setting.get("day") or tab_day(name, sheet, setting)
        if sheet.get("error"):
            days.append({"day": day, "tab": name, "gid": setting.get("gid"),
                         "units": [], "kinds": {}, "missing": sheet["error"]})
            continue
        tab = published.get(day)
        if not day or not tab or not sheet["rows"]:
            days.append({
                "day": day, "tab": name, "gid": setting.get("gid"),
                "units": [], "kinds": {},
                "missing": ("the tab holds no unit rows" if not sheet["rows"]
                            else "the dashboard has no tab for {}".format(day)),
            })
            continue

        online = published_rows(tab)
        result = compare(sheet["rows"], online, adjudicate=adjudicate)
        reported = setting.get("reported") or {}
        days.append({
            "day": day,
            "tab": name,
            "gid": setting.get("gid"),
            "reported": reported,
            "reportedDelta": _reported_delta(reported, sheet["rows"]),
            "trailing": sheet["trailing"],
            "columns": sheet["columns"],
            "onlineTab": {"name": tab.get("name"), "label": tab.get("label"),
                          "derived": bool(tab.get("derived")),
                          "derivedFrom": tab.get("derivedFrom") or {}},
            "counts": {
                "local": {"rows": len(sheet["rows"]),
                          "mlt": _tally(sheet["rows"], "mlt"),
                          "htt": _tally(sheet["rows"], "htt")},
                "online": {"rows": len(online),
                           "mlt": _tally(online, "mlt"),
                           "htt": _tally(online, "htt")},
            },
            "units": result["units"],
            "kinds": _kind_counts(result["units"]),
            # A serial Excel stored as a float is fine at fifteen digits and
            # lossy at sixteen. Reported as a property of the tab rather than
            # left to be discovered from a mismatch that looks like something
            # else.
            "numericSerials": sum(1 for row in sheet["rows"]
                                  if "E" in (row.get("raw") or "").upper()),
        })

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "source": {
            "workbook": book_path.name,
            "modifiedAt": datetime.fromtimestamp(
                book_path.stat().st_mtime, timezone.utc).replace(
                    microsecond=0).isoformat(),
            "sheetUrl": note.get("sheetUrl") or build_dailyexcel.source_url(),
            "publishedWorkbook": (daily.get("source") or {}).get("workbook"),
            "publishedModifiedAt": (daily.get("source") or {}).get("modifiedAt"),
        },
        "days": days,
    }


def _reported_delta(reported: Dict[str, Any],
                    rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The posted figures against the tab they were read off.

    Where they still agree, the tab has not been touched since the cut and the
    number people acted on is the number the tab holds. Where they differ, the
    tab has moved — and by how much, per station, dates that edit better than a
    file timestamp does. Neither is corrected into the other.
    """
    if not reported:
        return {}
    out: Dict[str, Any] = {}
    for key, label in STATIONS:
        said = reported.get(key) or {}
        if not said:
            continue
        now = _tally(rows, key)
        out[key] = {
            "label": label,
            "reportedPass": said.get("pass"), "reportedFail": said.get("fail"),
            "sheetPass": now["pass"], "sheetFail": now["fail"],
            "passDelta": now["pass"] - (said.get("pass") or 0),
            "failDelta": now["fail"] - (said.get("fail") or 0),
            "agrees": (now["pass"] == said.get("pass")
                       and now["fail"] == said.get("fail")),
            # A version in the post that the tab and the Jira both contradict is
            # worth showing rather than quietly preferring one of them.
            "reportedVersion": said.get("version"),
        }
    return out


def _kind_counts(units: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for unit in units:
        for delta in unit["deltas"]:
            counts[delta["kind"]] = counts.get(delta["kind"], 0) + 1
    return counts


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "delta.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "// Generated by `python -m factory.cli delta` — do not edit.\n"
        "window.__FACTORY_DELTA__ = {};\n".format(
            json.dumps(bundle, separators=(",", ":"), default=str)),
        encoding="utf-8")
    return target
