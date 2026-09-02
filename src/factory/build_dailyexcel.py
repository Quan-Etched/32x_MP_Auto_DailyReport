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
from datetime import datetime, timedelta, timezone
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

#: Days the workbook has not reached are rebuilt from the controllers so the
#: page keeps going when nobody has exported the sheet yet.
#:
#: Five, not three: the candidate list became calendar-driven, and the calendar
#: includes today — which in UTC arrives mid-afternoon Pacific and is usually
#: empty. Three slots therefore held two real days plus an empty one, and
#: 08-13 silently dropped off a tracker that had shown it the day before. Five
#: covers a working week's tail with room for the empty day.
DERIVE_LIMIT = 5

#: The earliest day the tracker rebuilds, and the first day its calendar shows.
#:
#: The page picks a day from a month grid now, and a grid makes the gaps
#: visible in a way the old strip of buttons did not: 08-03 sat there greyed
#: out as though the line had not tested, when pega3 has eleven runs for it and
#: the only reason there was no tab is that DERIVE_LIMIT kept the last five
#: days and nothing older. A calendar that shows a month has to be able to
#: answer for the month.
#:
#: It was 08-01 — "the first day the line produced", on the grounds that
#: earlier days are bring-up and a tab for one would file debugging as
#: production. Asked for on 2026-09-02 to reach the whole of what the
#: controllers hold, which is 2026-05-21 on pega3, and set to the same floor
#: the collector walks from.
#:
#: READ THE PRE-AUGUST TABS WITH THAT IN MIND. The rationale above was not
#: wrong, it was overruled: June and July were bring-up, and their tabs show
#: bring-up runs in the same shape as production ones. Their yields are not
#: line performance and should not be quoted as such. What they are good for
#: is a unit's own history — the Test History strip reaches through them, so a
#: chassis first tested in June now shows its real first attempt.
DAILY_FROM = pega.CONTROLLER_FROM

#: The stations the tracker covers, and the column pair each one fills.
DERIVED_STATIONS = (("mlt", "E", "F", "G"), ("htt", "H", "I", "J"))

#: Debug and dev suites are not line units. Same policy as the ``_krish``
#: exclusions in stations.py, applied to pega3's wider day.
#:
#: VALIDATION RUNS ARE KEPT, DELIBERATELY
#: They used to be excluded — but only by accident of where the word sat in the
#: name. ``\b`` matches after ``…_validation`` at the end of a name and not
#: inside ``mlt_validation_2026.225…``, so on 08-14 the tracker dropped the two
#: htt validation runs (7 units) and the mlt 220 validation run (8 units) while
#: keeping the 24 units of mlt_validation 225. Nobody chose that; the regex
#: did.
#:
#: The tracker answers "what did the line test today", and a validation build
#: is something the line tested. Now that every row names its own build, the
#: reader can tell them apart without the page deciding for them — which is
#: what the version column was added for. The station yield page still excludes
#: validation (see pega_collect.NOT_PRODUCTION), because "yield" is a claim
#: about production and this is not.
ENGINEERING = re.compile(
    r"(_krish|_out_dir|_SAM|_SMOKE|_etch\d+|^DRY_?RUN|^test_)",
    re.IGNORECASE)

#: A build that is not a release: debug bundles, hand-built tarballs.
#:
#: THESE ARE COUNTED, AND THAT IS A DECISION
#: On 08-15 every HTT run on the line was
#: ``debug_only_htt_2026.223.0-git78e6956e2`` — Justin's bundle, run twice by
#: Yi on production DUTs at a production station. Those units were tested; the
#: tracker's job is to say what the line did.
#:
#: What makes counting them safe is the version column: every row names the
#: build it ran, and the column filters, so a reader who wants release-only
#: numbers can have them in two clicks. The page does not have to decide on
#: their behalf — which is the same reasoning that brought the validation
#: suites back in.
#:
#: Still excluded above: dry runs, smoke tests, an engineer's personal branch,
#: output-directory artefacts. Those are not line units at all.
DEBUG_BUILD = re.compile(r"((^|_)debug|_dbg)", re.IGNORECASE)

#: Anything that is not a plain release build: validation runs and debug
#: bundles both. The tracker counts them — that is the point of the version
#: column — but a yield tile that silently mixes them with production is how
#: somebody reads a validation campaign as the day's line yield. Asked about
#: exactly that: "we're sure the data here doesn't have any potential errors
#: like accidentally including validation runs?"
#:
#: ``kamil_`` is here for L11: every provisioning run pega5 has is
#: ``kamil_L11_provisioning_rms_pdu_cdu``. A name in a suite name means a
#: bring-up run, not a release — the same claim ``debug`` makes — so it is
#: counted and flagged rather than dropped. It cannot collide with a module
#: suite, which are all ``mlt_``/``htt_`` prefixed.
NON_RELEASE = re.compile(
    r"((^|_)debug|_dbg|validation|(^|_)kamil_)", re.IGNORECASE)

#: Which module station a pega3 suite belongs to.
#:
#: Matched on the name rather than on the run id's first characters. The old
#: test was `run_id.startswith("mlt"/"htt")`, which is true of
#: mlt_2026.220.0-… and false of debug_only_htt_2026.223.0-… — so that day's
#: HTT runs were not classified as engineering and excluded, they were not
#: recognised at all. The tab simply had no HTT column and said nothing about
#: why, which is the failure mode this whole page exists to avoid.
STATION_TOKEN = re.compile(r"(?:^|_)(mlt|htt)_", re.IGNORECASE)


