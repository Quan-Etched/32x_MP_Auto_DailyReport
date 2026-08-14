"""One suite's validation run, and the units that actually went through it.

WHY THIS PAGE EXISTS
--------------------
Two people counted the mlt_2026.225 validation and got 24 and 39. Both were
right. Yi counted the units that went through
``mlt_validation_2026.225.0-gitb937ca2c``; the daily tracker counted every unit
that went through *any* MLT suite that day, because its column aggregates a
station and only its heading names a release. On a day when the line runs
production 220 and validation 225 side by side, that heading is misleading.

So this page takes a suite name and answers for that suite alone: which units,
which slots, what each one did, and whether it had been through this station
before. It also reconciles its own number against the day's other suites, so
the next person who sees two counts can see why in one place rather than
starting the comparison again.

WHAT IT IS NOT
--------------
Not a yield page. A validation run is a designed experiment — a chosen set of
units on a new build — and reading it as line yield would be a category error.
The interesting figures are the split between units that had failed before and
units that had not, which is what tells you whether a fix generalises.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import build_history, config, pega, version

#: The suite this page is about unless told otherwise.
DEFAULT_SUITE = "mlt_validation_2026.225.0-gitb937ca2c"

#: Which controller runs it. mlt/htt are pega3's.
DEFAULT_HOST = "pega3"


def collect(suite: str = DEFAULT_SUITE, host: str = DEFAULT_HOST,
            days: int = 30, history: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every unit that went through ``suite``, plus the day's other suites."""
    today = datetime.now(timezone.utc).date()
    window = [(today.toordinal() - offset) for offset in range(days - 1, -1, -1)]
    window = [datetime.fromordinal(day).strftime("%Y-%m-%d") for day in window]

    station_prefix = suite.split("_")[0]
    units: Dict[str, Dict[str, Any]] = {}
    siblings: Dict[str, Dict[str, Any]] = {}
    runs: List[Dict[str, Any]] = []
    days_seen = set()

    for day in window:
        try:
            listing = pega.day_suite_runs(day, host=host)
        except pega.PegaUnavailable:
            continue
        for entry in listing:
            name = entry.get("suite_name") or ""
            run_id = entry.get("suite_run_id") or ""
            if not run_id.startswith(station_prefix):
                continue
            mine = name == suite
            if not mine and not days_seen:
                # Sibling suites are only interesting on the days this one ran.
                continue
            try:
                detail = pega.suite_run(run_id, host=host)
            except pega.PegaUnavailable:
                continue
            parts = pega.participants(detail)

            if mine:
                days_seen.add(day)
                runs.append({
                    "runId": run_id,
                    "short": run_id.rsplit("_run_", 1)[-1],
                    "day": day,
                    "startedAt": entry.get("start_time"),
                    "station": entry.get("station_id"),
                    "slots": len(parts),
                    "url": pega.run_url(run_id, None, host=host),
                })
                for part in parts:
                    units[part["dut"]] = {
                        "dut": part["dut"],
                        "slot": part["slot"],
                        "status": part["status"],
                        "failures": _failures(detail, part["slot"]),
                        "run": run_id.rsplit("_run_", 1)[-1],
                        "url": pega.run_url(run_id, part["slot"], host=host),
                        "day": day,
                        "partNumber": entry.get("dut_part_number"),
                    }
            else:
                bucket = siblings.setdefault(name, {"units": set(), "runs": 0})
                bucket["runs"] += 1
                for part in parts:
                    bucket["units"].add(part["dut"])

    # Only keep siblings from the days this suite actually ran on.
    sibling_rows = [
        {"suite": name, "runs": data["runs"], "units": len(data["units"]),
         "overlap": len(data["units"] & set(units)),
         "only": sorted(data["units"] - set(units))[:40]}
        for name, data in sorted(siblings.items())
    ]

    everyone = set(units)
    for data in siblings.values():
        everyone |= data["units"]

    return {
        "suite": suite,
        "host": host,
        "days": sorted(days_seen),
        "runs": runs,
        "units": units,
        "siblings": sibling_rows,
        "dayTotal": len(everyone),
    }


