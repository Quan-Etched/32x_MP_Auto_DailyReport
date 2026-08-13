"""Compile the line's daily MLT/HTT tracker tabs into a dashboard page.

WHAT THIS IS, AND WHY IT IS NOT AN ETL
--------------------------------------
Everything else in this repo derives from the EOS API. This does not: it reads a
Google Sheet the module line keeps by hand, exported to .xlsx and dropped in
``daily/``. The sheet is the line's own record of which units passed MLT and
HTT on a given day, which test case failed, and which Jira ticket tracks it —
judgements no API exposes, because a person made them.

So it is published as what it is: a faithful reproduction of the tab, not a
re-derivation. The numbers are the line's numbers. Where this page can add
something the spreadsheet cannot — a link from a DUT to the runs behind it —
it does, and where it cannot it says so rather than inventing a link.

WHICH TABS
----------
Tabs are discovered by name, not hard-coded: ``08-11 87x`` and ``08-12  51x``
both match ``MM-DD<space>Nx``, where N is the unit count the line wrote into the
tab name. Adding ``08-13 62x`` to the workbook publishes it with no code change,
which is the point — this file should not need editing every morning.

The year is not in the tab name. It comes from the Date column, so a tab whose
rows disagree with its own name is a warning rather than a guess.

THE CROSS-REFERENCE, AND WHY MOST ROWS DO NOT HAVE ONE
------------------------------------------------------
A DUT serial in this sheet is linked into ``runs.html`` only when that serial
actually appears in the collected run table. On the first build 32 of 138
serials did, and the gap is real rather than a bug here: for 2026-08-11 and -12
the sheet records 138 units while EOS returns 45 MLT/HTT runs per day. The
counts are published on the page. A link rendered for all 138 would be dead for
three quarters of them, and a reader would learn the wrong lesson from that —
that the drill-down is broken, rather than that EOS is not showing the line's
full volume.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config, links, xlsx

#: ``08-11 87x`` / ``08-12  51x`` — month-day, then the line's own unit count.
TAB_PATTERN = re.compile(r"^\s*(\d{1,2})-(\d{1,2})\s+(\d+)\s*x\s*$", re.IGNORECASE)

#: Fill colour -> the role it plays, so the page can render both themes instead
#: of pasting the sheet's light-mode hex into a dark one. Any fill not listed
#: here becomes a warning: a new colour in the tracker means the line started
#: marking something new, and that is worth noticing rather than flattening.
FILL_TONES: Dict[str, str] = {
    "FF1E3A5F": "header",
    "FFD1FAE5": "pass",
    "FFFEE2E2": "fail",
    "FFF9FAFB": "zebra",
    "FFFFFFFF": "plain",
}

#: Jira keys in the notes column, e.g. ``ETCH-38567: SohuLlamaForward…``.
JIRA_KEY = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

#: Column letters whose text is a status word the page colours by role.
RESULT_COLUMNS = ("E", "H")

#: The sheet's own link columns: short run id as text, pega3 URL as target.
LINK_COLUMNS = ("G", "J")

DEFAULT_DIR = config.REPO_ROOT / "daily"


def workbook_path(explicit: Optional[str] = None) -> Path:
    """The tracker export to publish.

    ``FACTORY_DAILY_XLSX`` wins; otherwise the most recently modified .xlsx in
    ``daily/``, so replacing the export is a drag-and-drop rather than an edit.
    """
    chosen = explicit or os.environ.get("FACTORY_DAILY_XLSX", "").strip()
    if chosen:
        path = Path(chosen).expanduser()
        if not path.exists():
            raise FileNotFoundError("FACTORY_DAILY_XLSX points at {}".format(path))
        return path

    candidates = sorted(
        DEFAULT_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        raise FileNotFoundError(
            "no .xlsx in {} — export the tracker there, or set "
            "FACTORY_DAILY_XLSX".format(DEFAULT_DIR)
        )
    return candidates[0]


def source_url() -> str:
    """The Google Sheet this was exported from, for the page's provenance line."""
    override = os.environ.get("FACTORY_DAILY_URL", "").strip()
    if override:
        return override
    # daily/dailyexcel.json records the URL. It is hand-written and has been
    # seen unquoted, so it is scraped rather than parsed — the URL is worth
    # more than insisting on well-formed JSON for a one-line note file.
    note = DEFAULT_DIR / "dailyexcel.json"
    if note.exists():
        match = re.search(r"https?://\S+?(?=[\s\"',}]|$)", note.read_text(
            encoding="utf-8", errors="replace"))
        if match:
            return match.group(0)
    return ""


# --------------------------------------------------------------------- build

def build_bundle(
    payload: Optional[Dict[str, Any]] = None, path: Optional[Path] = None
) -> Dict[str, Any]:
    source = workbook_path(str(path) if path else None)
    book = xlsx.Workbook(source)

    known_duts = _known_duts(payload or {})
    warnings: List[str] = []
    tabs = []
    for name in book.sheet_names():
        match = TAB_PATTERN.match(name)
        if not match:
            continue
        tabs.append(_tab(book, name, match, known_duts, warnings))

    if not tabs:
        warnings.append(
            "no tab in {} is named like 'MM-DD Nx' — nothing to publish".format(
                source.name))

    tabs.sort(key=lambda tab: tab["day"] or "")
    matched = sum(tab["crossref"]["matched"] for tab in tabs)
    total = sum(tab["crossref"]["duts"] for tab in tabs)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "workbook": source.name,
            "modifiedAt": datetime.fromtimestamp(
                source.stat().st_mtime, timezone.utc
            ).replace(microsecond=0).isoformat(),
            "url": source_url(),
            "tabsInWorkbook": len(book.sheet_names()),
        },
        "tabs": tabs,
        "crossref": {
            "matched": matched,
            "duts": total,
            "runsCollectedAt": (payload or {}).get("generatedAt"),
        },
        "links": {
            "jiraBase": links.jira_base() or None,
            "ocp": links.describe(),
        },
        "warnings": warnings,
    }