def station_of(run_id: str, suite: str) -> Optional[str]:
    """``mlt`` / ``htt`` for a pega3 suite, or None if it is neither."""
    for text in (suite or "", run_id or ""):
        found = STATION_TOKEN.search(text)
        if found:
            return found.group(1).lower()
    return None


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

    # The module line's history, read once for the whole build rather than once
    # per tab — see attempt_index. Lazy: a workbook-only build, or one with the
    # controllers switched off, must not pay for a span it will not read.
    _module_span: Dict[str, Any] = {"index": None, "read": False}

    def module_history() -> Optional[Dict[str, Any]]:
        if not _module_span["read"]:
            _module_span["read"] = True
            if pega.enabled():
                first = max(pega.CONTROLLER_FROM, (
                    datetime.strptime(DAILY_FROM, "%Y-%m-%d").date()
                    - timedelta(days=NEW_INPUT_LOOKBACK)).strftime("%Y-%m-%d"))
                last = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                try:
                    _module_span["index"] = module_index(first, last)
                except Exception:                         # noqa: BLE001
                    _module_span["index"] = None
        return _module_span["index"]

    for name in book.sheet_names():
        match = TAB_PATTERN.match(name)
        if not match:
            continue
        tab = _tab(book, name, match, known_duts, warnings)
        # The sheet is the line's record, but its failure column is knowingly
        # lossy — one name where a unit failed eight tests. Fill it from pega3,
        # which is the system the line was reading when it typed the one.
        if enrich:
            tab = _enrich_from_pega(tab, module_history())
        # Whether or not pega3 answered, the sheet's own heading is split onto
        # two lines, so every tab in the strip has the same shape and switching
        # between them does not move the columns.
        tab = _reformat_sheet_columns(tab)
        tabs.append(tab)

    _drop_always_empty(tabs)

    if not tabs:
        warnings.append(
            "no tab in {} is named like 'MM-DD Nx' — nothing to publish".format(
                source.name))

    # Days the line has tested that the workbook has not caught up with.
    # Derived tabs are marked as such and never overwrite a real one — the
    # line's own record wins wherever it exists.
    if derive:
        have = {tab["day"] for tab in tabs if tab["day"]}
        newest = max(have) if have else ""
        oldest = min(have) if have else ""
        candidates = [day for day in sorted(_candidate_days(payload or {}) - have)
                      if _derivable(day, oldest, newest)]
        for day in candidates:
            newest_real = next((tab for tab in reversed(tabs)
                                if not tab.get("derived")), None)
            built = (_pega_tab(day, newest_real, module_history())
                     if pega.enabled() else None)
            if built is None:
                # pega3 unreachable: fall back to what EOS alone can say, which
                # is per-chip verdicts without the serials.
                built = derived_tab(payload or {}, day, template=newest_real)
            if built:
                tabs.append(built)

    tabs.sort(key=lambda tab: tab["day"] or "")

    # A table each rather than more columns: the serials are different
    # lengths, one chassis holds many modules and one rack holds four chassis,
    # so a row carrying all three would have no single subject. Same format,
    # same renderer, stacked.
    #
    # L10 alongside the module stages, and L11 under that. Three tables, three
    # subjects: a module, a chassis, a rack. One row cannot carry all three.
    # Each controller's history read once for the whole run of tabs, not once
    # per tab. See attempt_index: per tab it is tens of seconds each, and the
    # tracker now publishes every day the controllers hold.
    days_shown = sorted(tab["day"] for tab in tabs if tab.get("day"))
    l10_index = l11_index = None
    if days_shown and pega.enabled():
        from . import build_l10, build_l11
        span_first = max(pega.CONTROLLER_FROM, (
            datetime.strptime(days_shown[0], "%Y-%m-%d").date()
            - timedelta(days=NEW_INPUT_LOOKBACK)).strftime("%Y-%m-%d"))
        try:
            l10_index = build_l10.stage_index(span_first, days_shown[-1])
        except Exception:                                 # noqa: BLE001
            l10_index = None
        try:
            l11_index = build_l11.stage_index(span_first, days_shown[-1])
        except Exception:                                 # noqa: BLE001
            l11_index = None

    for tab in tabs:
        if tab.get("day") and tab["day"] >= L10_FROM:
            l10_tab = _l10_for(tab["day"], l10_index)
            if l10_tab:
                tab["l10"] = l10_tab
        if tab.get("day") and tab["day"] >= L11_FROM:
            l11_tab = _l11_for(tab["day"], l11_index)
            if l11_tab:
                tab["l11"] = l11_tab
        _serial_heading(tab)
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
        # Days somebody has set up a hand-sheet comparison for, so the day view
        # can offer the link on those days and not on the twenty where it would
        # lead nowhere. Read from diff/delta.json — the config, not the built
        # bundle: this module must not depend on a page that depends on it.
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


#: What the serial column is called on every daily table.
SERIAL_HEADING = "SN"


def _serial_heading(tab: Dict[str, Any]) -> None:
    """Head the serial column ``SN`` on this tab and on the two under it.

    The three tables are read together and each was naming its own subject in
    the column head — "DUT SN" over modules, "Chassis SN" over L10, "Rack SN"
    over L11 — which made one column at three levels look like three different
    things. The subject is already stated where it belongs: the section heading
    above each table says L10 or L11 and counts chassis or racks.

    This is the one place the module table can be changed. L10 and L11 set the
    title in their own ``_columns``; the module table's comes from the line's
    workbook, and a sheet-copied tab carries whatever heading the export had.
    Rewriting it here rather than at parse time keeps the workbook reader a
    faithful reader — the only thing overridden is what the page prints.
    """
    for table in (tab, tab.get("l10"), tab.get("l11")):
        for column in (table or {}).get("columns") or []:
            if column.get("key") == "B":
                column["title"] = SERIAL_HEADING



def _derivable(day: str, oldest: str, newest: str) -> bool:
    """Whether a day the workbook does not have may be rebuilt from pega3.

    Outside the sheet's own range, never inside it.

    The rule was "only days after the newest real tab", and half its reason is
    sound: a hole *between* two tabs is the line deciding not to track that day,
    and filling it would compete with their record rather than extend it. But
    the same test also excluded every day *before* the workbook's first tab,
    which is a different thing — the sheet has no opinion about 08-05, it simply
    does not begin until 08-11.

    Nobody noticed while the day picker was a strip of buttons that drew only
    the days it had. On a month grid those days sit in the open, greyed as
    though the line had been idle, and pega3 has runs for eight of them.

    So: after the newest real tab, or before the oldest one, and never before
    the floor. ``oldest``/``newest`` empty means the workbook has no day tabs at
    all, and then every day is outside its range.
    """
    if day < DAILY_FROM:
        return False
    if not oldest or not newest:
        return True
    return day > newest or day < oldest