def _failures(detail: Dict[str, Any], slot: Optional[int]) -> List[str]:
    from . import build_dailyexcel

    text = build_dailyexcel._unit_failures(detail, slot)
    return [name for name in text.split("\n") if name]


def build_bundle(payload: Dict[str, Any], collected: Dict[str, Any]) -> Dict[str, Any]:
    """Join the suite's units to their history, so new vs retest is visible."""
    history = build_history.build_bundle(payload, days=90)
    # Everything the unit did *before* this suite ran, keyed by serial.
    prior: Dict[str, List[Dict[str, Any]]] = {}
    for row in sorted(history["rows"], key=lambda r: r["ts"] or 0):
        if row["station"] != "mlt" and not row["station"].startswith(
                collected["suite"].split("_")[0]):
            continue
        prior.setdefault(row["dut"], []).append(row)

    # "Before" means before *this build*, and the build is the commit, not the
    # suite name. On 08-14 the same sixteen units ran the 225 commit twice under
    # two names — mlt_2026.225.0-gitb937ca2c at 08:23 and
    # mlt_validation_2026.225.0-gitb937ca2c at 10:03 — so matching on the name
    # would call every one of them a retest of itself and report 0 new builds,
    # which is the opposite of what the page is read for. Matching on the commit
    # treats both names as the one validation event and leaves prior history
    # meaning what it says.
    #
    # Excluding by *day* instead would be wrong in the other direction: a unit
    # that ran the production suite in the morning and the validation build in
    # the afternoon is a retest, and the day rule would hide that.
    suite = collected["suite"]
    build = _build_token(suite)
    rows = []
    for dut, unit in collected["units"].items():
        earlier = [row for row in prior.get(dut, [])
                   if not _same_build(row.get("suite"), suite, build)]
        failed_before = [name for row in earlier for name in row["failures"]]
        rows.append(dict(unit, **{
            "priorRuns": len(earlier),
            "isNew": not earlier,
            "priorFailures": _distinct(failed_before),
            "priorStatus": earlier[-1]["status"] if earlier else None,
        }))

    rows.sort(key=lambda row: (row["status"] != "fail", row["isNew"], row["dut"]))

    new = [row for row in rows if row["isNew"]]
    seen = [row for row in rows if not row["isNew"]]
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "suite": collected["suite"],
        "host": collected["host"],
        "days": collected["days"],
        "runs": collected["runs"],
        "rows": rows,
        "counts": {
            "units": len(rows),
            "passed": sum(1 for row in rows if row["status"] == "pass"),
            "failed": sum(1 for row in rows if row["status"] == "fail"),
            "new": {"units": len(new),
                    "passed": sum(1 for row in new if row["status"] == "pass")},
            "seen": {"units": len(seen),
                     "passed": sum(1 for row in seen if row["status"] == "pass")},
        },
        # The reconciliation: this suite against everything else the station ran
        # on the same days. It is the whole reason two people got two numbers.
        "reconcile": {
            "dayTotal": collected["dayTotal"],
            "siblings": collected["siblings"],
        },
    }


#: The commit a suite was built from: ``mlt_validation_2026.225.0-gitb937ca2c``
#: and ``mlt_2026.225.0-gitb937ca2c`` are two names for one build.
BUILD_TOKEN = re.compile(r"git[0-9a-f]{6,}")


def _build_token(suite: str) -> Optional[str]:
    found = BUILD_TOKEN.search(suite or "")
    return found.group(0) if found else None


def _same_build(candidate: Optional[str], suite: str, build: Optional[str]) -> bool:
    """Is this earlier run part of the same validation event?

    By commit when the names carry one, by exact name when they do not — a
    suite with no commit stamp is matched conservatively rather than guessed at.
    """
    name = candidate or ""
    if build:
        return build in name
    return name == suite


def _distinct(names: List[str]) -> List[str]:
    out: List[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return out


def write_bundle(bundle: Dict[str, Any], path: Optional[Path] = None) -> Path:
    target = path or (config.DASHBOARD_DATA_DIR / "validation.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bundle, separators=(",", ":"), default=str)
    target.write_text(
        "// Generated by `python -m factory.cli validation` — do not edit.\n"
        "window.__FACTORY_VALIDATION__ = {};\n".format(body),
        encoding="utf-8",
    )
    return target
