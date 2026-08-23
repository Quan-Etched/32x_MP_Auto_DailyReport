"""Failures as error codes, for the customize page's error table.

WHAT THIS JOINS
Two things nobody had put next to each other:

  * The line's daily tracker already records, per unit per station, the name of
    the test case that failed and a link to the run. Its own column headings
    say so: "MLT Failure Test Case", then "FI Test Link". FI is the line's
    abbreviation and this module keeps it.
  * The error-code catalogue (`errors/catalogue.json`, derived from the sheet
    Ulysses Kao maintains) maps those test-case names to error codes, with the
    message, component, quick action and known bugs for each.

So a failure that used to read `CheckHsmTokenTestCase` now reads
`TH-SEC-0002-...  CheckHsmTokenTestCase  ESCALATE`, and the code is the thing
you can look up, argue about, and count.

WHAT IT DOES NOT DO
It does not guess. A test case in the catalogue often carries more than one
code — 125 of 177 do, because the code distinguishes *which way* the case
failed and the tracker records only that it did. Every candidate code is
listed and the row says how many; picking one would be inventing a diagnosis.
Cases the catalogue has never heard of are kept, marked, and counted, because a
failure mode nobody has catalogued is the more interesting finding.

THE ANNOTATIONS
Root cause, corrective action and note are people's work, not derived: they
live in `errors/annotations.json`, keyed by day|station|unit|case, and are
merged in here. Nothing in this module writes that file — the customize page's
admin mode does, through tools/annotate_server.py.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import config, stations, version

#: Derived from the sheet, committed so the build never reaches the network.
#: Refresh with tools/refresh_error_catalogue.py when the sheet moves on.
CATALOGUE = config.REPO_ROOT / "errors" / "catalogue.json"

#: People's annotations. Written by the admin flow, read here.
ANNOTATIONS = config.REPO_ROOT / "errors" / "annotations.json"

#: Root causes already established for a whole test case, rather than for one
#: failure of it. Hand-edited and committed; a per-row annotation still wins.
ESTABLISHED = config.REPO_ROOT / "errors" / "established.json"

#: A root cause is one of two answers, and the table is more use for it. Either
#: the test setup caused the failure or the DUT is genuinely bad — that is the
#: decision the line acts on, and a free-text box produced twelve spellings of
#: each. Prose goes in the note.
CAUSES = {"setup": "Test setup", "dut": "True DUT failure"}

#: The tracker bundle this reads. Same file the daily page loads, so the two
#: cannot disagree about what failed.
DAILY_BUNDLE = config.DASHBOARD_DATA_DIR / "dailyexcel.js"

OUT = config.DASHBOARD_DATA_DIR / "errors.js"

#: A tracker column holding the failing case, and the link column that follows
#: it. Both spellings appear across the MLT/HTT, L10 and L11 blocks.
FAILURE_TITLE = re.compile(r"Failure Test Case\s*$", re.I)
LINK_TITLE = re.compile(r"^FI Test Link\s*$", re.I)


class NoBundle(Exception):
    """The daily tracker has not been built yet."""


def _read_js_bundle(path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))


def catalogue() -> Dict[str, Any]:
    if not CATALOGUE.exists():
        return {"codes": [], "source": "", "readOn": ""}
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


def by_case(cat: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """test case name -> every code that names it."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for entry in cat.get("codes") or []:
        for case in entry.get("cases") or []:
            out.setdefault(case, []).append(entry)
    return out


def established() -> Dict[str, Dict[str, str]]:
    """test case -> the root cause we already know for it."""
    if not ESTABLISHED.exists():
        return {}
    try:
        got = json.loads(ESTABLISHED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {case: known for case, known in (got.get("cases") or {}).items()
            if (known or {}).get("rootCause") in CAUSES}


def annotations() -> Dict[str, Dict[str, str]]:
    if not ANNOTATIONS.exists():
        return {}
    try:
        got = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got.get("entries") or {}


def _cases(cell: Dict[str, Any]) -> List[str]:
    """The tracker puts two failing cases in one cell, separated by a newline."""
    raw = (cell or {}).get("v")
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[\n;,]+", str(raw))
            if part.strip()]


def _pairs(columns: List[Dict[str, Any]]) -> List[Tuple[int, int, Optional[str]]]:
    """(failure column, link column, station key) for each station in a block.

    The station comes from the nearest Results column above the failure column,
    which is the only place the tracker records it. Derived rather than listed:
    a hard-coded map of column letters to stations would be wrong the first
    time somebody inserts a column, and this bundle is rebuilt hourly.
    """
    out = []
    for index, column in enumerate(columns):
        if not FAILURE_TITLE.search(column.get("title") or ""):
            continue
        link = None
        if index + 1 < len(columns) and LINK_TITLE.match(
                columns[index + 1].get("title") or ""):
            link = index + 1
        station = None
        for back in range(index - 1, -1, -1):
            if columns[back].get("station"):
                station = columns[back]["station"]
                break
        out.append((index, link, station))
    return out


