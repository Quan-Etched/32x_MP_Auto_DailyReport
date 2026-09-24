"""Standup markdown from one day's MLT/HTT tracker tab.

The floor already writes a short note like this every morning::

    A03 Sohu Module Retest 54x SohuLaneRepairTestCase failed unit
    34/54 passed MLT/HTT

    MLT 257: 41x PASS / 13x FAIL
    Only 1/54 still failed on SohuLaneRepairTestCase https://...
    New symptom ProvisionTpmTestCase failure https://...

    HTT 257: 34x PASS / 7x FAIL
    Test Tracker: https://docs.google.com/...
    Master Jira: https://etched-ai.atlassian.net/browse/ETCH-42215

The numbers here come from the same tab ``dailyexcel.html`` shows — one row
per unit, the line's (or pega3's) own verdicts. Jira keys come from the sheet's
notes column first, then from ``errors/established.json``. Nothing is invented:
a failure with no ticket is a count and a test-case name, not a guessed link.

``--cohort-case`` is what turns today's list into a *retest* note. Without it
the title is the day and the bullets are just counts; with it, remaining hits
of that case become "still failed" and everything else becomes "New symptom".
That split cannot be inferred from today's failures — on a successful retest
the original case is no longer the most common one.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import build_dailyexcel, build_errors, config, links, pega, stations

DEFAULT_PRODUCT = "Sohu Module"
DEFAULT_DIR = config.REPO_ROOT / "daily"
BUNDLE = config.DASHBOARD_DATA_DIR / "dailyexcel.js"

#: How far back a refresh walks when the on-disk bundle has no tabs.
#: Also the minimum: the last published day is always re-fetched, because a
#: listing captured while that day was still running is how 09-11 froze.
REFRESH_LOOKBACK = 14

#: Extra prose in the notes column that is the whole finding, not a suffix on
#: the test-case name. "Operator issue during MLT" is a bullet of its own;
#: "need to follow up" rides on the case.
NOTE_IS_FINDING = re.compile(
    r"\b(operator|ops|human|misload|wrong slot|wrong unit)\b", re.I)


class NoTab(Exception):
    """There is no tracker tab to write a report from."""


# --------------------------------------------------------------------- load

def _read_js_bundle(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))


def load_bundle(path: Optional[Path] = None) -> Dict[str, Any]:
    """The published daily-tracker bundle, or a workbook-only rebuild.

    Used by ``--offline``. The default path fetches from pega3 first
    (:func:`refresh`) so a laptop that last collected on 09-11 does not keep
    reporting 09-11.
    """
    source = path or BUNDLE
    if source.exists():
        return _read_js_bundle(source)
    try:
        return build_dailyexcel.build_bundle({}, derive=False, enrich=False)
    except FileNotFoundError as exc:
        raise NoTab(
            "No daily tracker — run without --offline to fetch from pega3 ({})"
            .format(exc)
        ) from exc


def _existing_tabs() -> List[Dict[str, Any]]:
    if not BUNDLE.exists():
        return []
    try:
        return list((_read_js_bundle(BUNDLE).get("tabs") or []))
    except (OSError, ValueError, IndexError):
        return []


def refresh_window(day: Optional[str] = None,
                   lookback: int = REFRESH_LOOKBACK,
                   tabs: Optional[List[Dict[str, Any]]] = None,
                   today: Optional[str] = None) -> Tuple[str, str]:
    """Inclusive ``(start, today)`` of listings to drop and re-fetch."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.strptime(today, "%Y-%m-%d").date()
             - timedelta(days=lookback)).strftime("%Y-%m-%d")
    held = [tab.get("day") for tab in (tabs if tabs is not None
                                       else _existing_tabs()) if tab.get("day")]
    if held:
        # Re-read the newest published day: it may have been cached mid-shift.
        start = min(start, max(held))
    if day:
        start = min(start, day)
    if start > today:
        start = today
    return start, today


