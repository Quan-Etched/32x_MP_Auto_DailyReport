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


def _load(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    body = text.split("= ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)


def archive(label: Optional[str] = None, bundle: Optional[Path] = None,
            root: Optional[Path] = None) -> List[Path]:
    """Write this week's summary to ``weekly/<label>/`` and return the paths."""
    source = bundle or BUNDLE
    if not source.exists():
        raise FileNotFoundError(
            "{} — run `make fpy` first".format(source))

    data = _load(source)
    window = data.get("window") or {}
    name = label or window.get("to") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target = (root or ARCHIVE_DIR) / name
    target.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []

    payload = target / "fpy.json"
    payload.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
    written.append(payload)

    readme = target / "summary.md"
    readme.write_text(summarise(data), encoding="utf-8")
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


def summarise(data: Dict[str, Any]) -> str:
    """The week as prose and one table — readable without the dashboard."""
    window = data.get("window") or {}
    totals = data.get("totals") or {}
    rows = data.get("rows") or []
    external = data.get("external") or []

    def pct(value: Optional[float]) -> str:
        return "—" if value is None else "{:.1f}%".format(value * 100)

    lines = [
        "# First-pass yield, {} to {}".format(window.get("from"), window.get("to")),
        "",
        "Archived from `dashboard/data/fpy.js` on {}.".format(
            datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        "",
        "Rolled first-pass across {}: **{}**.".format(
            " x ".join(totals.get("rolledOver") or []) or "no stage",
            pct(totals.get("rolledFpy"))),
        "",
        "| Step | Units | Runs | First pass | After retest | Retest load | Top failure |",
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
                totals.get("minCohort"),
                ", ".join("{} ({} unit{})".format(
                t["label"], t["units"], "" if t["units"] == 1 else "s")
                for t in thin)),
        ]

    source = data.get("source") or {}
    lines += [
        "",
        "## Sources",
        "",
        "- Measured rows: {}. One row per unit, not one per fixture.".format(
            source.get("label", "the station controllers")),
        "- Attempts numbered over {} days of history, so a unit returning this "
        "week counts as a retest rather than a first pass.".format(
            data.get("historyDays")),
        "- Reported rows are hand-entered; the source and date are on the row.",
        "- Built from commit {}.".format(
            (data.get("build") or {}).get("commit", "unknown")),
        "",
    ]
    return "\n".join(lines)