def _block_rows(block: Dict[str, Any], day: str) -> List[Dict[str, Any]]:
    columns = block.get("columns") or []
    keys = [column.get("key") for column in columns]
    if "B" not in keys:
        return []
    sn_at = keys.index("B")
    found = []
    for row in block.get("rows") or []:
        dut = (row[sn_at] or {}).get("v") if sn_at < len(row) else None
        if not dut:
            continue
        for fail_at, link_at, station in _pairs(columns):
            if fail_at >= len(row):
                continue
            for case in _cases(row[fail_at]):
                link_cell = row[link_at] if (
                    link_at is not None and link_at < len(row)) else {}
                found.append({
                    "day": day,
                    "dut": str(dut),
                    "station": station or "",
                    "case": case,
                    "fi": (link_cell or {}).get("h") or "",
                    "run": (link_cell or {}).get("v") or "",
                })
    return found


def collect(bundle: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every failing (unit, station, case) the tracker records, newest first."""
    if bundle is None:
        if not DAILY_BUNDLE.exists():
            raise NoBundle("{} is missing — run `make dailyexcel`".format(
                DAILY_BUNDLE))
        bundle = _read_js_bundle(DAILY_BUNDLE)
    rows: List[Dict[str, Any]] = []
    for tab in bundle.get("tabs") or []:
        day = tab.get("day") or ""
        if not day:
            continue
        rows.extend(_block_rows(tab, day))
        for extra in ("l10", "l11"):
            block = tab.get(extra)
            if block:
                rows.extend(_block_rows(block, block.get("day") or day))
    rows.sort(key=lambda row: (row["day"], row["station"], row["dut"],
                              row["case"]), reverse=True)
    return rows


def entry_key(row: Dict[str, Any]) -> str:
    """The annotation key. Readable on purpose: it is a filename's worth of
    identity and somebody will read it in a diff."""
    return "|".join([row["day"], row["station"], row["dut"], row["case"]])


def build_bundle(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    cat = catalogue()
    index = by_case(cat)
    notes = annotations()
    known = established()
    labels = {key: station.label for key, station in stations.BY_KEY.items()}
    if rows is None:
        rows = collect()

    out = []
    unknown: Dict[str, int] = {}
    used: set = set()
    for row in rows:
        codes = index.get(row["case"]) or []
        note = notes.get(entry_key(row)) or {}
        if not codes:
            unknown[row["case"]] = unknown.get(row["case"], 0) + 1
        used.update(c["code"] for c in codes)
        # Established first, then the row's own annotation on top: a case with
        # a known usual cause can still fail for a different reason on one
        # unit, and the person who looked at that unit outranks the table.
        settled = known.get(row["case"]) or {}
        annotated = {}
        if settled.get("rootCause") not in CAUSES:
            # Checked here as well as in established(): the page renders
            # CAUSES[value] and would print the raw string, and this is the
            # layer every source of a cause passes through.
            settled = {}
        if settled:
            annotated["rootCause"] = settled["rootCause"]
            annotated["established"] = True
            if settled.get("correctiveAction"):
                annotated["correctiveAction"] = settled["correctiveAction"]
            if settled.get("why"):
                annotated["note"] = settled["why"]
            if settled.get("ref"):
                annotated["ref"] = settled["ref"]
        for key in ("rootCause", "correctiveAction", "note", "by", "at"):
            if not note.get(key):
                continue
            if key == "rootCause" and note[key] not in CAUSES:
                continue
            annotated[key] = note[key]
        out.append({
            "day": row["day"],
            "dut": row["dut"],
            "station": row["station"],
            "case": row["case"],
            # The whole FI URL is one long string repeated per row and every
            # one has the same shape. The suite run and slot are the only
            # varying parts; the page rebuilds the address from `fiBase`.
            "fi": row["fi"],
            "run": row["run"],
            # Every candidate, and nothing else: the code's message, action,
            # component and bugs are the same text for every row that hits it,
            # and repeating them per row put 600 KB on a page that already
            # loads a big bundle. They go in `codes` below, once each, and the
            # page looks them up.
            "codes": [c["code"] for c in codes],
        })
        # Only when there is one. An empty annotation on every row was five
        # dead keys per row, and "no root cause recorded" is the default the
        # page renders anyway.
        if annotated:
            out[-1].update(annotated)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "build": version.describe(),
        "catalogue": {
            "source": cat.get("source", ""),
            "readOn": cat.get("readOn", ""),
            "codes": len(cat.get("codes") or []),
            "cases": len(index),
        },
        # Named, not hidden: a failing case the catalogue has never heard of is
        # the finding, and a table that quietly dropped those rows would report
        # the line as fully catalogued.
        # The codes these rows point at, once each. Only the ones actually
        # used — the full 313 would be mostly dead weight on the page.
        "codes": {code["code"]: {
            "message": code["message"],
            "action": code["action"],
            "component": code["component"],
            "type": code["type"],
            "source": code["source"],
            "bugs": code["bugs"],
        } for code in (cat.get("codes") or [])
            if code["code"] in used},
        # The two answers, so the page and the CSV spell them the same way as
        # this module and as the service that writes them.
        "causes": CAUSES,
        "stationLabels": {key: labels.get(key, key.upper())
                          for key in sorted({row["station"]
                                             for row in rows})},
        "uncatalogued": sorted(
            ({"case": case, "rows": n} for case, n in unknown.items()),
            key=lambda item: (-item["rows"], item["case"])),
        "rows": out,
    }


def write_bundle(bundle: Dict[str, Any], path=None):
    target = path or OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "// Generated by `python -m factory.cli errors` — do not edit.\n"
        "window.__FACTORY_ERRORS__ = "
        + json.dumps(bundle, separators=(",", ":"), sort_keys=True)
        + ";\n", encoding="utf-8")
    return target