def refresh(day: Optional[str] = None, lookback: int = REFRESH_LOOKBACK
            ) -> Dict[str, Any]:
    """Drop recent pega3 listings, rebuild those days, write the bundle.

    Older tabs already on disk are kept. Run details stay cached — only the
    per-day run *list* is thrown away, which is what goes stale.
    """
    if not pega.enabled():
        raise NoTab("pega3 is switched off (FACTORY_PEGA=0); cannot fetch")
    if pega.offline("pega3"):
        print("pega3 is marked offline — using the on-disk tracker",
              file=sys.stderr)
        return load_bundle()
    if not pega.available():
        raise NoTab(
            "pega3 is unreachable. Connect to the office network or VPN "
            "and retry."
        )

    existing = _read_js_bundle(BUNDLE) if BUNDLE.exists() else {}
    tabs = list(existing.get("tabs") or [])
    start, today = refresh_window(day, lookback, tabs)
    dropped = pega.drop_listings(start, today, hosts=("pega3",))
    print("Fetching pega3 {} .. {} (dropped {} cached listings)".format(
        start, today, dropped), file=sys.stderr)

    template = None
    for tab in reversed(tabs):
        if tab.get("columns"):
            template = tab
            break
    if template is None:
        template = {"columns": build_dailyexcel._derived_columns(None, {})}

    fresh: Dict[str, Dict[str, Any]] = {}
    for stamp in pega.day_range(start, today):
        built = build_dailyexcel._pega_tab(stamp, template, history_index={})
        if built:
            fresh[stamp] = built
            print("  {}  {} units".format(stamp, len(built.get("rows") or [])),
                  file=sys.stderr)

    if not fresh:
        raise NoTab(
            "pega3 returned no MLT/HTT units for {} .. {}".format(start, today)
        )

    kept = [tab for tab in tabs
            if tab.get("day") and (tab["day"] < start or tab["day"] > today)]
    merged = kept + [fresh[stamp] for stamp in sorted(fresh)]
    merged.sort(key=lambda tab: tab.get("day") or "")

    bundle = {
        "schemaVersion": existing.get("schemaVersion") or 1,
        "generatedAt": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "source": existing.get("source") or {
            "workbook": "(pega3)",
            "url": build_dailyexcel.source_url(),
        },
        "tabs": merged,
        "crossref": existing.get("crossref") or {"matched": 0, "duts": 0},
        "links": existing.get("links") or {
            "jiraBase": links.jira_base() or None,
        },
        "warnings": list(existing.get("warnings") or []),
    }
    build_dailyexcel.write_bundle(bundle)
    print("Tracker now through {}".format(merged[-1]["day"]), file=sys.stderr)
    return bundle


def _has_verdict(tab: Dict[str, Any]) -> bool:
    slots = _station_slots(tab)
    for row in tab.get("rows") or []:
        for slot in slots.values():
            if _tone(row, slot.get("result")) in ("pass", "fail"):
                return True
    return False


def pick_tab(bundle: Dict[str, Any], day: Optional[str] = None
             ) -> Dict[str, Any]:
    """One tab. Default is the newest day that has a pass or fail.

    A trailing empty day — validation listed, no verdicts yet — is the usual
    state mid-morning. Reporting 0/n of that would hide the last real day.
    ``--day`` still selects an empty tab if you name it.
    """
    tabs = [tab for tab in bundle.get("tabs") or [] if tab.get("day")]
    if not tabs:
        raise NoTab("the daily tracker bundle has no day tabs")
    if day:
        for tab in tabs:
            if tab["day"] == day:
                return tab
        have = ", ".join(tab["day"] for tab in tabs[-8:])
        raise NoTab("no tab for {} (have {})".format(day, have))
    graded = [tab for tab in tabs if _has_verdict(tab)]
    return max(graded or tabs, key=lambda tab: tab["day"])


# --------------------------------------------------------------------- columns

