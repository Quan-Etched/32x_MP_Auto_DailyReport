"""Pack a week out, so a later week has something to compare against.

WHY THIS EXISTS
---------------
``fpy.html`` always shows the current seven days. That is the right thing for a
dashboard and the wrong thing for a trend: on 22 August the page will have
quietly replaced the numbers this Monday's meeting was run on, and the question
"is MLT better than last week" will have nothing to answer from. The
controllers keep 30 days of detail and then it is gone.

So each week is written to disk under ``weekly/<date>/``: the bundle exactly as
it was rendered, a readable summary next to it, and the deck if one was built.
Committed to the repo, because the point is to still have it in three months.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
No trend is computed here. Two weeks of a line in bring-up is not a trend, and
a chart that draws one would be read as though it were. The archive is the raw
material; the comparison waits until there is enough of it to mean something.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

ARCHIVE_DIR = config.REPO_ROOT / "weekly"

#: Where the live bundle is written by `factory.cli fpy`.
BUNDLE = config.DASHBOARD_DATA_DIR / "fpy.js"

#: The weekly tracker's bundle, which is what names the week.
WEEKLY = config.DASHBOARD_DATA_DIR / "weekly.js"


def _load(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    body = text.split("= ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


def pick_week(weeks: List[Dict[str, Any]], label: Optional[str] = None,
              current: bool = False) -> Dict[str, Any]:
    """Which week to archive.

    The default is the newest week that has **ended**, and that default is
    load-bearing: the snapshot runs Sunday night Pacific, which is Monday
    morning UTC, so "the current week" at that moment is a brand-new empty one.
    Archiving weeks[0] there would have stored an empty week over the one
    everybody was about to discuss.
    """
    if label:
        for week in weeks:
            if week["week"] == label:
                return week
        raise FileNotFoundError("no week {} in the bundle".format(label))
    if current:
        return weeks[0]
    for week in weeks:
        if not week.get("partial"):
            return week
    # Nothing has finished yet — a first run in a fresh deployment.
    return weeks[0]


def archive(label: Optional[str] = None, bundle: Optional[Path] = None,
            root: Optional[Path] = None, current: bool = False) -> List[Path]:
    """Write one week to ``weekly/<ISO week>/`` and return the paths.

    Sourced from the weekly bundle rather than the rolling one, so the folder,
    the deck and the page's own address all describe the same Monday-to-Sunday
    week. An archive that disagreed with the page it was archiving would be
    worse than no archive.
    """
    source = bundle or WEEKLY
    if not source.exists():
        raise FileNotFoundError(
            "{} — run `make weekly` first".format(source))

    data = _load(source)
    weeks = data.get("weeks") or []
    if not weeks:
        raise FileNotFoundError("{} holds no weeks".format(source))

    week = pick_week(weeks, label=label, current=current)
    name = week["week"]
    target = (root or ARCHIVE_DIR) / name
    target.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []

    # The week, plus the context needed to read it a quarter from now: what the
    # cohort floor was, which stage was excluded, where the numbers came from.
    stored = dict(week, context={
        "minCohort": data.get("minCohort"),
        "excluded": data.get("excluded"),
        "historyDays": data.get("historyDays"),
        "source": data.get("source"),
        "build": data.get("build"),
        "generatedAt": data.get("generatedAt"),
    })
    payload = target / "week.json"
    payload.write_text(json.dumps(stored, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
    written.append(payload)

    readme = target / "summary.md"
    readme.write_text(summarise(stored), encoding="utf-8")
    written.append(readme)

    # A standalone page, so an archived week opens in a browser on its own —
    # no dashboard, no server, no data bundle. The live page will have moved
    # on to another week and eventually drop this one's unit rows entirely;
    # this file is the copy that still works in November.
    page = target / "week.html"
    page.write_text(render_html(stored), encoding="utf-8")
    written.append(page)

    # The deck, if one was built for this week. Matched on the window's end
    # date, which is why the deck is named for the data it shows rather than
    # for the day it gets presented — a file named for the meeting cannot be
    # matched to the week it describes. Copied rather than linked so the
    # folder is self-contained when someone opens it a quarter from now.
    for deck in sorted((config.REPO_ROOT / "decks").glob("*{}*.pptx".format(name))):
        copy = target / deck.name
        shutil.copyfile(deck, copy)
        written.append(copy)

    return written


def _current_week() -> Optional[str]:
    if not WEEKLY.exists():
        return None
    try:
        weeks = _load(WEEKLY).get("weeks") or []
    except (OSError, ValueError, IndexError):
        return None
    return weeks[0]["week"] if weeks else None


def _thin_volumes(step: Dict[str, Any]) -> str:
    """One thin stage, as both of its counts.

    Two numbers because the sentence around it is about first-time units and
    the number people quote is the week's traffic: "MLT (10 first-time of 90
    units)" cannot be misread, and "MLT (90 units)" was.
    """
    if step.get("newUnits") is None:            # an older archive
        return "{} ({} unit{})".format(
            step["label"], step["units"], "" if step["units"] == 1 else "s")
    return "{} ({} first-time of {} unit{})".format(
        step["label"], step["newUnits"], step["units"],
        "" if step["units"] == 1 else "s")


def summarise(week: Dict[str, Any]) -> str:
    """The week as prose and one table — readable without the dashboard."""
    context = week.get("context") or {}
    totals = week.get("totals") or {}
    rows = week.get("rows") or []
    external = week.get("external") or []

    def pct(value: Optional[float]) -> str:
        return "—" if value is None else "{:.1f}%".format(value * 100)

    lines = [
        "# {} — first-pass yield, {} to {}{}".format(
            week.get("week"), week.get("from"), week.get("endsOn"),
            " (week still running when archived)" if week.get("partial") else ""),
        "",
        "Archived from `dashboard/data/weekly.js` on {}. Live page: "
        "`week.html#week={}`.".format(
            datetime.now(timezone.utc).strftime("%Y-%m-%d"), week.get("week")),
        "",
        # Marked where it is thin, because this file is quoted from months
        # later and the mark is the only thing travelling with the number.
        "Rolled first-pass across {}: **{}**{}.".format(
            " x ".join(totals.get("rolledOver") or []) or "no stage",
            pct(totals.get("rolledFpy")),
            " (thin: {})".format(", ".join(
                "{} over {} first-time units".format(step["label"],
                                                     step.get("newUnits"))
                for step in totals.get("rolledThin") or []))
            if (totals.get("rolledFpy") is not None
                and totals.get("rolledThin")) else ""),
        "",
        "| Step | Units | Runs | First pass | After retest | Retest rate | Top failure |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for item in external:
        lines.append("| {} *(reported {})* | — | — | {} | — | — | {} |".format(
            item.get("label"), item.get("asOf"), pct(item.get("yield")),
            item.get("source", "")))

    for row in rows:
        top = (row.get("topFailures") or [{}])[0].get("name", "")
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            row["label"], row["units"], row["runs"], pct(row.get("fpy")),
            pct(row.get("finalYield")), pct(row.get("retestRatio")), top))

    thin = totals.get("excludedThin") or []
    if thin:
        lines += [
            "",
            "Excluded from the rolled figure — fewer than {} first-time units, "
            "which is too few to read a yield from: {}.".format(
                context.get("minCohort"),
                # The first-time count, not the week's traffic. It printed
                # `units` under a sentence about first-time units, so a thin
                # MLT read as "MLT (90 units)" — a line that argues with
                # itself, and the reader believes the number.
                ", ".join(_thin_volumes(t) for t in thin)),
        ]

    source = context.get("source") or {}
    lines += [
        "",
        "## Sources",
        "",
        "- Measured rows: {}. One row per unit, not one per fixture.".format(
            source.get("label", "the station controllers")),
        "- Attempts numbered over {} days of history, so a unit returning this "
        "week counts as a retest rather than a first pass.".format(
            context.get("historyDays")),
        "- Reported rows are hand-entered; the source and date are on the row.",
        "- Excluded from this view: {}.".format(
            ", ".join(context.get("excluded") or []) or "nothing"),
        "- {} unit-level rows kept with this week.".format(len(week.get("units") or [])),
        "- Built from commit {}.".format(
            (context.get("build") or {}).get("commit", "unknown")),
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------- standalone

#: Inline, because the point of this file is that it works with nothing else
#: around it. Light-only for the same reason: an archived record should look
#: the same to everyone who opens it.
_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 30px 26px 60px; background: #f9f9f7; color: #141414;
       font: 14px/1.55 -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }
.wrap { max-width: 1180px; margin: 0 auto; }
h1 { font-size: 25px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 32px 0 8px; }
.sub { color: #6b6b6b; margin: 0 0 18px; }
.archived { display: inline-block; padding: 2px 9px; border: 1px dashed #a09e97;
            border-radius: 4px; font-size: 11px; color: #6b6b6b; margin-left: 8px;
            vertical-align: middle; }
.tiles { display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0 8px; }
.tile { flex: 1 1 210px; border: 1px solid #e1e0d9; border-radius: 9px;
        padding: 13px 15px; background: #fcfcfb; }
.tile .k { display: block; font-size: 12px; color: #6b6b6b; }
.tile .v { display: block; font-size: 28px; margin: 3px 0 2px;
           font-variant-numeric: tabular-nums; }
.tile .s { display: block; font-size: 12px; color: #52514e; }
.tile.lead { border-color: #1c62b8; } .tile.lead .v { color: #1c62b8; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
caption { text-align: left; color: #52514e; padding: 8px 0; }
th { text-align: left; font-size: 12px; padding: 7px 9px; border-bottom: 1px solid #e1e0d9; }
td { padding: 6px 9px; border-bottom: 1px solid #eeede7; vertical-align: top; }
th.n, td.n { text-align: right; font-variant-numeric: tabular-nums; }
.step { font-weight: 600; }
.small { display: block; font-size: 10.5px; color: #898781; font-weight: 400; }
tr.thin td { color: #898781; }
.y { font-size: 15px; font-weight: 650; }
.good { color: #006300; } .warn { color: #8a5200; } .bad { color: #a3271d; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; }
.res { font-weight: 600; text-transform: capitalize; }
.r-pass { color: #006300; } .r-fail, .r-error { color: #a3271d; }
.reported::after { content: 'reported'; margin-left: 7px; padding: 1px 6px;
  border: 1px dashed #a09e97; border-radius: 3px; font-size: 10px; color: #6b6b6b; }
.notes { margin-top: 28px; font-size: 12px; color: #6b6b6b; line-height: 1.65; }
.scroll { overflow-x: auto; }
"""


