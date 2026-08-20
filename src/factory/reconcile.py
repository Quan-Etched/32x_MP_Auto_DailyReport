"""The two sources against each other, run by run, for one day.

WHY RUN BY RUN
--------------
``compare.py`` already states the gap between the two station pages as a pass
rate per station, which is the right shape for "can I trust this number". It
cannot answer the next question — *which* runs one source has and the other does
not — and that is the question that gets asked as soon as the rates disagree.

So this joins the two collected payloads for a single day and says, per station,
what each side holds and which units are on one side only.

THE TRAP THIS MODULE EXISTS TO AVOID
------------------------------------
EOS records **one run per fixture**: one ``dutSerial``, no slot, one verdict for
eight chips. The controllers record **one result per unit**. Join those on the
serial and seven of every eight units come out "missing from OCP" — which is not
a fault, it is the schema, and a report that says it anyway is worse than no
report because it buries the real gaps in noise.

Every difference is therefore classified, and only one class is a fault:

``station-absent``
    The day has controller runs for this station and OCP has *none at all*. No
    schema difference explains this: the runs happened and the API does not have
    them. On 2026-08-20 this is every MLT unit on the line.
``fixture-not-unit``
    OCP has a run for the same station and release inside the same window, but
    not this unit's serial. Expected: it is the fixture row standing in for the
    eight units under it. Reported so the count is auditable, never as a fault.
``run-absent``
    OCP has runs for this station that day, but none that lines up with this
    unit's — not by serial, and not by release inside the window. A real gap,
    and the one worth chasing after ``station-absent``.

BOTH DIRECTIONS
---------------
The other side drops data too, and a report that only looks one way would keep
saying so. On 08-12 and 08-13 OCP held roughly twice the MLT units the
controllers did; on 08-20 it held none. So the summary counts both directions
and the CSV can be written for either — asking only "what did OCP miss" of a
day where the controllers are the thin one would produce a clean bill of health
and a wrong conclusion.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config, stations, version

#: How far apart two records of the same work may sit and still be the same
#: work. EOS stamps a run when it is filed and a controller when the slot
#: started; the pair that prompted this number were 11 seconds apart, and a
#: fixture run lasts long enough that a whole hour is still unambiguous within
#: one station and release.
WINDOW_SEC = 3600

#: The compact keys the published run bundles use. Spelt out once here because
#: reading ``r["d"]`` at the point of use is how a join gets written against the
#: wrong field.
FIELD = {
    "id": "i", "serial": "d", "station": "k", "level": "l",
    "suite": "su", "version": "v", "release": "r", "day": "day",
    "start": "t", "status": "s",
}

#: Buckets that are not a station, and not a gap worth reporting.
SKIP_STATIONS = ("engineering", "unclassified")


class NoBundle(RuntimeError):
    """One of the two payloads is not built, so there is nothing to compare."""


def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise NoBundle("{} is not built — run `make build` first".format(path.name))
    text = path.read_text(encoding="utf-8")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise NoBundle("{} is not a bundle".format(path.name))
    try:
        return json.loads(text[start:end + 1])
    except ValueError as exc:
        raise NoBundle("{}: {}".format(path.name, str(exc)[:120]))


def bundles(ocp: Optional[Path] = None,
            controllers: Optional[Path] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The two published run bundles: OCP's and the controllers'.

    Read from disk rather than re-collected. The question is whether the two
    *published* views agree, and re-fetching would compare something nobody has
    seen against something nobody has seen.
    """
    data = config.DASHBOARD_DATA_DIR
    return (_load(ocp or (data / "runs.js")),
            _load(controllers or (data / "runs_pega.js")))


def _rows(bundle: Dict[str, Any], day: str) -> List[Dict[str, Any]]:
    out = []
    for row in bundle.get("runs") or []:
        if row.get(FIELD["day"]) != day:
            continue
        station = row.get(FIELD["station"])
        if station in SKIP_STATIONS:
            continue
        out.append({
            # A controller row is per slot and carries "#slot3" on its id; the
            # suite run is the part in front, and it is what pairs with an EOS
            # run.
            "run": str(row.get(FIELD["id"]) or "").split("#")[0],
            "id": row.get(FIELD["id"]),
            "serial": str(row.get(FIELD["serial"]) or "").strip(),
            "station": station,
            "suite": row.get(FIELD["suite"]) or "",
            "version": row.get(FIELD["version"]) or "",
            "release": row.get(FIELD["release"]) or "",
            "start": row.get(FIELD["start"]) or 0,
            "status": row.get(FIELD["status"]) or "",
        })
    return out


def latest_day(*bundles_in: Dict[str, Any]) -> Optional[str]:
    """The most recent day any source has a run for."""
    days = set()
    for bundle in bundles_in:
        for row in bundle.get("runs") or []:
            if row.get(FIELD["day"]):
                days.add(row[FIELD["day"]])
    return max(days) if days else None


