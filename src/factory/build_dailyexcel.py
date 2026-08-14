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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import chips, config, links, pega, rootcause, stations, version, xlsx

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

#: Days EOS has module MLT/HTT data for, but the workbook does not, are rebuilt
#: from the API so the page keeps going when nobody has exported the sheet yet.
#: Capped: the point is "today and the day before", not a parallel history that
#: quietly competes with the line's own record.
DERIVE_LIMIT = 3

#: The stations the tracker covers, and the column pair each one fills.
DERIVED_STATIONS = (("mlt", "E", "F", "G"), ("htt", "H", "I", "J"))

#: Validation and debug suites are engineering, not production. Same policy as
#: the ``_krish`` exclusions in stations.py, applied to pega3's wider day.
ENGINEERING = re.compile(r"_(validation|debug)\b", re.IGNORECASE)


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
    payload: Optional[Dict[str, Any]] = None, path: Optional[Path] = None,
    derive: bool = True, enrich: bool = True,
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
        tab = _tab(book, name, match, known_duts, warnings)
        # The sheet is the line's record, but its failure column is knowingly
        # lossy — one name where a unit failed eight tests. Fill it from pega3,
        # which is the system the line was reading when it typed the one.
        if enrich:
            tab = _enrich_from_pega(tab)
        tabs.append(tab)

    if not tabs:
        warnings.append(
            "no tab in {} is named like 'MM-DD Nx' — nothing to publish".format(
                source.name))

    # Days EOS knows about that the workbook has not caught up with. Derived
    # tabs are marked as such and never overwrite a real one — the line's own
    # record wins wherever it exists.
    if derive:
        have = {tab["day"] for tab in tabs if tab["day"]}
        # Only days *after* the newest real tab. A day the sheet skipped is the
        # line's decision, not a gap to fill; a day it has not reached yet is.
        newest = max(have) if have else ""
        candidates = sorted({_utc_day(run.get("startTs")) for run in (payload or {}).get("runs", [])
                             if run.get("level") == "module"
                             and run.get("stationKey") in ("mlt", "htt")} - {None} - have)
        candidates = [day for day in candidates if day > newest]
        for day in candidates[-DERIVE_LIMIT:]:
            newest_real = next((tab for tab in reversed(tabs)
                                if not tab.get("derived")), None)
            built = (_pega_tab(day, newest_real)
                     if pega.enabled() else None)
            if built is None:
                # pega3 unreachable: fall back to what EOS alone can say, which
                # is per-chip verdicts without the serials.
                built = derived_tab(payload or {}, day, template=newest_real)
            if built:
                tabs.append(built)

    tabs.sort(key=lambda tab: tab["day"] or "")
    matched = sum(tab["crossref"]["matched"] for tab in tabs)
    total = sum(tab["crossref"]["duts"] for tab in tabs)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        # Which build of this repo produced the page. Published copies are
        # rsynced by hand, so "what is on the site" drifts from "what is on
        # main" silently unless the page says.
        "build": version.describe(),
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