def _pct(value: Optional[float]) -> str:
    return "&mdash;" if value is None else "{:.1f}%".format(value * 100)


def _tone(value: Optional[float]) -> str:
    if value is None:
        return ""
    return "good" if value >= 0.9 else "warn" if value >= 0.6 else "bad"


def _esc(text: Any) -> str:
    return (str(text if text is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_html(week: Dict[str, Any]) -> str:
    """The archived week as one self-contained page."""
    context = week.get("context") or {}
    totals = week.get("totals") or {}
    floor = context.get("minCohort")

    # What the dash is waiting for, where there is a dash: the stages in scope
    # and the first-time counts they came up short on. "Enough units" named the
    # wrong denominator — a step can run ninety units and have ten it has never
    # seen, which is exactly how 2026-W36 lost its headline.
    thin_scope = totals.get("rolledThin") or []
    missing = totals.get("rolledMissing") or []
    scope = " &times; ".join(totals.get("rolledOver") or [])
    thin_note = " &middot; ".join(
        "{} {} new of {}".format(step["label"], step.get("newUnits"),
                                 step["units"])
        for step in thin_scope)

    if totals.get("rolledFpy") is None:
        # No product: which half was absent, or an archive too old to say.
        sub = ("no {} first-pass cohort this week &mdash; one station is not a "
               "product of two".format(" or ".join(missing)) if missing
               else "no step in the product had a first-pass cohort")
    elif thin_note:
        # Published thin, the way a thin step's own yield is.
        sub = "{} &middot; thin: {} &mdash; under {}".format(
            scope, thin_note, floor)
    else:
        sub = scope

    tiles = [
        ("Rolled first-pass",
         _pct(totals.get("rolledFpy")) + (" *" if thin_note else ""),
         sub, "lead"),
        ("Units tested",
         str(sum(row.get("units") or 0 for row in week.get("rows") or [])),
         "{} steps &middot; {} unit runs".format(
             len(week.get("rows") or []), len(week.get("units") or [])), ""),
        ("Week", "{} &ndash; {}".format(week.get("from"), week.get("endsOn")),
         "still running when archived" if week.get("partial")
         else "Monday to Sunday, complete", ""),
    ]

    steps = []
    for item in week.get("external") or []:
        steps.append(
            "<tr><td><span class='step reported'>{}</span>"
            "<span class='small'>{}</span></td>"
            "<td class='n'>&mdash;</td><td class='n'>&mdash;</td>"
            "<td class='n y {}'>{}</td><td class='n'>&mdash;</td>"
            "<td class='n'>&mdash;</td><td class='small'>as of {}</td></tr>".format(
                _esc(item.get("label")), _esc(item.get("source")),
                _tone(item.get("yield")), _pct(item.get("yield")),
                _esc(item.get("asOf"))))

    for row in week.get("rows") or []:
        readable = row.get("readable")
        fails = "<br>".join(
            "{} &times;{}".format(_esc(f.get("name")), _esc(f.get("runs")))
            for f in (row.get("topFailures") or [])[:3]) or "&mdash;"
        steps.append(
            "<tr class='{}'><td><span class='step'>{}</span>"
            "<span class='small'>{}{}</span></td>"
            "<td class='n'>{}</td><td class='n'>{}</td>"
            "<td class='n y {}'>{}<span class='small'>{} new</span></td>"
            "<td class='n'>{}</td>"
            "<td class='n'>{}<span class='small'>{}</span></td>"
            "<td class='small'>{}</td></tr>".format(
                "" if readable else "thin",
                _esc(row.get("label")), _esc(row.get("controller") or ""),
                "" if readable else
                (" &middot; quantity only, in bring-up" if row.get("countsOnly")
                 # The yield beside this prints, and has since L10 and L11
                 # asked for theirs. What is true of a thin step is that its
                 # yield is over too few first-time units to roll.
                 else " &middot; under {} first-time units, not rolled".format(
                     floor)),
                _esc(row.get("units")), _esc(row.get("runs")),
                _tone(row.get("fpy")) if readable else "", _pct(row.get("fpy")),
                row.get("newUnits"),
                _pct(row.get("finalYield")),
                _pct(row.get("retestRatio")),
                "{} of {} units re-run".format(row.get("retestUnits"),
                                               row.get("units"))
                if row.get("retestUnits") is not None
                else _esc(row.get("retestNote") or ""),
                fails))

    units = []
    for row in week.get("units") or []:
        link = ("<a href='{0}'>{1} &#8599;</a>".format(
                    _esc(row.get("url")), _esc(row.get("controller")))
                if row.get("url") else "&mdash;")
        # .get() throughout: this runs unattended from a timer, and one row
        # missing a field must not cost the whole week its archive.
        status = row.get("status") or "unknown"
        units.append(
            "<tr><td>{}</td><td>{}</td><td class='mono'>{}</td>"
            "<td class='mono'>{}</td><td class='n'>{}</td>"
            "<td class='res r-{}'>{}</td><td class='small'>{}</td>"
            "<td>{}</td></tr>".format(
                _esc(row.get("day")), _esc(row.get("station")),
                _esc(row.get("dut")),
                _esc(row.get("release")), _esc(row.get("attempt")),
                _esc(status), _esc(status),
                "<br>".join(_esc(f) for f in (row.get("failures") or [])),
                link))

    source = (context.get("source") or {}).get("label", "the station controllers")

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{week} &mdash; first-pass yield</title>
<style>{css}</style></head><body><div class="wrap">
<h1>{week}<span class="archived">archived {stamp}</span></h1>
<p class="sub">{start} to {ends}{partial} &middot; first-pass yield by test step,
and every unit run behind it. Self-contained: this file needs nothing else.</p>
<div class="tiles">{tiles}</div>
<h2>Every step</h2>
<div class="scroll"><table>
<caption>First-pass yield is over the units new to that step, the count under it.
Steps with fewer than {floor} of them publish the yield, marked thin, and stay out
of the rolled figure &mdash; a yield over three chassis is not a yield.</caption>
<thead><tr><th>Test step</th><th class="n">Units</th><th class="n">Runs</th>
<th class="n">First-pass yield</th><th class="n">After retest</th>
<th class="n">Retest rate</th><th>Top failures</th></tr></thead>
<tbody>{steps}</tbody></table></div>
<h2>Source data &mdash; every unit run this week</h2>
<div class="scroll"><table>
<caption>{nunits} rows, oldest first. Links point at the controller that ran it;
they resolve on the factory network and may have aged out.</caption>
<thead><tr><th>Date</th><th>Test step</th><th>DUT SN</th>
<th>Software release</th><th class="n">Attempt</th><th>Result</th>
<th>Failed test cases</th><th>Source</th></tr></thead>
<tbody>{units}</tbody></table></div>
<p class="notes">Source: {source} &mdash; one row per unit, not one per fixture.
Attempts numbered over {history} days of history, so a unit returning during the
week counts as a retest rather than a first pass. Excluded from this view:
{excluded}. WST and FT are Sigurd's and are reported by hand. Built from commit
{commit}.</p>
</div></body></html>
""".format(
        week=_esc(week.get("week")), css=_CSS,
        stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        start=_esc(week.get("from")), ends=_esc(week.get("endsOn")),
        partial=" (still running when archived)" if week.get("partial") else "",
        tiles="".join(
            "<div class='tile {}'><span class='k'>{}</span>"
            "<span class='v'>{}</span><span class='s'>{}</span></div>".format(
                extra, label, value, sub)
            for label, value, sub, extra in tiles),
        floor=floor, steps="".join(steps),
        nunits=len(week.get("units") or []), units="".join(units),
        source=_esc(source), history=context.get("historyDays"),
        excluded=", ".join(context.get("excluded") or []) or "nothing",
        commit=_esc((context.get("build") or {}).get("commit", "unknown")))