def _station_slots(tab: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """result / fail / version column indexes per station, from the header."""
    columns = tab.get("columns") or []
    slots: Dict[str, Dict[str, Any]] = {}
    for index, column in enumerate(columns):
        station = column.get("station")
        title = column.get("title") or ""
        if not station or column.get("kind") == "version":
            continue
        if re.search(r"\bversion\b", title, re.I):
            continue
        fail_at = version_at = None
        for ahead in range(index + 1, len(columns)):
            other = columns[ahead]
            title = other.get("title") or ""
            if version_at is None and (
                    other.get("kind") == "version"
                    or re.search(r"\bversion\b", title, re.I)):
                version_at = ahead
            if build_errors.FAILURE_TITLE.search(title) and fail_at is None:
                fail_at = ahead
                break
        slots[station] = {
            "result": index,
            "fail": fail_at,
            "version": version_at,
            "sub": column.get("sub"),
            "label": stations.label_of(station),
        }
    return slots


def _jira_at(tab: Dict[str, Any]) -> Optional[int]:
    for index, column in enumerate(tab.get("columns") or []):
        if re.search(r"\bjira\b|\bnotes?\b", column.get("title") or "", re.I):
            return index
    return None


def _sn_at(tab: Dict[str, Any]) -> Optional[int]:
    for index, column in enumerate(tab.get("columns") or []):
        if column.get("key") == "B":
            return index
    return None


# --------------------------------------------------------------------- cells

def _cell(row: Sequence[Any], at: Optional[int]) -> Dict[str, Any]:
    if at is None or at >= len(row):
        return {}
    return row[at] or {}


def _tone(row: Sequence[Any], at: Optional[int]) -> Optional[str]:
    tone = _cell(row, at).get("t")
    return tone if tone in ("pass", "fail", "abort") else None


def _cases(row: Sequence[Any], at: Optional[int]) -> List[str]:
    return build_errors._cases(_cell(row, at))


def _notes(row: Sequence[Any], jira_at: Optional[int]
           ) -> Tuple[List[str], str]:
    """Jira keys and leftover prose from the notes column (or any cell)."""
    keys: List[str] = []
    prose = ""
    if jira_at is not None:
        cell = _cell(row, jira_at)
        prose = str(cell.get("v") or "")
        keys = list(cell.get("j") or [])
        if not keys:
            keys = build_dailyexcel.JIRA_KEY.findall(prose)
    else:
        for cell in row:
            if not isinstance(cell, dict):
                continue
            if cell.get("j"):
                keys.extend(cell["j"])
            elif cell.get("v"):
                found = build_dailyexcel.JIRA_KEY.findall(str(cell["v"]))
                if found:
                    keys.extend(found)
                    if not prose:
                        prose = str(cell["v"])
    leftover = build_dailyexcel.JIRA_KEY.sub("", prose)
    leftover = re.sub(r"^[\s:;,\u2014-]+|[\s:;,\u2014-]+$", "", leftover)
    leftover = re.sub(r"\s+", " ", leftover).strip(" :;,\u2014-")
    # Dedupe keys, keep order: a cell that repeats the same ticket is one link.
    seen = set()
    unique = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique, leftover


def _clean_prose(prose: str, cases: Sequence[str]) -> str:
    """Drop leftover notes that just repeat the failing test-case name.

    The sheet often stores ``ETCH-38719: SohuVrmTestCase``. After the key is
    stripped that is the case name again, and printing it twice is noise.
    """
    if not prose:
        return ""
    tokens = [part.strip() for part in re.split(r"[,;/]+", prose) if part.strip()]
    named = {name.lower() for name in cases}
    if tokens and all(token.lower() in named for token in tokens):
        return ""
    if prose.lower() in named:
        return ""
    return prose


_RELEASE_IN = re.compile(r"(\d{4})\.(\d+)\.")


def _release_token(text: Optional[str]) -> Optional[str]:
    """The floor's release number: ``257`` out of ``mlt_2026.257.0-git…``.

    Also works for ``mlt_validation_2026.247.0-git…``. The heading
    ``3 versions in this column`` is not a release — that case falls through
    so the per-row version column can answer.
    """
    if not text:
        return None
    raw = str(text)
    if re.search(r"\bversions?\s+in\s+this\s+column\b", raw, re.I):
        return None
    found = _RELEASE_IN.search(raw)
    return found.group(2) if found else None


def _station_release(rows: Sequence[Sequence[Any]], slot: Dict[str, Any]
                     ) -> Optional[str]:
    from_heading = _release_token(slot.get("sub"))
    if from_heading:
        return from_heading
    counted: Counter = Counter()
    for row in rows:
        counted[_release_token(_cell(row, slot.get("version")).get("v"))] += 1
    counted.pop(None, None)
    return counted.most_common(1)[0][0] if counted else None


# --------------------------------------------------------------------- refs

def _established() -> Dict[str, Dict[str, str]]:
    return build_errors.established()


def _knowledge_refs() -> Dict[str, str]:
    """test case -> Jira key, from the knowledge files that carry one.

    Only keys that are actually in a file. A case with no ticket stays
    without one; guessing ETCH-n from a neighbouring file is how a report
    sends people to the wrong issue.
    """
    folder = config.REPO_ROOT / "errors" / "knowledge"
    out: Dict[str, str] = {}
    if not folder.exists():
        return out
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        key = None
        for cause in data.get("rootCauses") or []:
            for action in cause.get("correctiveActions") or []:
                if action.get("ref"):
                    key = action["ref"]
                    break
            if key:
                break
            for evidence in cause.get("evidence") or []:
                match = build_dailyexcel.JIRA_KEY.search(
                    str(evidence.get("url") or ""))
                if match:
                    key = match.group(1)
                    break
            if key:
                break
        if not key:
            continue
        for case in (data.get("appliesTo") or {}).get("cases") or []:
            out.setdefault(case, key)
    return out


def jira_url(key: str) -> str:
    return "{}/{}".format(links.jira_base(), key)


def _ref_for(case: str, row_keys: Sequence[str],
             established: Dict[str, Dict[str, str]],
             knowledge: Dict[str, str]) -> Optional[str]:
    if row_keys:
        return row_keys[0]
    known = established.get(case) or {}
    if known.get("ref"):
        return known["ref"]
    return knowledge.get(case)


# --------------------------------------------------------------------- summarize

def _unit_rows(tab: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    sn_at = _sn_at(tab)
    rows = []
    for row in tab.get("rows") or []:
        serial = (_cell(row, sn_at).get("v") or "").strip()
        if not serial:
            continue
        rows.append(row)
    return rows


def summarize(
    tab: Dict[str, Any],
    product: Optional[str] = None,
    master_jira: Optional[str] = None,
    cohort_case: Optional[str] = None,
    tracker_url: Optional[str] = None,
    established: Optional[Dict[str, Dict[str, str]]] = None,
    knowledge: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Counts and failure groups for one tab — the data behind the markdown."""
    rows = _unit_rows(tab)
    slots = _station_slots(tab)
    jira_at = _jira_at(tab)
    known = established if established is not None else _established()
    refs = knowledge if knowledge is not None else _knowledge_refs()
    n_units = len(rows)

    mlt = slots.get("mlt") or {}
    htt = slots.get("htt") or {}
    both = 0
    for row in rows:
        if _tone(row, mlt.get("result")) == "pass" and \
                _tone(row, htt.get("result")) == "pass":
            both += 1

    stations_out = []
    for key in ("mlt", "htt"):
        slot = slots.get(key)
        if not slot:
            continue
        passed = failed = 0
        groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in rows:
            tone = _tone(row, slot["result"])
            if tone == "pass":
                passed += 1
                continue
            if tone != "fail":
                continue
            failed += 1
            cases = _cases(row, slot.get("fail"))
            first = cases[0] if cases else "unclassified failure"
            keys, prose = _notes(row, jira_at)
            prose = _clean_prose(prose, cases)
            kind = "note" if prose and NOTE_IS_FINDING.search(prose) else "case"
            label = prose if kind == "note" else first
            bucket = groups.setdefault(
                (kind, label, prose),
                {"kind": kind, "case": first, "prose": prose,
                 "units": 0, "keys": Counter()})
            bucket["units"] += 1
            for key_name in keys:
                bucket["keys"][key_name] += 1
            ref = _ref_for(first, keys, known, refs)
            if ref:
                bucket["keys"][ref] += 1

        bullets = []
        for (_kind, _label, _prose), bucket in sorted(
                groups.items(),
                key=lambda item: (
                    0 if (cohort_case and item[1]["kind"] == "case"
                          and item[1]["case"] == cohort_case) else 1,
                    -item[1]["units"],
                    item[0][1])):
            case = bucket["case"]
            top_key = bucket["keys"].most_common(1)
            bullets.append({
                "kind": bucket["kind"],
                "case": case,
                "prose": bucket["prose"],
                "units": bucket["units"],
                "jira": top_key[0][0] if top_key else None,
                "original": bool(cohort_case) and case == cohort_case
                            and bucket["kind"] == "case",
            })
        stations_out.append({
            "key": key,
            "label": slot["label"],
            "release": _station_release(rows, slot),
            "pass": passed,
            "fail": failed,
            "bullets": bullets,
        })

    return {
        "day": tab.get("day"),
        "label": (tab.get("label") or (tab.get("day") or "")[-5:]),
        "product": (product or os.environ.get(
            "FACTORY_REPORT_PRODUCT", "").strip() or DEFAULT_PRODUCT),
        "units": n_units,
        "claimed": tab.get("claimedUnits") or n_units,
        "passedBoth": both,
        "cohortCase": cohort_case or None,
        "stations": stations_out,
        "trackerUrl": tracker_url or "",
        "masterJira": master_jira or os.environ.get(
            "FACTORY_MASTER_JIRA", "").strip() or None,
    }


# --------------------------------------------------------------------- render

def _link(key: Optional[str]) -> str:
    return " " + jira_url(key) if key else ""


def _bullet_line(item: Dict[str, Any], total: int,
                 cohort: Optional[str]) -> str:
    n = item["units"]
    case = item["case"]
    prose = item["prose"]
    href = _link(item.get("jira"))
    if item["kind"] == "note" and prose:
        prefix = "{}x ".format(n) if n > 1 else ""
        return "{}{}{}".format(prefix, prose, href)
    if item.get("original"):
        return "Only {}/{} still failed on {}{}".format(n, total, case, href)
    if cohort and not item.get("original") and n == 1 and not prose:
        return "New symptom {} failure{}".format(case, href)
    count = "{}x ".format(n) if n > 1 else ""
    extra = " {}".format(prose) if prose else ""
    return "{}{}{}{}".format(count, case, extra, href)


def render(summary: Dict[str, Any]) -> str:
    """The markdown. Short, pasteable, no tables."""
    product = summary["product"]
    units = summary["units"]
    cohort = summary.get("cohortCase")
    if cohort:
        title = "{} Retest {}x {} failed unit".format(
            product, units, cohort)
    else:
        title = "{} {} {}x".format(product, summary["label"], units)

    lines = [
        title,
        "{}/{} passed MLT/HTT".format(summary["passedBoth"], units),
        "",
    ]
    for station in summary["stations"]:
        release = station.get("release") or "?"
        lines.append("{} {}: {}x PASS / {}x FAIL".format(
            station["label"], release, station["pass"], station["fail"]))
        for item in station["bullets"]:
            lines.append(_bullet_line(item, units, cohort))
        if station["key"] == "htt":
            continue
        lines.append("")
    tracker = summary.get("trackerUrl") or ""
    if tracker:
        lines.append("Test Tracker: {}".format(tracker))
    master = summary.get("masterJira")
    if master:
        key = build_dailyexcel.JIRA_KEY.search(master)
        lines.append("Master Jira: {}".format(
            jira_url(key.group(1)) if key else master))
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------- write

def default_path(day: str, directory: Optional[Path] = None) -> Path:
    root = directory or DEFAULT_DIR
    return root / "{}.md".format(day)


def generate(
    day: Optional[str] = None,
    bundle: Optional[Dict[str, Any]] = None,
    product: Optional[str] = None,
    master_jira: Optional[str] = None,
    cohort_case: Optional[str] = None,
    fetch: bool = True,
) -> Tuple[Dict[str, Any], str]:
    """Load, summarize, render. Returns (summary, markdown).

    ``fetch`` (the default) throws away recent pega3 listings and rebuilds
    those days before reading them. Pass ``False`` or ``--offline`` to use
    whatever is already on disk.
    """
    if bundle is not None:
        data = bundle
    elif fetch:
        data = refresh(day=day)
    else:
        data = load_bundle()
    tab = pick_tab(data, day)
    tracker = (data.get("source") or {}).get("url") or build_dailyexcel.source_url()
    summary = summarize(
        tab,
        product=product,
        master_jira=master_jira,
        cohort_case=cohort_case,
        tracker_url=tracker,
    )
    return summary, render(summary)


def write(markdown: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path
