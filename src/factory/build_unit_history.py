"""A board's history from before the collected window — and only from there.

WHAT THIS IS FOR
----------------
Search a serial on customize.html and you get everything the controllers ever
saw for it. "Ever" meant "since 2026-08-01": the runs bundle is collected from
:data:`pega.CONTROLLER_FROM`, which is the line's reporting horizon, and a
board first tested in July arrived on that page looking new.

Asked for by Chris on 2026-09-07, in his words: *is there a way to extend the
re-test history for boards all the way to the start, when they first got
tested?* The daily tracker's answer landed the next day — its new-input flag
and Test History strip read from :data:`pega.HISTORY_FROM` — but the serial
search reads the runs bundle, so it still stopped at August. Measured against
the published bundle on 09-08: 268086800000021, 268086800000015 and
268108570000002 each had two runs in it, both dated 09-07, and four months of
MLT history between them that the page could not show.

WHY NOT JUST COLLECT FURTHER BACK
---------------------------------
Because the runs bundle is not only the serial search. Widen the collector and
every station yield, every chart and every day tab silently gains June and July
— bring-up runs, in the same shape as production ones, moving numbers the line
reviews. That is the change that was made on 2026-09-02 and withdrawn on 09-03.
The heavy bundle is also 6.6 MB for five weeks and fetched on demand; four more
months of it, test names and all, is a page nobody wants to open.

So the window that gets *reported on* stays where the line put it, and this
carries the part that window cannot see.

THE SHAPE, AND WHY THERE IS NO OVERLAP
--------------------------------------
Strictly before ``window.from``. Every attempt from that day onward is already
in the runs bundle, with its duration, its per-test detail and its failure
names; anything here would be a second, thinner copy of a row the page already
has, and the page would have to choose. Ending this file where the other one
starts means the two are joined rather than merged — no duplicates, no
tie-break, and one honest sentence on the page about which side of the join a
row came from.

WHAT IS IN A ROW, AND WHAT IS NOT
---------------------------------
Day, timestamp, verdict, suite, and the link to the run. Not the duration and
not the failed test cases: those live in the run *detail*, one fetch per run,
and interning four months of June/July test names is how a 90 KB file becomes
a 6 MB one. The page says so rather than leaving blank columns to be read as
"no failures".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import (build_dailyexcel, build_l10, build_l11, config, pega,
               pega_collect, stations)

#: The three indices, each with the controller that serves its links. Same
#: readers the daily tracker uses — a second way to turn a listing into a
#: unit's attempts would be a second answer to "what has this board done".
SOURCES = (
    ("pega3", build_dailyexcel.module_index),
    ("pega4", build_l10.stage_index),
    ("pega5", build_l11.stage_index),
)

#: How a station is named here: the name the runs bundle uses, so the two
#: halves of a card join instead of sitting side by side as different stages.
#:
#: The module index already keys by station ("mlt", "htt") and passes straight
#: through. L10 and L11 key by stage, and the translation is
#: ``pega_collect.STAGE_STATIONS`` — the same table the collector itself uses,
#: not a copy of it.
#:
#: WHY NOT ASK ``station_of`` WITH THE SUITE NAME, which would need no table at
#: all: because it classifies the *suite string*, and July's HTT runs were
#: named htt_20260724 rather than htt_2026.205.0-git…. That misses the version
#: pattern, classifies as nothing, and silently drops every July HTT attempt —
#: which is precisely the history this file exists to carry. The index has
#: already decided which station an attempt belongs to, using the reader the
#: daily tracker's strips use; re-deciding it from a string is a second opinion
#: nobody asked for.
def station_key(host: str, index_key: str) -> str:
    return pega_collect.STAGE_STATIONS.get(host, {}).get(index_key, index_key)


def build_bundle(history_from: Optional[str] = None,
                 window_from: Optional[str] = None) -> Dict[str, Any]:
    """Every attempt on record before ``window_from``, keyed by serial.

    Defaults are the two floors themselves, which is the only combination that
    makes the join exact: this file ends the day before the runs bundle starts.
    """
    first = history_from or pega.HISTORY_FROM
    start = window_from or pega.CONTROLLER_FROM
    last = _day_before(start)

    labels = {entry["key"]: entry.get("label", entry["key"])
              for entry in stations.registry()}
    units: Dict[str, Dict[str, List[List[Any]]]] = {}
    controllers: Dict[str, str] = {}
    attempts = 0

    for host, reader in SOURCES:
        if last < first:
            break
        try:
            index = reader(first, last)
        except Exception:                                 # noqa: BLE001
            # A controller that cannot be reached is a gap in the history, not
            # a failed build: the page says how far back it reaches and this
            # one contributes nothing to it.
            continue
        for index_key, duts in index.items():
            key = station_key(host, index_key)
            for dut, got in duts.items():
                for attempt in got:
                    if attempt["day"] >= start:
                        continue          # the runs bundle owns this one
                    controllers.setdefault(key, host)
                    rows = units.setdefault(dut, {}).setdefault(key, [])
                    rows.append([
                        attempt["day"],
                        attempt.get("startTs"),
                        attempt["status"],
                        attempt.get("runId") or "",
                        attempt.get("slot"),
                        attempt.get("suite") or "",
                    ])
                    attempts += 1

    for stations_of in units.values():
        for rows in stations_of.values():
            rows.sort(key=lambda row: (row[1] or 0, row[0]))

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        # What the page needs to say where its two halves join, and how far
        # back the earlier one reaches. Printed rather than implied: "every run
        # we have" is a claim, and this is the evidence for it.
        "historyFrom": first,
        "window": {"from": start},
        # Only the fields a row here can honestly fill. The page reads this as
        # its licence to leave the other columns empty and say why.
        "fields": ["day", "startTs", "status", "runId", "slot", "suite"],
        "stationLabels": {key: labels.get(key, key) for key in controllers},
        "controllers": controllers,
        "units": units,
        "counts": {"units": len(units), "attempts": attempts},
    }


def _day_before(day: str) -> str:
    """The day before ``day``. Where this file has to stop."""
    at = datetime.strptime(day, "%Y-%m-%d").date() - timedelta(days=1)
    return at.strftime("%Y-%m-%d")


def write_bundle(bundle: Dict[str, Any],
                 path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "unit_history.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "window.__FACTORY_UNIT_HISTORY__ = {};\n".format(body),
        encoding="utf-8")
    return target
