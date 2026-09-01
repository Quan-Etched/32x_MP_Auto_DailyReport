"""EOS tested it — does the shopfloor know about it?

WHY THIS IS ITS OWN REPORT
--------------------------
The two systems are joined by serial and by nothing else, so the only way to
know the join is holding is to take one side's serials and look for them on the
other. Every gap found so far was found this way, one serial at a time, by
somebody noticing: a Sohu board with an MLT run and no genealogy, a module that
belongs to no product level. This does that sweep on purpose.

It reads EOS live rather than from a snapshot, because the question is "is the
join holding *now*" and a snapshot answers "was it holding when the snapshot was
taken". The SFIS side is checked live too, per serial.

BOTH DIRECTIONS, AND THEY MEAN DIFFERENT THINGS
-----------------------------------------------
``eos_not_in_sfis``
    EOS has runs for a serial the receiver has never heard of. This is the
    traceability escape: a board was tested and never linked, so nothing
    downstream can say what it was fitted into. The "no ASIC SN linked in SFIS"
    class, in bulk.

``sfis_test_no_eos``
    The receiver has a *test-section* process event for a serial that EOS has no
    run for in the window. Weaker evidence and often benign — Pega's own
    stations (AQC, DIP MDA, 5DX) are real tests that were never going to be in
    EOS — so it is reported separately and never counted as an escape.

WHAT IS NOT A FINDING
---------------------
* **Non-production DUTs.** EOS carries hand-typed and bring-up serials — ``1234``,
  ``RENAME_TEST_0``, ``ZZTEST…``. Counting those as escapes buries the real ones.
* **A level EOS cannot read.** ``l11`` and ``bringup`` return HTTP 424 with the
  current key: the bucket is unreadable, so "no runs" there is a permission fact,
  not a manufacturing one. Reported as unavailable rather than as zero.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import eos, sfis

#: Serial shapes that are not product. Same list the gap report uses.
NON_PRODUCTION = (
    # A literal "SN" arrived as a dutSerial on three l6 runs -- a station with an
    # unfilled placeholder, not a board. Listed explicitly because the honest way
    # to know is to look at it, and a rule broad enough to catch it by shape
    # would start eating real vendor barcodes.
    r"(?i)^sn$",
    r"^\d{1,8}$",
    r"(?i)^zztest",
    r"(?i)rename_test",
    r"(?i)^test$",
    r"(?i)^dut\d*$",
)


def is_non_production(sn: str) -> bool:
    return any(re.search(pattern, sn or "") for pattern in NON_PRODUCTION)


def sfis_knows(sn: str) -> Dict[str, Any]:
    """Does the receiver hold anything at all for this serial?

    "Anything" is deliberately broad: its own process events, or an edge in
    either direction. A board that was scanned into a parent and never routed
    still counts as known -- the escape being hunted is the serial the receiver
    has never seen, not the one with a thin record.
    """
    response = sfis.serial(sn)
    if not response.ok:
        return {"known": None, "error": response.error}
    data = response.data or {}
    process = data.get("process_events") or []
    as_parent = data.get("genealogy_events_as_parent") or []
    as_child = data.get("genealogy_events_as_child") or []
    return {
        "known": bool(process or as_parent or as_child),
        "process": len(process),
        "as_parent": len(as_parent),
        "as_child": len(as_child),
    }


def controller_window(days: int) -> Dict[str, Any]:
    """What the ESVM controllers recorded over the same window.

    The third leg, and the one that makes the report a loop rather than a
    comparison. EOS being empty for a level means one of two very different
    things -- the line did not run that station, or EOS stopped receiving it --
    and only the controllers can tell them apart. They are the line's own record.

    Degrades to ``available: False`` rather than failing: a controller that
    cannot be reached must not cost us the EOS half.
    """
    from datetime import datetime, timedelta, timezone

    try:
        from factory import pega, pega_collect, stations as factory_stations
    except ImportError as exc:  # pragma: no cover
        return {"available": False, "error": f"factory package: {exc}"}

    today = datetime.now(timezone.utc).date()
    per_station: Dict[str, int] = {}
    hosts_seen: Dict[str, Any] = {}
    for offset in range(days):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        for host, level, per_slot in getattr(pega_collect, "HOSTS", ()):
            try:
                entries = pega.day_suite_runs(day, host=host)
            except Exception as exc:
                hosts_seen.setdefault(host, str(exc))
                continue
            hosts_seen.setdefault(host, "ok")
            for entry in entries:
                suite = entry.get("suite_name") or ""
                key = pega_collect.station_of(host, suite) or f"{host}/{suite}"
                per_station[key] = per_station.get(key, 0) + 1
    return {"available": True, "stations": per_station, "hosts": hosts_seen}


def run(days: int = 7, levels: Optional[List[str]] = None,
        with_controllers: bool = True) -> Dict[str, Any]:
    """Sweep EOS for the window and check every DUT against the receiver."""
    since, until = eos.window(days)
    wanted = levels or list(eos.LEVELS)

    per_level: Dict[str, Any] = {}
    duts: Dict[str, Dict[str, Any]] = {}

    for level in wanted:
        response = eos.runs(level, since=since, until=until,
                            timeout=eos.SWEEP_TIMEOUT, retries=2)
        if not response.ok:
            per_level[level] = {"available": False, "error": response.error}
            continue
        found = (response.data or {}).get("runs") or []
        seen: Dict[str, int] = {}
        for entry in found:
            sn = str(entry.get("dutSerial") or "")
            if not sn:
                continue
            seen[sn] = seen.get(sn, 0) + 1
            record = duts.setdefault(sn, {"levels": {}, "runs": 0, "first": "",
                                          "suite": entry.get("suite")})
            record["levels"][level] = record["levels"].get(level, 0) + 1
            record["runs"] += 1
            started = entry.get("startedAt") or ""
            if not record["first"] or started < record["first"]:
                record["first"] = started
        per_level[level] = {"available": True, "runs": len(found), "duts": len(seen)}

    for sn, record in duts.items():
        if is_non_production(sn):
            record["verdict"] = "non_production"
            continue
        state = sfis_knows(sn)
        record.update(state)
        if state.get("known") is None:
            record["verdict"] = "lookup_failed"
        elif state["known"]:
            record["verdict"] = "in_sfis"
        else:
            record["verdict"] = "absent_from_sfis"

    for level, stats in per_level.items():
        if not stats.get("available"):
            continue
        stats["in_sfis"] = 0
        stats["absent"] = 0
        stats["non_production"] = 0
        stats["lookup_failed"] = 0
        for record in duts.values():
            if level not in record["levels"]:
                continue
            key = {"in_sfis": "in_sfis", "absent_from_sfis": "absent",
                   "non_production": "non_production",
                   "lookup_failed": "lookup_failed"}.get(record.get("verdict"))
            if key:
                stats[key] += 1

    # Freshness per level: "no runs in the window" and "EOS stopped receiving
    # this level" look identical from inside the window, so the last run at each
    # level is asked for over a wider one.
    wide_since, wide_until = eos.window(max(days * 6, 60))
    for level in wanted:
        stats = per_level.get(level) or {}
        if not stats.get("available"):
            continue
        response = eos.runs(level, since=wide_since, until=wide_until,
                            timeout=eos.SWEEP_TIMEOUT, retries=1)
        if response.ok:
            stamps = sorted(
                (r.get("startedAt") or "")
                for r in ((response.data or {}).get("runs") or [])
            )
            stats["last_seen"] = stamps[-1] if stamps else None
            stats["runs_wide"] = len(stamps)

    controllers = controller_window(days) if with_controllers else None

    return {"window": [since, until], "days": days,
            "levels": per_level, "duts": duts,
            "controllers": controllers}