def _release(version_text: str) -> str:
    """A release the two sources spell the same.

    EOS reports ``2026.227.0-gite2b61375`` in its version field; a controller
    reports the whole suite name, ``L10_SFT`` or
    ``mlt_2026.231.0-git91a99a1f-tpm-permanent``. The release number is the only
    token both carry, and only sometimes — so this returns "" rather than
    guessing, and a blank release simply means the release cannot corroborate a
    match.
    """
    import re

    found = re.search(r"(\d{4}\.\d+\.\d+)", version_text or "")
    return found.group(1) if found else ""


def _classify(unit: Dict[str, Any], other: List[Dict[str, Any]]) -> str:
    """Why the other source does not have this unit."""
    same_station = [row for row in other if row["station"] == unit["station"]]
    if not same_station:
        return "station-absent"
    release = _release(unit["version"]) or _release(unit["suite"])
    for row in same_station:
        if release and release == (_release(row["version"]) or _release(row["suite"])) \
                and abs(row["start"] - unit["start"]) <= WINDOW_SEC:
            return "fixture-not-unit"
    return "run-absent"


def compare_day(day: str, ocp: Dict[str, Any],
                controllers: Dict[str, Any]) -> Dict[str, Any]:
    """What each source holds for one day, and which units are on one side only."""
    left, right = _rows(ocp, day), _rows(controllers, day)

    def index(rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
        out: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for row in rows:
            out.setdefault((row["station"], row["serial"]), []).append(row)
        return out

    by_ocp, by_ctl = index(left), index(right)

    missing_from_ocp = [
        dict(row, kind=_classify(row, left))
        for key, rows in sorted(by_ctl.items()) if key not in by_ocp
        for row in [rows[0]]
    ]
    missing_from_controllers = [
        dict(row, kind=_classify(row, right))
        for key, rows in sorted(by_ocp.items()) if key not in by_ctl
        for row in [rows[0]]
    ]

    keys = sorted({row["station"] for row in left} | {row["station"] for row in right},
                  key=lambda k: _order(k))
    per_station = []
    for key in keys:
        ocp_rows = [row for row in left if row["station"] == key]
        ctl_rows = [row for row in right if row["station"] == key]
        per_station.append({
            "station": key,
            "label": stations.label_of(key),
            "ocpRuns": len({row["run"] for row in ocp_rows}),
            "ocpUnits": len({row["serial"] for row in ocp_rows if row["serial"]}),
            "ctlRuns": len({row["run"] for row in ctl_rows}),
            "ctlUnits": len({row["serial"] for row in ctl_rows if row["serial"]}),
            "missingFromOcp": sum(1 for row in missing_from_ocp
                                  if row["station"] == key),
            "missingFromControllers": sum(1 for row in missing_from_controllers
                                          if row["station"] == key),
            # The one class no schema difference explains.
            "ocpBlind": bool(ctl_rows and not ocp_rows),
        })

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "build": version.describe(),
        "day": day,
        "sources": {
            "ocp": {"label": (ocp.get("source") or "OCP Logs"),
                    "collectedAt": ocp.get("collectedAt")},
            "controllers": {"label": (controllers.get("source") or "pega"),
                            "collectedAt": controllers.get("collectedAt")},
        },
        "stations": per_station,
        "missingFromOcp": missing_from_ocp,
        "missingFromControllers": missing_from_controllers,
        "counts": {
            "missingFromOcp": len(missing_from_ocp),
            "missingFromControllers": len(missing_from_controllers),
            "byKind": _by_kind(missing_from_ocp),
            "byKindOther": _by_kind(missing_from_controllers),
        },
    }


def _order(key: str) -> Tuple[int, str]:
    for station in stations.registry():
        if station["key"] == key:
            return (station.get("order", 999), key)
    return (999, key)


def _by_kind(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        out[row["kind"]] = out.get(row["kind"], 0) + 1
    return out


#: The CSV's columns. ``Kind`` first among the judgements because it is the one
#: that says whether a row is a fault at all.
CSV_HEADER = ("Day", "Station", "DUT_SN", "Kind", "Suite", "Release",
              "Status_On_The_Side_That_Has_It", "Suite_Run", "Started_UTC")


def write_csv(result: Dict[str, Any], path: Optional[Path] = None,
              direction: str = "ocp") -> Path:
    """The units one side does not have, as a file for a spreadsheet.

    ``direction`` picks which side is being asked about: "ocp" lists what OCP
    does not have, "controllers" the reverse. Both exist because on some days
    the controllers are the thin one, and a report that can only look one way
    would call those days clean.
    """
    rows = (result["missingFromOcp"] if direction == "ocp"
            else result["missingFromControllers"])
    target = path or (config.DASHBOARD_DATA_DIR /
                      "missing-from-{}-{}.csv".format(direction, result["day"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        # utf-8-sig: the people who read this open it in Excel, which reads a
        # plain UTF-8 file as its local codepage.
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow([
                result["day"], row["station"], row["serial"], row["kind"],
                row["suite"], row["release"], row["status"], row["run"],
                datetime.fromtimestamp(row["start"], timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S") if row["start"] else "",
            ])
    return target
