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


def archive(label: Optional[str] = None, bundle: Optional[Path] = None,
            root: Optional[Path] = None) -> List[Path]:
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

    week = weeks[0]
    if label:
        week = next((w for w in weeks if w["week"] == label), None)
        if week is None:
            raise FileNotFoundError("no week {} in {}".format(label, source))

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
        "Rolled first-pass across {}: **{}**.".format(
            " x ".join(totals.get("rolledOver") or []) or "no stage",
            pct(totals.get("rolledFpy"))),
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
                ", ".join("{} ({} unit{})".format(
                t["label"], t["units"], "" if t["units"] == 1 else "s")
                for t in thin)),
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