def derived_tab(payload: Dict[str, Any], day: str,
                template: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Rebuild a day's tracker tab from EOS, one row per chip.

    WHY ONE ROW PER CHIP, AND WHY THE SERIALS ARE MISSING
    A fixture run tests eight chips and EOS records it as one run carrying one
    ``dutSerial`` — and does not say which slot that serial sat in. The other
    seven serials exist only in pega3 and in the line's own sheet. Neither
    ``bom_config`` (every ``serial_number: null``) nor ``suite_config`` carries
    them; ``resource_config`` is never fetched, because it holds credentials.

    So the unit column says ``chip 3``. The run's serial is not dropped — it
    rides on the test link, which is also what makes the row clickable into the
    run table. Guessing which chip it belonged to would put a real serial next
    to the wrong verdict, which is worse than admitting the gap.

    MLT and HTT are separate fixture runs, so a derived row fills one station's
    columns and leaves the other blank — the same convention the sheet already
    uses for a unit that failed MLT and never reached HTT.
    """
    runs = [
        run for run in payload.get("runs", [])
        if run.get("level") == "module"
        and run.get("stationKey") in ("mlt", "htt")
        and _utc_day(run.get("startTs")) == day
    ]
    if not runs:
        return None

    versions = {}
    for station, _, _, _ in DERIVED_STATIONS:
        seen = [r.get("version") for r in runs if r.get("stationKey") == station]
        versions[station] = _release_label(seen)

    # The newest real tab is the format. Titles and widths are copied from it
    # verbatim and only the version token is swapped, so a derived tab is
    # indistinguishable from the line's own beside it — and stays that way if
    # the line renames a heading, instead of drifting until someone notices.
    columns = _derived_columns(template, versions)
    index = {column["key"]: position for position, column in enumerate(columns)}

    rows: List[List[Dict[str, Any]]] = []
    for station, result_col, fail_col, link_col in DERIVED_STATIONS:
        for run in sorted((r for r in runs if r.get("stationKey") == station),
                          key=lambda r: r.get("startTs") or 0):
            graded = chips.grade(run)
            for chip_index, entry in graded["chips"].items():
                row = [{} for _ in columns]
                row[index["A"]] = {"v": day}
                row[index["B"]] = {"v": "chip {}".format(chip_index)}
                status = entry["status"]
                # The sheet leaves a result cell blank when that stage did not
                # run on that unit; a chip whose tests were all skipped is the
                # same statement, so it is written the same way.
                if status in ("pass", "fail"):
                    row[index[result_col]] = {
                        "v": "Passed" if status == "pass" else "Failed",
                        "t": status,
                    }
                # Every failure on the chip, one per line — the same thing the
                # pega3 path says. This is the fallback for a host that cannot
                # reach the controller, and a fallback that quietly answers a
                # different question is worse than an obvious gap.
                failures = entry.get("failures") or (
                    [entry["firstFail"]] if entry["firstFail"] else [])
                if failures:
                    row[index[fail_col]] = {"v": "\n".join(failures)}
                row[index[link_col]] = _derived_link(run, day)
                rows.append(row)

    header_counts = _counts(rows, columns)
    return {
        "name": "{} (derived)".format(day),
        "label": day[5:],
        "day": day,
        "claimedUnits": None,
        "derived": True,
        "derivedFrom": {
            "runs": len(runs),
            "source": "eos",
            "versions": versions,
            "note": "Rebuilt from EOS. One row per chip; DUT serials live in "
                    "pega3 and the line's sheet, not in the API.",
        },
        "columns": columns,
        "rows": rows,
        "counts": header_counts,
        "crossref": {"matched": 0, "duts": 0},
    }


#: Fallback when the workbook has no real tab to copy — the widths observed on
#: the line's own tabs, so the shape is right even with nothing to imitate.
FALLBACK_WIDTHS = {"B": 18.13, "C": 4.38, "E": 25.25, "F": 34.0,
                   "H": 10.63, "I": 32.0, "J": 8.88, "K": 48.38}

FALLBACK_TITLES = ("Date", "DUT SN", "ASIC SN", "DUT PN",
                   "MLT Results mlt_", "MLT Failure Test Case mlt_",
                   "FI Test Link", "HTT Results htt_",
                   "HTT Failure Test Case htt_", "FI Test Link", "Jira")

#: ``mlt_2026.220`` / ``htt_2026.217`` inside a column heading.
#: The trailing digits are optional so the fallback headings — which carry a
#: bare ``mlt_`` with no version to copy — are substituted too.
VERSION_TOKEN = re.compile(r"(mlt|htt)_[0-9.]*", re.IGNORECASE)


def _derived_columns(template: Optional[Dict[str, Any]],
                     versions: Dict[str, str]) -> List[Dict[str, Any]]:
    """The real tab's columns, with each heading's version token swapped."""
    source = (template or {}).get("columns") or [
        {"key": xlsx.column_letters(i), "title": title,
         "width": FALLBACK_WIDTHS.get(xlsx.column_letters(i))}
        for i, title in enumerate(FALLBACK_TITLES)
    ]

    columns = []
    for column in source:
        title = column.get("title") or ""
        # Swap in the version this day actually ran, keeping the prefix the
        # line writes (mlt_2026.220, not 2026.220).
        def swap(match):
            release = versions.get(match.group(1).lower())
            return "{}_{}".format(match.group(1), release) if release else ""
        columns.append({
            "key": column.get("key"),
            "title": VERSION_TOKEN.sub(swap, title).strip(),
            "width": column.get("width"),
        })
    return columns


def _enrich_from_pega(tab: Dict[str, Any]) -> Dict[str, Any]:
    """Fill the sheet's failure columns with every failure pega3 recorded.

    The sheet's own columns are kept wherever they carry something pega3 cannot:
    the Jira keys, the line's verdicts, its links, its DUT list. Only the two
    failure-case columns are replaced, and only for a unit pega3 actually has.

    WHY THIS IS NOT VANDALISM OF A FAITHFUL COPY
    The failure column is the one place the sheet is knowingly lossy. A person
    types one name where the unit failed eight tests; on 08-11 and 08-12 that
    dropped 61 failures between them. Every verdict and every test link in those
    tabs was verified identical to pega3 first, so replacing the column is
    filling in the same day from the system the line was reading, not overruling
    the line's judgement about it.

    Where the two disagree the sheet's name is kept alongside, because a name a
    person wrote down deliberately is evidence even when it is not in pega3's
    list — on 08-11 exactly one row is like that, and it turned out to be a
    neighbouring slot's failure written on the wrong row.
    """
    day = tab.get("day")
    if not day:
        return tab
    gathered = _pega_units(day)
    if not gathered:
        return tab
    units = gathered[0]

    index = {column["key"]: position for position, column in enumerate(tab["columns"])}
    if not all(key in index for key in ("B", "F", "I")):
        return tab

    filled = 0
    added = 0
    for row in tab["rows"]:
        dut = (row[index["B"]].get("v") or "").strip()
        unit = units.get(dut)
        if not unit:
            continue
        for station, _result, fail_col, _link in DERIVED_STATIONS:
            got = (unit.get(station) or {}).get("fail") or ""
            if not got:
                continue
            cell = row[index[fail_col]]
            was = (cell.get("v") or "").strip()
            names = [n for n in got.split("\n") if n]
            # A name only the sheet has is kept: it was typed on purpose.
            for name in (n.strip() for n in was.split("\n") if n.strip()):
                if name not in names:
                    names.append(name)
            if names and "\n".join(names) != was:
                cell["v"] = "\n".join(names)
                filled += 1
                added += max(0, len(names) - len([n for n in was.split("\n") if n.strip()]))
    if filled:
        tab["enriched"] = {"rows": filled, "added": added, "source": "pega3"}
    return tab


def _pega_units(day: str) -> Optional[Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]], int]]:
    """Every unit pega3 tested that day, keyed by DUT serial.

    Shared by the two callers that need it: rebuilding a day the workbook has
    not reached, and filling the complete failure list into a day it has.

    FACTORY_PEGA=0 stops here rather than at the call sites, so switching the
    integration off really means no pega3 — a test that sets it and still
    reaches the factory network passes or fails on where it is run.
    """
    if not pega.enabled():
        return None
    try:
        listing = pega.day_suite_runs(day)
    except pega.PegaUnavailable:
        return None

    units: Dict[str, Dict[str, Any]] = {}
    versions: Dict[str, List[str]] = {"mlt": [], "htt": []}
    runs_seen = 0

    for entry in listing:
        run_id = entry.get("suite_run_id") or ""
        suite = entry.get("suite_name") or ""
        station = "mlt" if run_id.startswith("mlt") else "htt" if run_id.startswith("htt") else None
        if not station:
            continue
        # Engineering runs, excluded for the same reason stations.py drops the
        # _krish debug suites: they are not line units and would distort the
        # day's yield. pega3's day includes them; the line's tracker does not.
        if ENGINEERING.search(run_id) or ENGINEERING.search(suite):
            continue
        try:
            detail = pega.suite_run(run_id)
        except pega.PegaUnavailable:
            continue
        runs_seen += 1
        versions[station].append(entry.get("suite_name") or "")
        started = entry.get("start_time") or ""
        for part in pega.participants(detail):
            unit = units.setdefault(part["dut"], {
                "pn": entry.get("dut_part_number") or "",
                "asic": entry.get("asic_lot_code") or "",
            })
            # A unit retested the same day gets one row, not one per attempt —
            # the sheet has one row per unit. The row is the *latest* attempt:
            # keeping whichever run happened to be processed last made the
            # verdict depend on the order pega3 returned its listing, and
            # disagreed with the line on 9 of 87 units.
            previous = unit.get(station)
            if previous and previous["started"] >= started:
                continue
            unit[station] = {
                "status": part["status"],
                "fail": _unit_failures(detail, part["slot"]) if part["status"] == "fail" else "",
                "url": pega.run_url(run_id, part["slot"]),
                "short": run_id.rsplit("_run_", 1)[-1],
                "started": started,
            }

    if not units:
        return None
    return units, versions, runs_seen


def _pega_tab(day: str, template: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A day's tracker rebuilt from pega3 — the sheet's own source.

    pega3 assigns the slots, so it knows all eight DUT serials, the part number,
    every failing test case and the very link the sheet pastes into its FI Test
    Link column. Rows come out per unit with MLT and HTT merged, which is the
    shape the line's tabs have.
    """
    gathered = _pega_units(day)
    if not gathered:
        return None
    units, versions, runs_seen = gathered

    labels = {station: _release_label(list(seen)) for station, seen in versions.items()}
    columns = _derived_columns(template, labels)
    index = {column["key"]: position for position, column in enumerate(columns)}

    def sort_key(item):
        dut, unit = item
        # Passes first, failures last — the order the line's own tabs read in.
        bad = any((unit.get(s) or {}).get("status") == "fail" for s in ("mlt", "htt"))
        return (bad, dut)

    rows = []
    for dut, unit in sorted(units.items(), key=sort_key):
        row = [{} for _ in columns]
        row[index["A"]] = {"v": day}
        row[index["B"]] = {"v": dut}
        if unit.get("asic"):
            row[index["C"]] = {"v": unit["asic"]}
        if unit.get("pn"):
            row[index["D"]] = {"v": unit["pn"]}
        for station, result_col, fail_col, link_col in DERIVED_STATIONS:
            got = unit.get(station)
            if not got:
                continue
            if got["status"] in ("pass", "fail"):
                row[index[result_col]] = {
                    "v": "Passed" if got["status"] == "pass" else "Failed",
                    "t": got["status"],
                }
            if got["fail"]:
                row[index[fail_col]] = {"v": got["fail"]}
            row[index[link_col]] = {"v": got["short"], "h": got["url"]}
        rows.append(row)

    return {
        "name": "{} (from pega3)".format(day),
        "label": day[5:],
        "day": day,
        "claimedUnits": None,
        "derived": True,
        "derivedFrom": {
            "runs": runs_seen,
            "source": "pega3",
            "versions": labels,
            "note": "Rebuilt from pega3, which assigns the slots and therefore "
                    "knows every unit's serial.",
        },
        "columns": columns,
        "rows": rows,
        "counts": _counts(rows, columns),
        "crossref": {"matched": 0, "duts": len(units)},
    }


def _unit_failures(detail: Dict[str, Any], slot: Optional[int]) -> str:
    """Every test case that failed on one slot, oldest first, one per line.

    NOT the run's first failure. pega3's run-level ``first_failed_test_case``
    names the first failure anywhere in the fixture, which is usually a nest or
    another chip's problem; attributing it to a unit names someone else's fault.

    NOT just this slot's first failure either. A unit that fails eight tests has
    eight things wrong with it, and the one that happened to run first is rarely
    the interesting one — on DUT 268494130000069 (run 384ac187, slot 5) the first
    is BootloaderResultTestCase while the list also holds SohuVrmTestCase,
    SohuI2cTestCase and six more. The tracker sheet already writes several names
    into a cell on its own rows, so the shape is the line's, not an invention.

    Nest rows are left out: ``chip5`` (SltModuleNestedTestCase) and
    ``server_setup`` (ServerNestedTestCase) fail *because* a leaf under them did,
    and ServerNestedTestCase would appear twice in the same cell — once for
    server_setup and once for vbb_dependent_tests — which reads as a bug. Set
    ``FACTORY_DAILY_CONTAINERS=1`` for the literal list pega3's UI shows.

    A unit whose only failures are nests still gets a name rather than a blank
    cell: no leaf failed, but something did, and an empty cell beside "Failed"
    is the one thing this column must never say.
    """
    if slot is None:
        return ""
    keep_containers = os.environ.get("FACTORY_DAILY_CONTAINERS", "").strip() in ("1", "true", "yes")

    leaves: List[str] = []
    nests: List[str] = []
    for case in sorted(detail.get("test_cases") or [],
                       key=lambda c: c.get("start_time") or ""):
        status = str(case.get("status") or "").lower()
        if not status.startswith(("fail", "error")):
            continue
        if chips.chip_of(case.get("test_id") or "") != slot:
            continue
        name = (case.get("test_name") or "").strip()
        if not name:
            continue
        target = nests if rootcause.is_container(name) else leaves
        if name not in target:
            target.append(name)

    if keep_containers:
        names = leaves + [n for n in nests if n not in leaves]
    else:
        names = leaves or nests
    return "\n".join(names)


def _derived_link(run: Dict[str, Any], day: str) -> Dict[str, Any]:
    """The run's own identity, pointing at the rows behind it.

    Text is the timestamp tail of the runId — what OCP Logs shows in its RUN ID
    column — and the link goes to the drill-down filtered to the serial EOS did
    record, which is the one identifier that survives the trip.
    """
    run_id = run.get("runId") or ""
    dut = (run.get("dutSerial") or "").strip()
    tail = run_id.rsplit("_", 2)[-2:] if "_" in run_id else [run_id]
    cell: Dict[str, Any] = {"v": "_".join(tail) if tail else run_id}
    if dut:
        cell["d"] = dut
        cell["title"] = "EOS run {} · recorded DUT {}".format(run_id, dut)
    return cell


def _release_label(versions: List[Optional[str]]) -> Optional[str]:
    """The release the day mostly ran, as the heading writes it.

    Accepts either a bare version (``2026.220.0-git…``, from EOS) or pega3's
    fully-qualified suite name (``mlt_2026.220.0-git…``); the station prefix is
    stripped because the heading template supplies it. Where a day ran more
    than one release the most common wins — the heading names a build, and the
    line's own tabs name exactly one.
    """
    seen = [re.sub(r"^(mlt|htt)_", "", v) for v in versions if v]
    if not seen:
        # Nothing ran for this station that day. The heading drops its version
        # rather than inheriting the template's, which would claim a build that
        # never ran above a column that is entirely empty.
        return None
    dominant = Counter(seen).most_common(1)[0][0]
    release = stations.release_of(dominant)
    return "2026.{}".format(release) if release else str(dominant)


def _utc_day(ts: Optional[int]) -> Optional[str]:
    """The tracker's day boundary is UTC, not the factory-local one.

    Established by reconciliation: DUT 268494130000018 runs at 17:30 local on
    08-11, its runId is stamped ``20260812_003002``, and the sheet files it
    under 08-12. Bucketing a derived tab in local time would put its rows on a
    different day from the tabs beside it.
    """
    if not ts:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


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