def _candidate_days(payload: Dict[str, Any]) -> set:
    """Which days to try to rebuild.

    WHY THIS IS NOT JUST "DAYS EOS HAS RUNS FOR"
    It was, and 08-14 never appeared: pega3 had 49 units on it and EOS had
    none, so a day the line had plainly worked was missing from a page whose
    rows come from pega3 anyway. Asking the source that does not have the data
    which days the data covers is how a gap in EOS becomes a gap in the
    tracker — and EOS under-reporting the module line is the finding this
    dashboard exists to show, not an assumption it should build on.

    So the calendar supplies the candidates when pega3 is reachable, and each
    one is tried: a day with nothing on it returns no tab and costs one cached
    listing. EOS's own days are still unioned in, for the case where pega3 is
    unreachable and EOS is all there is.
    """
    days = {_utc_day(run.get("startTs")) for run in payload.get("runs", [])
            if run.get("level") == "module"
            and run.get("stationKey") in ("mlt", "htt")} - {None}

    if pega.enabled():
        # Every day from the floor to today. It was the last DERIVE_LIMIT days,
        # which is why the calendar had a fortnight of grey cells that looked
        # like idle days and were really unbuilt ones.
        today = datetime.now(timezone.utc).date()
        first = datetime.strptime(DAILY_FROM, "%Y-%m-%d").date()
        day = first
        while day <= today:
            days.add(day.strftime("%Y-%m-%d"))
            day += timedelta(days=1)
    return days


def _l10_for(day: str, index: Optional[Dict[str, Any]] = None
             ) -> Optional[Dict[str, Any]]:
    """That day's L10 stages, built by the L10 tracker's own code.

    Imported rather than reimplemented: the stage matching, the pega4 host and
    the four-column shape all live there, and a second copy would be a second
    answer to "did FAT pass today".
    """
    from . import build_l10

    try:
        return build_l10._day(day, index)
    except Exception:                                     # noqa: BLE001
        return None


def _l11_for(day: str, index: Optional[Dict[str, Any]] = None
             ) -> Optional[Dict[str, Any]]:
    """That day's L11 stages, built by the L11 tracker's own code.

    Same arrangement as [_l10_for]: the stage matching, the pega5 host and the
    aborted-is-an-outcome rule live in that module.
    """
    from . import build_l11

    try:
        return build_l11._day(day, index)
    except Exception:                                     # noqa: BLE001
        return None


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
    names: Dict[str, List[Optional[str]]] = {}
    for station, _, _, _ in DERIVED_STATIONS:
        seen = [r.get("version") for r in runs if r.get("stationKey") == station]
        # EOS reports a bare version; the line writes it with the station
        # prefix, so the heading and the column read the same either way.
        names[station] = ["{}_{}".format(station, v) for v in seen if v]
        versions[station] = _version_sub(names[station])

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
                if run.get("version"):
                    row[index[_version_column(station)]] = {
                        "v": "{}_{}".format(station, run["version"])}
                rows.append(row)

    _resync_version_subs(columns, rows)
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
            "versions": {station: _release_label(
                [r.get("version") for r in runs if r.get("stationKey") == station])
                for station, _, _, _ in DERIVED_STATIONS},
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

#: A per-unit version column, inserted after each Results column.
#:
#: WHY THE HEADING ALONE WAS NOT ENOUGH
#: The heading names one build, and 08-14 ran four MLT builds — 220 production,
#: 220 validation, and the 225 commit under two names. A single heading over a
#: column of 39 units silently claims they all ran the build it names, which is
#: how the same day got reported as both 24 units and 39. The row now carries
#: its own build and the heading says how many there were.
VERSION_COLUMNS = (("mlt", "E", "Ev", "MLT Version"),
                   ("htt", "H", "Hv", "HTT Version"))

VERSION_WIDTH = 30.0

#: ``mlt_2026.220`` / ``htt_2026.217`` inside a column heading.
#: The trailing digits are optional so the fallback headings — which carry a
#: bare ``mlt_`` with no version to copy — are substituted too.
VERSION_TOKEN = re.compile(r"(mlt|htt)_[0-9.]*", re.IGNORECASE)

#: The same token including any suffix — ``mlt_2026.220.0-git2f1c2f23`` and
#: ``mlt_validation_2026.225.0-gitb937ca2c``. Used when moving the build out of
#: a heading, where leaving ``.0-git2f1c2f23`` behind would be worse than not
#: splitting at all.
VERSION_TOKEN_FULL = re.compile(r"\b(mlt|htt)_[\w.\-]*", re.IGNORECASE)


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
        key = column.get("key")
        title = VERSION_TOKEN_FULL.sub("", column.get("title") or "").strip()
        entry = {"key": key, "title": title, "width": column.get("width")}
        # The build goes on a second line under the Results heading rather than
        # trailing it. One line of "MLT Results mlt_validation_2026.225.0-
        # gitb937ca2c" was wide enough to push the failure column off the
        # screen, and it is two facts anyway.
        if key in RESULT_COLUMNS:
            entry["sub"] = versions.get(_station_of_column(key))
            # Named on the column so the page can look a row's history up by
            # station rather than re-deriving it from column letters.
            entry["station"] = _station_of_column(key)
        columns.append(entry)

    return _with_version_columns(columns)


def _version_column(station: str) -> str:
    """The version column belonging to a station."""
    for name, _result_col, version_col, _title in VERSION_COLUMNS:
        if name == station:
            return version_col
    raise KeyError(station)


def _station_of_column(key: str) -> Optional[str]:
    for station, result_col, _version_col, _title in VERSION_COLUMNS:
        if result_col == key:
            return station
    return None