def _tab(book, name, match, known_duts, warnings) -> Dict[str, Any]:
    sheet = book.sheet(name)
    rows = _trim(sheet.rows)
    if not rows:
        warnings.append("tab {!r} is empty".format(name))
        return {
            "name": name, "label": name.strip(), "day": None, "claimedUnits": None,
            "columns": [], "rows": [], "counts": {}, "crossref": {"matched": 0, "duts": 0},
        }

    # The table is as wide as its last *titled* column. The header row is
    # styled well past that (26 cells against 11 headings here), and those
    # empties would otherwise become 15 blank columns on the page.
    titled = [index for index, cell in enumerate(rows[0]) if cell.value.strip()]
    width = (titled[-1] + 1) if titled else 0
    header = [_header(cell, sheet.widths) for cell in rows[0][:width]]
    body = []
    duts = set()
    matched = set()
    days = {}

    for cells in rows[1:]:
        # The header decides the table's width. Sheets carry styled-but-empty
        # cells well past their last real column — 26 here against 11 headings —
        # and shipping those would be pure bundle weight.
        record, dut, day = _row(cells[: len(header)], known_duts)
        record += [{}] * (len(header) - len(record))
        if not any(cell.get("v") for cell in record):
            continue
        body.append(record)
        if dut:
            duts.add(dut)
            if dut in known_duts:
                matched.add(dut)
        if day:
            days[day] = days.get(day, 0) + 1

    for cells in rows[1:]:
        for cell in cells:
            if cell.fill and cell.fill not in FILL_TONES:
                note = "tab {!r}: unmapped fill {} at {}".format(
                    name, cell.fill, cell.ref)
                if note not in warnings:
                    warnings.append(note)

    day = max(days, key=lambda key: days[key]) if days else None
    claimed = int(match.group(3))
    month, dom = match.group(1), match.group(2)
    if day and not day.endswith("-%02d-%02d" % (int(month), int(dom))):
        warnings.append(
            "tab {!r} is named {}-{} but its rows are mostly {}".format(
                name, month, dom, day))

    return {
        "name": name,
        "label": "%02d-%02d" % (int(month), int(dom)),
        "day": day,
        "claimedUnits": claimed,
        "columns": header,
        "rows": body,
        "counts": _counts(body, header),
        "crossref": {"matched": len(matched), "duts": len(duts)},
    }


def _row(cells, known_duts) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    record = []
    dut = None
    day = None
    for cell in cells:
        entry: Dict[str, Any] = {}
        if cell.value:
            entry["v"] = cell.value
        if cell.href:
            entry["h"] = cell.href
        tone = FILL_TONES.get(cell.fill or "", "")
        if tone in ("pass", "fail"):
            entry["t"] = tone
        if cell.column == "A" and cell.value:
            day = cell.value.strip()[:10]
        if cell.column == "B" and cell.value:
            dut = cell.value.strip()
            # Only where the run table can actually answer. See the module
            # docstring: a link for every serial would be dead for most of them.
            if dut in known_duts:
                entry["d"] = dut
        if cell.column == "K" and cell.value:
            keys = JIRA_KEY.findall(cell.value)
            if keys:
                entry["j"] = keys
        record.append(entry)
    return record, dut, day


def _header(cell, widths) -> Dict[str, Any]:
    return {
        "key": cell.column,
        "title": cell.value,
        "width": widths.get(cell.column),
    }


def _counts(rows: List[List[Dict[str, Any]]], header: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pass/fail per result column, by the sheet's own colouring."""
    index = {entry["key"]: position for position, entry in enumerate(header)}
    counts = {}
    for column in RESULT_COLUMNS:
        position = index.get(column)
        if position is None:
            continue
        tally = {"pass": 0, "fail": 0, "blank": 0}
        for row in rows:
            cell = row[position] if position < len(row) else {}
            tone = cell.get("t")
            if tone in tally:
                tally[tone] += 1
            else:
                tally["blank"] += 1
        counts[column] = dict(tally, title=header[position]["title"])
    return counts


def _trim(rows) -> List[List[Any]]:
    """Drop the trailing empty rows a sheet declares but does not use."""
    last = -1
    for index, cells in enumerate(rows):
        if any((cell.value or cell.href) for cell in cells):
            last = index
    return rows[: last + 1]


def _known_duts(payload: Dict[str, Any]) -> set:
    return {
        (run.get("dutSerial") or "").strip()
        for run in payload.get("runs", [])
        if run.get("dutSerial")
    }


# --------------------------------------------------------------------- write

def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "dailyexcel.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli dailyexcel` — do not edit.\n"
        "window.__FACTORY_DAILY_EXCEL__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target