def _with_version_columns(columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Put a version column immediately after each Results column.

    Idempotent: a derived tab copies its format from a real tab that has
    already been widened, so inserting unconditionally gives it two.
    """
    present = {column.get("key") for column in columns}
    out: List[Dict[str, Any]] = []
    for column in columns:
        out.append(column)
        for _station, result_col, version_col, title in VERSION_COLUMNS:
            if column.get("key") == result_col and version_col not in present:
                out.append({"key": version_col, "title": title,
                            "width": VERSION_WIDTH, "kind": "version"})
    return out


def _resync_version_subs(columns: List[Dict[str, Any]],
                         rows: List[List[Dict[str, Any]]]) -> None:
    """Make the heading agree with the column under it.

    The heading is computed from the day's runs, the column from the rows that
    survived — and a unit retested drops its earlier build, so 08-14 ran three
    MLT builds but only two reach the table. A heading that counts builds
    nobody can find in the column is the same kind of unfounded claim the
    column was added to remove.
    """
    index = {column["key"]: position for position, column in enumerate(columns)}
    for _station, result_col, version_col, _title in VERSION_COLUMNS:
        if result_col not in index or version_col not in index:
            continue
        position = index[version_col]
        columns[index[result_col]]["sub"] = _version_sub(
            [(row[position] or {}).get("v") for row in rows])


def _version_sub(names: List[Optional[str]]) -> Optional[str]:
    """The second line of a Results heading.

    One build gets named. Several get counted, and the reader is sent to the
    column that has the answer per unit — naming the most common one would be
    the same overclaim that made 24 and 39 look like a contradiction.
    """
    distinct = sorted({name for name in names if name})
    if not distinct:
        return None
    if len(distinct) == 1:
        return distinct[0]
    return "{} versions in this column".format(len(distinct))


def _enrich_from_pega(tab: Dict[str, Any],
                      history_index: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
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
    return _add_sheet_versions(tab, units, history_index)


def _add_sheet_versions(tab: Dict[str, Any],
                        units: Dict[str, Dict[str, Any]],
                        history_index: Optional[Dict[str, Any]] = None
                        ) -> Dict[str, Any]:
    """Give a hand-kept tab the per-unit version column too.

    The sheet has no such column — it writes one build in the heading — so this
    is the one place a derived value is added to the line's own record rather
    than filling one it left blank. It is worth it for the same reason the
    column exists at all: on a day that ran more than one build, the heading is
    a claim about every row that is true of only some of them.
    """
    tab = _widen_for_versions(tab)
    if "B" not in {column["key"] for column in tab["columns"]}:
        return tab

    at = {column["key"]: position for position, column in enumerate(tab["columns"])}
    # The line's own tabs get the same new-input marking as the rebuilt ones.
    # Without it every unit on 08-11 and 08-12 reads as fresh material, and the
    # two halves of the strip would answer the toggle differently.
    history = (_seen_before(tab["day"], index=history_index)
               if tab.get("day") else {})
    for row in tab["rows"]:
        dut = (row[at["B"]].get("v") or "").strip()
        unit = units.get(dut) or {}
        serial = row[at["B"]]
        for station, _result_col, version_col, _title in VERSION_COLUMNS:
            suite = (unit.get(station) or {}).get("suite")
            if suite:
                row[at[version_col]] = {"v": suite}
            # Same rule as the derived path: a station the unit has a past at
            # gets its history, whether or not it ran there today. A blank cell
            # with "P1 08-20" beside it says something a blank cell alone
            # cannot.
            past = history.get(station, {}).get(dut) or []
            today = _day_attempts(unit, station)
            if past:
                serial.setdefault("seen", {})[station] = past[-1]["day"]
            if past or len(today) > 1:
                serial.setdefault("history", {})[station] = \
                    _numbered_history(past, today)
        serial["new"] = "seen" not in serial

    # What the sheet leaves out, and whether it is the re-runs.
    #
    # Asked of 08-12: why do Count all and Count new agree? Because they do —
    # on a hand-kept tab there is nothing to add. pega3 recorded 59 MLT units
    # that day and the sheet lists 51, and all eight of the missing ones are
    # units the station had seen before. Same on 08-11: 100 against 87, and
    # all thirteen omitted are returning. The line was already keeping a
    # new-input-only record by hand, so its own tabs cannot show the
    # difference the derived ones do — and a page that offers a Count all
    # button on them owes the reader that sentence.
    omits: Dict[str, Dict[str, int]] = {}
    on_sheet = {(row[at["B"]].get("v") or "").strip() for row in tab["rows"]}
    for station, _result_col, _version_col, _title in VERSION_COLUMNS:
        ran = {dut for dut, unit in units.items() if station in unit}
        missing = ran - on_sheet
        if not missing:
            continue
        omits[station] = {
            "units": len(missing),
            "returning": len([d for d in missing
                              if history.get(station, {}).get(d)]),
            "ranThatDay": len(ran),
        }
    if omits:
        tab["sheetOmits"] = omits

    tab["counts"] = _counts(tab["rows"], tab["columns"])
    # The line's own tabs get the same wrong-flow detection as the rebuilt ones.
    # Without it the control would be silently absent on 08-11 and 08-12 —
    # correct today, since neither has any, but absent for the wrong reason.
    tab["misflow"] = misflow_for(units, history, tab.get("day"))
    return tab


def _widen_for_versions(tab: Dict[str, Any]) -> Dict[str, Any]:
    """Make room for the version columns, leaving the cells empty."""
    keys = {column["key"] for column in tab.get("columns") or []}
    if all(key in keys for _s, _r, key, _t in VERSION_COLUMNS):
        return tab

    index = {column["key"]: position
             for position, column in enumerate(tab["columns"])}
    columns = _with_version_columns(tab["columns"])
    at = {column["key"]: position for position, column in enumerate(columns)}
    rows = []
    for row in tab.get("rows") or []:
        wide = [{} for _ in columns]
        for key, position in index.items():
            if position < len(row):
                wide[at[key]] = row[position]
        rows.append(wide)
    tab["columns"] = columns
    tab["rows"] = rows
    return tab


#: Columns that stay even when every cell is blank, because blank is the
#: answer: a unit that never reached HTT has an empty HTT result, and dropping
#: the column would turn "did not run" into "not tracked".
KEEP_WHEN_EMPTY = frozenset(
    [result for _s, result, _v, _t in VERSION_COLUMNS] +
    [version for _s, _r, version, _t in VERSION_COLUMNS] +
    # Date, DUT SN, the two failure columns and the two link columns. An empty
    # failure column says the day had no failures, which is the best news the
    # tracker can carry and must not be deleted for being blank.
    ["A", "B", "F", "G", "I", "J"])


def _drop_always_empty(tabs: List[Dict[str, Any]]) -> None:
    """Drop a column no tab has ever filled.

    ASIC SN is the case in hand: the sheet carries the column and the line has
    never typed in it, so it is 158 empty cells of horizontal space between the
    serial and the part number. Judged across every published tab rather than
    per tab, so the tabs keep one shape and the column reappears by itself if
    the line starts filling it.
    """
    keys = [column["key"] for column in (tabs[0]["columns"] if tabs else [])]
    empty = []
    for key in keys:
        if key in KEEP_WHEN_EMPTY:
            continue
        used = False
        for tab in tabs:
            index = {column["key"]: position
                     for position, column in enumerate(tab["columns"])}
            position = index.get(key)
            if position is None:
                continue
            for row in tab["rows"]:
                cell = row[position] if position < len(row) else {}
                if cell.get("v") or cell.get("h") or cell.get("j"):
                    used = True
                    break
            if used:
                break
        if not used:
            empty.append(key)

    for key in empty:
        for tab in tabs:
            index = {column["key"]: position
                     for position, column in enumerate(tab["columns"])}
            position = index.get(key)
            if position is None:
                continue
            tab["columns"] = [column for column in tab["columns"]
                              if column["key"] != key]
            tab["rows"] = [row[:position] + row[position + 1:]
                           for row in tab["rows"]]
            tab["counts"] = _counts(tab["rows"], tab["columns"])


def _reformat_sheet_columns(tab: Dict[str, Any]) -> Dict[str, Any]:
    """Move the build out of a Results heading and onto a second line."""
    tab = _widen_for_versions(tab)
    columns = []
    for column in tab.get("columns") or []:
        title = column.get("title") or ""
        entry = dict(column)
        found = VERSION_TOKEN_FULL.search(title)
        if found:
            entry["title"] = VERSION_TOKEN_FULL.sub("", title).strip()
        if column.get("key") in RESULT_COLUMNS:
            versions = _sheet_versions(tab, column["key"])
            entry["sub"] = _version_sub(versions) or (
                found.group(0) if found else None)
            entry["station"] = _station_of_column(column["key"])
        columns.append(entry)
    tab["columns"] = columns
    if tab.get("rows"):
        tab["counts"] = _counts(tab["rows"], columns)
    return tab


def _sheet_versions(tab: Dict[str, Any], result_key: str) -> List[Optional[str]]:
    """What the version column of a real tab actually holds, row by row."""
    station = _station_of_column(result_key)
    index = {column["key"]: position for position, column in enumerate(tab["columns"])}
    position = index.get(_version_column(station)) if station else None
    if position is None:
        return []
    return [(row[position] or {}).get("v") for row in tab.get("rows") or []
            if position < len(row)]


#: The earliest day L10 is looked for on the module tracker.
#:
#: Every published day, now that the standalone L10 page is gone: a floor here
#: would be a floor on where L10 can be seen at all. The table is clearly
#: marked as rebuilt from pega4 and sits under the module one, so a day whose
#: module rows come from the line's own sheet is not made to look as though
#: the sheet carried L10 too.
L10_FROM = "0000-00-00"

#: The earliest day L11 is looked for.
#:
#: Every published day, same as L10. This had a floor at 08-17, on the argument
#: that pega5's earlier rows are rack bring-up rather than production testing.
#: They are — and the daily tracker is the only place they can be seen, so the
#: floor was not keeping bring-up out of the production record, it was keeping
#: L11 off the page for the fortnight it was actually being worked on. The
#: table says "from pega5" and sits under the module and L10 ones, so no day's
#: rack runs can be read as something the line's own sheet recorded.
L11_FROM = "0000-00-00"


#: How far back to look before calling a unit new.
#:
#: A day's yield is normally read as "how did today's build go", and a unit
#: that failed a fortnight ago and is re-run today answers a different question
#: — it says whether a fix worked, not how the fresh material is doing. Mixing
#: the two moves the number without anything on the line changing.
#:
#: Thirty days, asked for by the line. It was ten, chosen to cover the retest
#: campaigns as they were then run; the campaigns since have been longer than
#: that — a unit failing at MLT in the first week of the month and coming back
#: at the end of it counted as fresh material, which is the one thing this
#: window exists to prevent. Thirty is still inside what the controllers keep
#: (pega holds ninety), so the window is a judgement about the line rather
#: than a limit of the source.
#:
#: This is one number, not two: it decides both which rows are new input and
#: how far the Test History column reaches back. Splitting them would let the
#: table show an attempt that the tile beside it had already ruled out of
#: scope.
#:
#: It was 30, then everything the controllers hold, asked for on 2026-09-02.
#: The reason is the strip: at 30 days "F1" meant the unit's first attempt *in
#: the last 30 days*, which for a chassis first tested in June is not its first
#: attempt at all, and a numbering that quietly redefines its own 1 cannot be
#: checked against anything. Now F1 is F1.
#:
#: It moves the new-input yield with it, deliberately and in the strict
#: direction: a unit the line saw in June is a returning unit, and used to be
#: counted as fresh material. Fewer rows are new input than before and the
#: number is smaller — that is the definition being applied honestly, not a
#: regression.
#:
#: Derived from the floor rather than fixed, so it cannot walk away from the
#: start of the data the way the collector's 90 days did.
def _lookback_days() -> int:
    span = (datetime.now(timezone.utc).date()
            - datetime.strptime(pega.CONTROLLER_FROM, "%Y-%m-%d").date()).days
    return max(30, span)


NEW_INPUT_LOOKBACK = _lookback_days()


#: Suffix for the per-station list of the day's own attempts, kept on the unit
#: beside its verdict — same shape as the ``":release"`` key above it. A list,
#: not a count: the Test History strip ends on the day's last attempt, and to
#: draw it each attempt needs its verdict and its link, not a tally.
ATTEMPTS_KEY = ":attempts"


#: Spans already read, so a process that builds more than one bundle pays for
#: each span once. A build does; so does the test suite, and there it was the
#: difference between a suite that runs in three minutes and one that does not
#: finish — every ``build_bundle`` was re-reading the same months.
#:
#: Keyed on the two fetchers as well as the span. The tests replace them, and
#: two different stubs are two different answers to the same three dates; the
#: function objects rather than their ids, because an id is reused once the
#: object it named is collected.
_SPAN_CACHE: Dict[Any, Dict[str, Dict[str, List[Dict[str, str]]]]] = {}


def forget_spans() -> None:
    """Drop the memo. For a caller that has changed what the controllers say."""
    _SPAN_CACHE.clear()


def attempt_index(host: str, keys, key_of, url_of,
                  first: str, last: str
                  ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """Every attempt each station made over a whole span, in one pass.

    ``{station: {dut: [{day, status, url, suite}, …]}}``, each unit's list in
    time order.

    WHY A SPAN AND NOT A DAY. This used to be walked per tab: for each day the
    tracker published, re-read the previous N days of listings and every run
    detail in them. That is the same work over and over — 104 tabs each
    re-reading the same runs — and it was affordable only because N was 30 and
    the tracker began on 08-01. Measured at the full span it is 45 seconds per
    tab warm, about 78 minutes for one build. Read once and sliced per tab, it
    is a few seconds in total.

    Callers pass ``key_of`` and ``url_of`` because the three trackers differ
    only in how a suite name maps to a station and how a run turns into a link.
    """
    cache_key = (host, first, last, tuple(keys),
                 pega.day_suite_runs, pega.suite_run)
    if cache_key in _SPAN_CACHE:
        return _SPAN_CACHE[cache_key]

    index: Dict[str, Dict[str, List[Dict[str, str]]]] = {key: {} for key in keys}
    for day in pega.day_range(first, last):
        try:
            listing = pega.day_suite_runs(day, host=host)
        except pega.PegaUnavailable:
            continue
        for entry in sorted(listing, key=lambda e: e.get("start_time") or ""):
            key = key_of(entry)
            if not key or key not in index:
                continue
            run_id = entry.get("suite_run_id") or ""
            try:
                detail = pega.suite_run(run_id, host=host)
            except pega.PegaUnavailable:
                continue
            for part in pega.participants(detail):
                if part["status"] not in ("pass", "fail"):
                    continue
                index[key].setdefault(part["dut"], []).append({
                    "day": day,
                    "status": part["status"],
                    "url": url_of(run_id, part["slot"]),
                    "suite": entry.get("suite_name") or "",
                })
    _SPAN_CACHE[cache_key] = index
    return index


def slice_before(index: Dict[str, Dict[str, List[Dict[str, str]]]],
                 day: str, lookback: int
                 ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """The part of an index that lies before ``day``, within ``lookback``.

    Strictly before: the row's own day is the row, not its history.
    """
    floor = (datetime.strptime(day, "%Y-%m-%d").date()
             - timedelta(days=lookback)).strftime("%Y-%m-%d")
    out: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    for key, duts in index.items():
        kept: Dict[str, List[Dict[str, str]]] = {}
        for dut, attempts in duts.items():
            got = [a for a in attempts if floor <= a["day"] < day]
            if got:
                kept[dut] = got
        out[key] = kept
    return out


#: The stations the module tracker indexes, and how a pega3 run maps onto one.
MODULE_STATIONS = ("mlt", "htt")


def _module_station(entry: Dict[str, Any]) -> Optional[str]:
    """Which module station a pega3 run belongs to, if any.

    Engineering runs are not line units and never belonged in a unit's
    history: a ``_krish`` debug bundle in the strip would number a real
    attempt as the unit's fifth when the line only put it through four.
    """
    run_id = entry.get("suite_run_id") or ""
    suite = entry.get("suite_name") or ""
    if ENGINEERING.search(run_id) or ENGINEERING.search(suite):
        return None
    return station_of(run_id, suite)


def module_index(first: str, last: str
                 ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """:func:`attempt_index` for the module line."""
    return attempt_index(
        "pega3", MODULE_STATIONS, _module_station,
        lambda run_id, slot: pega.run_url(run_id, slot),
        first, last)


def _seen_before(day: str, lookback: int = NEW_INPUT_LOOKBACK,
                 index: Optional[Dict[str, Dict[str, List[Dict[str, str]]]]] = None
                 ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """Every attempt each station made on a serial before ``day``.

    Station -> {dut: [{day, status, url}, …]} in time order. The dates alone
    would say a unit is a returning one; the attempts say what happened on
    each visit and link to it, which is what makes "F1 P2" on the row
    checkable rather than a claim.

    ``index`` is a span read once by the caller — see :func:`attempt_index`.
    Without one this reads the span itself, which is what a standalone call
    and the tests do.
    """
    if not pega.enabled():
        return {"mlt": {}, "htt": {}}
    if index is not None:
        return slice_before(index, day, lookback)

    start = datetime.strptime(day, "%Y-%m-%d").date()
    first = max(pega.CONTROLLER_FROM,
                (start - timedelta(days=lookback)).strftime("%Y-%m-%d"))
    last = (start - timedelta(days=1)).strftime("%Y-%m-%d")
    return slice_before(module_index(first, last), day, lookback)


#: A unit at HTT that should not be there, and which of the two kinds it is.
#:
#: THE DISTINCTION THAT MAKES THIS USEFUL
#: A unit with no MLT verdict on the day is usually not a flow error: it passed
#: MLT yesterday and reached HTT this morning. Since 08-01 that is 80 of the 92
#: such units, and calling them wrong flow would have flagged an ordinary day
#: and thrown 17 good units out of 08-14's HTT yield.
#:
#: So the wrong flow is narrower and there are exactly two kinds:
#:   ``failed``   MLT failed on the day and the unit went to HTT anyway.
#:   ``unproven`` nothing on record — this day or in the lookback — shows the
#:                unit ever passing MLT.
#: Computed here rather than in the page, because the daily tab and the weekly
#: rollup both need it and two implementations of "wrong flow" would disagree
#: inside a week.
MISFLOW_KINDS = ("failed", "unproven")


def misflow_for(units: Dict[str, Dict[str, Any]],
                history: Dict[str, Dict[str, List[Dict[str, str]]]],
                day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every unit that reached HTT without an MLT pass behind it."""
    out: List[Dict[str, Any]] = []
    for dut in sorted(units):
        unit = units[dut]
        htt = unit.get("htt") or {}
        if htt.get("status") not in ("pass", "fail"):
            continue
        mlt = unit.get("mlt") or {}
        status = mlt.get("status")
        if status == "pass":
            continue
        if status == "fail":
            kind = "failed"
        else:
            past = (history.get("mlt") or {}).get(dut) or []
            if any(attempt.get("status") == "pass" for attempt in past):
                continue                      # passed MLT earlier — fine
            kind = "unproven"
        out.append({
            "dut": dut,
            "kind": kind,
            "day": day,
            "mlt": status or "",
            "htt": htt.get("status") or "",
            # The raw record, so the count on the page can be followed to the
            # run it is about instead of taken on trust.
            "httUrl": htt.get("url") or "",
            "httRun": htt.get("short") or "",
            "mltUrl": mlt.get("url") or "",
            "mltRun": mlt.get("short") or "",
            "suite": htt.get("suite") or "",
        })
    return out


def _day_attempts(unit: Dict[str, Any], station: str) -> List[Dict[str, str]]:
    """What this unit did at this station on the row's own day, oldest first.

    Collected as the runs arrive rather than read back in order, because the
    controllers do not return a day's listing in time order. The sort key is
    dropped on the way out so a today attempt carries the same four fields a
    prior-day one does and the strip stays one kind of thing.
    """
    attempts = sorted(unit.get(station + ATTEMPTS_KEY) or [],
                      key=lambda attempt: attempt.get("started") or "")
    return [{key: value for key, value in attempt.items() if key != "started"}
            for attempt in attempts]


def _numbered_history(past: List[Dict[str, str]],
                      today: Optional[List[Dict[str, str]]] = None
                      ) -> List[Dict[str, Any]]:
    """Every attempt this unit made at the station, numbered from its first.

    ``past`` is the prior days from :func:`_seen_before` and ``today`` is the
    row's own day, both oldest first. They go in one strip because that is how
    the strip is read — as this unit's story at this station, in order.

    Ending it on the day before was actively misleading. 268645440002 on the
    09-01 L10 tab read ``F2 F3 F4 F5 F6 F7 F8 F9  08-31`` beside a verdict of
    Passed: nine failures, no pass anywhere in the part of the row people
    actually look at, and the unit had in fact passed FAT that afternoon on
    its tenth try. The verdict column had it right and nobody reads the
    verdict column when the strip beside it is shouting. Now the strip ends
    where the day ends — ``F1 … F9 P10`` — and it agrees with the cell it sits
    next to.

    Not trimmed, either. It used to keep the last eight, which is what cost
    that row its ``F1``: the numbering is only trustworthy if the reader can
    see it start, and "why does this unit have no first attempt" is a worse
    thing to leave on the page than a wide cell. The widest real case in the
    last month is nineteen chips (267694410002 at L10 2U); the cell wraps.
    """
    return [dict(attempt, n=index + 1)
            for index, attempt in enumerate(list(past) + list(today or []))]


def _pega_units(day: str) -> Optional[Tuple[Dict[str, Dict[str, Any]],
                                            Dict[str, List[str]], int,
                                            Dict[str, List[str]],
                                            Dict[str, List[str]]]]:
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
        listing = pega.day_suite_runs(day, host="pega3")
    except pega.PegaUnavailable:
        return None

    units: Dict[str, Dict[str, Any]] = {}
    versions: Dict[str, List[str]] = {"mlt": [], "htt": []}
    excluded: Dict[str, List[str]] = {"mlt": [], "htt": []}
    debug_builds: Dict[str, List[str]] = {"mlt": [], "htt": []}
    runs_seen = 0

    for entry in listing:
        run_id = entry.get("suite_run_id") or ""
        suite = entry.get("suite_name") or ""
        station = station_of(run_id, suite)
        if not station:
            continue
        # Engineering runs, excluded for the same reason stations.py drops the
        # _krish debug suites: they are not line units and would distort the
        # day's yield. pega3's day includes them; the line's tracker does not.
        #
        # Counted on the way out, though. "No HTT today" and "HTT ran five
        # times and every one was a debug bundle" are different facts, and the
        # tab used to show the same empty column for both.
        if ENGINEERING.search(run_id) or ENGINEERING.search(suite):
            excluded[station].append(suite)
            continue
        # Counted, but recorded: a day whose only HTT was a debug bundle reads
        # very differently from a normal day, and the tile should say so
        # without the reader having to notice it in the version column.
        if DEBUG_BUILD.search(suite) or DEBUG_BUILD.search(run_id):
            debug_builds[station].append(suite)
        try:
            detail = pega.suite_run(run_id, host="pega3")
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
            # The last *release* attempt, kept separately from the last attempt
            # of any kind. On 08-14 sixteen units ran mlt_2026.225.0 at 08:23
            # and mlt_validation_225 at 10:03; the row shows the validation
            # result, and a release-only tally that just filtered those rows
            # lost all sixteen units rather than counting the release run they
            # really had.
            #
            # Above the "latest attempt wins" guard below, deliberately: that
            # guard returns early for any run older than the one already held,
            # and pega3 does not return a day's runs in time order — so the
            # 08:23 release run arrived after the 10:03 validation run and was
            # skipped before it could be recorded.
            if not NON_RELEASE.search(suite):
                previous_release = unit.get(station + ":release")
                if not previous_release or previous_release["started"] < started:
                    unit[station + ":release"] = {
                        "status": part["status"], "suite": suite,
                        "started": started,
                    }

            # Every attempt of the day, not only the one that wins the row.
            # The row keeps the last; the Test History strip beside it keeps
            # all of them, which is the difference between "passed" and
            # "failed twice and then passed".
            if part["status"] in ("pass", "fail"):
                unit.setdefault(station + ATTEMPTS_KEY, []).append({
                    "day": day,
                    "status": part["status"],
                    "url": pega.run_url(run_id, part["slot"]),
                    "suite": suite,
                    "started": started,
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
                # The build *this unit* ran, which on a mixed day is not the
                # build in the column heading.
                "suite": suite,
            }

    if not units:
        return None
    return units, versions, runs_seen, excluded, debug_builds


def _pega_tab(day: str, template: Optional[Dict[str, Any]],
              history_index: Optional[Dict[str, Any]] = None
              ) -> Optional[Dict[str, Any]]:
    """A day's tracker rebuilt from pega3 — the sheet's own source.

    pega3 assigns the slots, so it knows all eight DUT serials, the part number,
    every failing test case and the very link the sheet pastes into its FI Test
    Link column. Rows come out per unit with MLT and HTT merged, which is the
    shape the line's tabs have.
    """
    gathered = _pega_units(day)
    if not gathered:
        return None
    units, versions, runs_seen, excluded, debug_builds = gathered

    # Line 2 of the heading names the build when the day ran one and counts
    # them when it ran several; the per-unit column carries the truth either way.
    subs = {station: _version_sub(list(seen)) for station, seen in versions.items()}
    labels = {station: _release_label(list(seen)) for station, seen in versions.items()}
    columns = _derived_columns(template, subs)
    index = {column["key"]: position for position, column in enumerate(columns)}

    def sort_key(item):
        dut, unit = item
        # Passes first, failures last — the order the line's own tabs read in.
        bad = any((unit.get(s) or {}).get("status") == "fail" for s in ("mlt", "htt"))
        return (bad, dut)

    history = _seen_before(day, index=history_index)

    rows = []
    for dut, unit in sorted(units.items(), key=sort_key):
        row = [{} for _ in columns]
        row[index["A"]] = {"v": day}
        # The serial carries whether the line had seen it before, and when.
        # A day's yield is read as "how did today's build go", and a unit
        # returning from Monday answers a different question.
        serial: Dict[str, Any] = {"v": dut}
        # Every station the serial has a past at, not only the ones it ran
        # today.
        #
        # This used to skip a station the unit had no run at on this day, and
        # that is precisely the case somebody asks about: 268524660000006
        # passed MLT at 16:58 on 08-20 and came back for HTT at 00:52 on 08-21,
        # so its 08-21 row had a blank MLT cell, no history behind it, and no
        # way to tell "passed yesterday" from "never ran". The result was never
        # missing — it is on the 08-20 tab — but the row that people were
        # reading could not say so.
        #
        # The per-column counts are unaffected: they key on
        # ``seen[station]`` only for cells that carry a verdict, and a station
        # the unit did not run today is blank. What changes is that the blank
        # now carries its own history, which is the whole point of the column.
        for station, _result, _fail, _link in DERIVED_STATIONS:
            past = history.get(station, {}).get(dut) or []
            today = _day_attempts(unit, station)
            # "seen" and "new" stay prior-days-only, deliberately: they decide
            # which rows Count new keeps, and a unit is fresh material or not
            # by what it did *before* today. Only the strip grows.
            if past:
                serial.setdefault("seen", {})[station] = past[-1]["day"]
            # One attempt and nothing behind it is not a history — the verdict
            # column already says it. Two is: it is a retest.
            if past or len(today) > 1:
                serial.setdefault("history", {})[station] = \
                    _numbered_history(past, today)
        serial["new"] = "seen" not in serial
        row[index["B"]] = serial
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
            if got.get("suite"):
                cell = {"v": got["suite"]}
                release = unit.get(station + ":release")
                if release and release["suite"] != got["suite"]:
                    # Same unit, same day, a release run that a later
                    # non-release run superseded. The table shows where the
                    # unit ended up; the tile needs what it did on the release.
                    cell["rel"] = release["suite"]
                    cell["relStatus"] = release["status"]
                elif release:
                    cell["relStatus"] = release["status"]
                row[index[_version_column(station)]] = cell
        rows.append(row)

    _resync_version_subs(columns, rows)

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
            # Whether this day's runs came off the network or out of the
            # cache after a failed fetch.
            #
            # On 2026-08-27 one listing call timed out, the cache caught the
            # fall, and the cached copy was hours old — so the tab was built
            # from six runs when pega3 had fifteen, reported nothing excluded,
            # and its note said it had been rebuilt from pega3. A stale answer
            # presented as a fresh one is the exact failure this page exists to
            # avoid, so now it says.
            "staleListing": pega.fell_back("pega3"),
            "excluded": {station: sorted(set(names))
                         for station, names in excluded.items() if names},
            "excludedRuns": {station: len(names)
                             for station, names in excluded.items() if names},
            "debugBuilds": {station: sorted(set(names))
                            for station, names in debug_builds.items() if names},
            "note": "Rebuilt from pega3, which assigns the slots and therefore "
                    "knows every unit's serial.",
        },
        "columns": columns,
        "rows": rows,
        "counts": _counts(rows, columns),
        # Units at HTT with no MLT pass behind them, with the run each one is
        # about. Computed here so the day view and the weekly rollup share one
        # definition rather than two that drift.
        "misflow": misflow_for(units, history, day),
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
    # release_of returns the input unchanged when it cannot parse one, so
    # "2026." must only be prepended to something that really is a release
    # number. Without the check, mlt_validation_2026.225.0-gitb937ca2c came out
    # as "mlt_2026.validation_2026.225.0-gitb937ca2c" in the column heading.
    if release and str(release).isdigit():
        return "2026.{}".format(release)
    return str(dominant)


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
    """Pass/fail per result column, by the sheet's own colouring.

    Counted twice: once over everything the station ran, and once over release
    builds alone. The tab deliberately includes validation and debug runs —
    they are real units tested on real stations — but the yield above the table
    must not quietly become a mixture. Where the two differ, the page shows
    both and says which is which.
    """
    index = {entry["key"]: position for position, entry in enumerate(header)}
    serial_at = index.get("B")
    counts = {}
    # Driven by the header rather than by a fixed pair of column letters: the
    # L10 tracker has four result columns at different letters and wants the
    # same tallies, and two copies of this arithmetic would be two chances to
    # count a day differently on two pages.
    for position, entry in enumerate(header):
        column = entry["key"]
        station = entry.get("station")
        # A version column names its station too, so that a result column can
        # find its pair — but it holds a build name, not a verdict, and
        # tallying it produced four phantom tiles on the L10 page.
        if not station or entry.get("kind") == "version":
            continue
        version_at = next(
            (i for i in range(position + 1, len(header))
             if header[i].get("kind") == "version"
             and header[i].get("station", station) == station), None)

        def tally():
            # `abort` is its own bucket, not part of `blank`. It only ever
            # fills on L11, where a third of runs end without a verdict, and
            # folding it into blank made the tile say "not run" about a rack
            # that ran for an hour and gave up.
            return {"pass": 0, "fail": 0, "abort": 0, "blank": 0}

        # Four tallies, from two independent questions the page has to keep
        # apart: everything the station ran versus release builds only, and
        # every unit versus new input only. Collapsing either pair would put a
        # number on screen that answers a question nobody asked.
        every, every_release = tally(), tally()
        fresh, fresh_release = tally(), tally()
        non_release: List[str] = []
        returning = 0

        for row in rows:
            cell = row[position] if position < len(row) else {}
            tone = cell.get("t")
            bucket = tone if tone in ("pass", "fail", "abort") else "blank"

            serial = (row[serial_at] or {}) if (
                serial_at is not None and serial_at < len(row)) else {}
            # New at *this* station: a unit can be new to HTT and returning to
            # MLT on the same row, and the columns are counted separately.
            is_new = not (serial.get("seen") or {}).get(station)
            if not is_new and bucket != "blank":
                returning += 1

            every[bucket] += 1
            if is_new:
                fresh[bucket] += 1

            version = (row[version_at] or {}) if (
                version_at is not None and version_at < len(row)) else {}
            build = version.get("v") or ""
            if build and NON_RELEASE.search(build):
                if build not in non_release:
                    non_release.append(build)
                # The unit may still have run a release build earlier the same
                # day. Count that verdict rather than dropping the unit.
                status = version.get("relStatus")
                if status in ("pass", "fail"):
                    every_release[status] += 1
                    if is_new:
                        fresh_release[status] += 1
                continue
            every_release[bucket] += 1
            if is_new:
                fresh_release[bucket] += 1

        counts[column] = dict(every, title=header[position]["title"],
                              station=station,
                              sub=header[position].get("sub"),
                              release=every_release,
                              new=fresh,
                              newRelease=fresh_release,
                              returning=returning,
                              lookback=NEW_INPUT_LOOKBACK,
                              nonRelease=sorted(non_release))
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
