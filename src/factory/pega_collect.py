"""Build the run table from the ESVM controllers instead of from EOS.

WHY A SECOND COLLECTOR RATHER THAN A SECOND DASHBOARD
-----------------------------------------------------
The station page's daily yield does not match the line's own numbers, and the
reason is upstream of any chart: EOS records **one run per fixture**, with one
DUT serial and no slot, while the controllers record **one result per unit**.
Every metric built on the first is answering a slightly different question from
the one the line asks.

So this produces the *same payload shape* ``collect.read_runs()`` does —
``{"runs": [...], "stations": [...], "levelErrors": {}}`` — and everything
downstream is reused untouched: ``daily.py`` computes the same metrics,
``build_stations.py`` compiles the same bundle, and the page renders the same
layout. The only difference is where a run came from, which is exactly the
difference worth being able to see.

WHAT A "RUN" IS HERE
--------------------
On the module line a fixture drives eight slots, and pega3 returns them, so one
suite run becomes **eight records** — one per unit, carrying that chip's tests
and that chip's verdict. That is the granularity the line counts in, and it is
what makes this page's yield comparable to the tracker's.

On L10, L11 and VBB a run tests one DUT and ``participating`` is null, so a
suite run is one record.

WHAT IT COSTS
-------------
A 30-day window is roughly a thousand detail fetches across four hosts. They are
cached on disk and a finished run never changes, so the first build is slow and
the rest are not.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import build_l10, chips, config, parse, pega, stations

log = logging.getLogger(__name__)

#: Which controller drives which part of the line, and whether its runs carry
#: slots. Order is the order the line runs, so the payload reads top to bottom.
HOSTS: Tuple[Tuple[str, str, bool], ...] = (
    ("pega2", "l6", False),        # VBB provisioning
    ("pega6", "module", True),     # TIM — two ovens, sixteen slots each
    ("pega3", "module", True),     # MLT, HTT, chip screening, SLT — eight slots
    ("pega4", "l10", False),       # FAT, SFT, RIN, 2U — one chassis
    ("pega5", "l11", False),       # provisioning and test
)

#: Controllers that put the module serial in ``dut_part_number`` rather than in
#: the participant list.
#:
#: pega6 is the odd one out and it is worth being explicit. Everywhere else the
#: unit under test *is* the thing the participant list names, so
#: ``pega.participants`` is the right reader. At the bake the unit under test is
#: a module bolted to a coldplate, and pega6 records the coldplate as the
#: participant (a 12-digit serial) and the module in ``dut_part_number`` (15
#: digits). Read it the usual way and every TIM result is filed under a
#: coldplate, which then matches no MLT row and looks like missing data.
SERIAL_FROM_ENTRY = ("pega6",)

#: A module serial as every other station spells it: fifteen digits.
#:
#: Needed because ``dut_part_number`` on pega6 has not always held one. Before
#: 2026-08-20 the bake logged a six-character coldplate or lot code there
#: (SW5VZ8), so a run from those days has no module to attribute to. Those runs
#: still count — the bake happened — they simply cannot be traced to a unit, and
#: guessing would be worse than saying so.
MODULE_SERIAL = re.compile(r"^\d{15}$")

#: A version stamp and everything after it: ``mlt_2026.220.0-git2f1c2f23`` and
#: ``…_validation`` alike reduce to ``mlt``.
VERSIONED = re.compile(r"_\d{4}\.\d+.*$")

#: Not a production run, whatever the stage looks like once the version is off.
#: Checked against the full name, before any stripping.
NOT_PRODUCTION = re.compile(
    r"(_validation|_debug|_krish|_out_dir|_SAM|_SMOKE|_etch\d+|^DRY_?RUN|^test_)",
    re.IGNORECASE)

#: How far back to walk the controllers, when a caller asks for a fixed window.
#:
#: The default is no longer a number: :func:`collect` walks from
#: ``pega.CONTROLLER_FROM``, the day the data actually starts. Ninety was
#: measured when 90 days back was 2026-05-27 and the earliest run anywhere was
#: 05-21 — true then, and quietly false by 09-02, when the same 90 days began
#: on 06-04 and cut a fortnight off pega3. A window defined by its age walks
#: away from a history defined by its start.
#:
#: This constant stays for the callers that genuinely want a recent slice —
#: the FPY summary asks for its own — and for `--days`.
#:
#: It is cheap to keep the whole history: a finished run never changes, so
#: every day but today is served from disk after the first build. The reporting
#: windows are much shorter and are trimmed at the point of use — the station
#: page shows seven days — but the collected history is what lets the weekly
#: page tell a unit's first attempt from its fourth.
COLLECT_DAYS = 90

#: pega verdicts -> the vocabulary the rest of the repo speaks.
STATUS = {
    "passed": "pass", "pass": "pass",
    "failed": "fail", "fail": "fail",
    "error": "error", "aborted": "error", "abort": "error",
    "skipped": "skip", "not_started": "skip", "notstarted": "skip",
    "running": "unknown",
}


def _status(value: Optional[str]) -> str:
    return STATUS.get(str(value or "").strip().lower(), "unknown")


def _epoch(value: Optional[str]) -> Optional[int]:
    """pega timestamps are ISO, sometimes with a Z and sometimes without."""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def station_of(host: str, suite: Optional[str]) -> Optional[str]:
    """The station key for a controller's suite name.

    The two systems spell the same stage differently — EOS reports the test
    class, a controller reports the suite it ran under — so this asks the
    registry first (which already accepts both spellings for VBB and the module
    stations) and falls back to the L10 stage matcher for pega4.
    """
    name = (suite or "").strip()
    if not name:
        return None

    if host == "pega4":
        stage = build_l10.stage_of(name)
        return {"fat": "l10_fat", "sft": "l10_sft",
                "rin": "l10_rin", "2u": "l10_2u"}.get(stage)

    if host == "pega5":
        lowered = name.lower()
        if "provision" in lowered:
            return "l11_provision"
        return "l11_test" if lowered.startswith("l11") else None

    # Engineering first, on the *whole* name. Stripping the version off
    # mlt_2026.220.0-git2f1c2f23_validation leaves "mlt", which classifies as a
    # production station — so a validation run would be counted into the line's
    # yield by an accident of string handling.
    if NOT_PRODUCTION.search(name):
        return None

    # pega2 and pega3: the registry already accepts both systems' spellings. The
    # suite carries a version on pega3 (mlt_2026.220.0-git…) that the registry's
    # anchored patterns cannot match, so it is removed along with anything after.
    base = VERSIONED.sub("", name)
    for candidate in (base, name):
        for level in ("module", "slt", "l6", "l10", "l11"):
            key = stations.classify(level, candidate)
            if key not in (stations.UNCLASSIFIED, stations.ENGINEERING):
                return key
    return None


def _tests_for(detail: Dict[str, Any], slot: Optional[int]) -> List[Dict[str, Any]]:
    """The test cases belonging to one unit.

    With a slot, only the cases carrying that chip index — a fixture's other
    seven chips are other units' results and must not land in this one's
    Pareto. Without one, the run is a single DUT and every case is its own.
    """
    out = []
    for case in detail.get("test_cases") or []:
        name = case.get("test_id") or case.get("test_name") or ""
        if slot is not None and chips.chip_of(name) != slot:
            continue
        out.append({
            "name": name.rsplit("_run_", 1)[-1] if "_run_" in name else name,
            "displayName": case.get("test_name"),
            "status": _status(case.get("status")),
            "durationSec": case.get("duration_seconds"),
            "code": None,
            "logFile": None,
        })
    return out


def collect(days: Optional[int] = None,
            hosts: Tuple[Tuple[str, str, bool], ...] = HOSTS,
            progress: bool = True) -> Dict[str, Any]:
    """Walk every controller and return a payload shaped like the EOS one.

    ``days`` asks for that many days ending today. Left out — the default —
    the walk starts at :data:`pega.CONTROLLER_FROM` instead, so it reaches the
    beginning of the data rather than a fixed distance behind today.
    """
    today = datetime.now(timezone.utc).date()
    if days is None:
        window = pega.day_range(pega.CONTROLLER_FROM,
                                today.strftime("%Y-%m-%d"))
    else:
        window = [(today - timedelta(days=offset)).strftime("%Y-%m-%d")
                  for offset in range(days - 1, -1, -1)]

    records: List[Dict[str, Any]] = []
    problems: List[str] = []
    host_errors: Dict[str, str] = {}

    for host, level, per_slot in hosts:
        seen = 0
        for day in window:
            try:
                listing = pega.day_suite_runs(day, host=host)
            except pega.PegaUnavailable as exc:
                host_errors.setdefault(host, str(exc))
                break
            for entry in listing:
                run_id = entry.get("suite_run_id") or ""
                suite = entry.get("suite_name") or ""
                station = station_of(host, suite)
                if not station:
                    continue
                try:
                    detail = pega.suite_run(run_id, host=host)
                except pega.PegaUnavailable as exc:
                    problems.append("{}: {}".format(run_id, exc))
                    continue
                seen += 1
                records.extend(_records_for(entry, detail, host, level, station,
                                            per_slot))
        if progress and seen:
            log.info("%s -> %d suite runs", host, seen)

    records.sort(key=lambda rec: (rec.get("startTs") or 0, rec.get("runId") or ""))
    _mark_attempts(records)

    return {
        "schemaVersion": 2,
        "levelErrors": host_errors,
        "stations": stations.registry(),
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "window": {"from": window[0], "to": window[-1]},
        "levels": sorted({level for _h, level, _s in hosts}),
        "timezone": config.timezone_name(),
        "runCount": len(records),
        "problems": problems,
        "source": "pega",
        "dataSource": {
            # Named from HOSTS rather than written out, so adding a
            # controller cannot leave the page claiming the old set. It said
            # "pega2 – pega5" for a day after pega6 started serving TIM.
            "label": "{} (ESVM)".format(
                ", ".join(host for host, _level, _slots in HOSTS)),
            "url": "http://pega3:3000",
            "note": "straight from the station controllers — one row per unit",
        },
        "runs": records,
    }


def fetch_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    """A fetch state for a source that has no fetch history.

    The EOS side tracks last-fetch against last-update across ticks, because a
    tick there can return identical data. This collector reads the controllers
    live on every build, so the honest answer to "when was this fetched" is
    "when it was built" — and reporting the EOS shape unfilled makes the page
    say ``never`` under three headings while showing a thousand runs, which is
    the sort of contradiction that costs a reader their trust in the rest of it.

    Per-station timestamps are the newest run each station actually has, so the
    "newest station data" cell answers about the line rather than about us.
    """
    built = payload.get("generatedAt")
    newest: Dict[str, Dict[str, Any]] = {}
    for record in payload.get("runs", []):
        key = record.get("stationKey")
        started = record.get("startTs")
        if not key or not started:
            continue
        moment = datetime.fromtimestamp(started, timezone.utc).replace(
            microsecond=0).isoformat()
        # `runs`, not `runCount`: this dict is read by the same header the EOS
        # state feeds, and a near-miss on the field name shows up as a confident
        # "0 runs across all stations" beside a thousand of them.
        entry = newest.setdefault(key, {"lastUpdateAt": moment, "runs": 0})
        entry["runs"] += 1
        if moment > entry["lastUpdateAt"]:
            entry["lastUpdateAt"] = moment

    return {
        "lastFetchAt": built,
        "lastFetchAttemptAt": built,
        "lastFetchStatus": "ok",
        "lastUpdateAt": built,
        "consecutiveNoChange": 0,
        # No history: every build here is a live read, so there is nothing to
        # compare against. An empty strip says that more honestly than a
        # fabricated one would.
        "totalFetches": 0,
        "stations": newest,
        "history": [],
    }


def _records_for(entry: Dict[str, Any], detail: Dict[str, Any], host: str,
                 level: str, station: str, per_slot: bool) -> List[Dict[str, Any]]:
    run_id = entry.get("suite_run_id") or ""
    suite = entry.get("suite_name") or ""
    started = _epoch(entry.get("start_time"))
    ended = _epoch(entry.get("end_time"))
    duration = entry.get("duration_seconds")

    parts = pega.participants(detail)

    # pega6's participant is the coldplate; the module is on the list entry. Only
    # where the run drove one participant: with several there is no way to say
    # which of them the single entry-level serial belongs to, and inventing an
    # answer would put one unit's bake on another's row.
    entry_serial = str(entry.get("dut_part_number") or "").strip()
    override = (host in SERIAL_FROM_ENTRY and len(parts) == 1
                and MODULE_SERIAL.match(entry_serial))

    # The slot filter on the test cases exists to separate eight chips' results
    # inside one fixture run, and it does that by reading a chip index off each
    # test id. The bake has no chip index on any of its ids — its three cases
    # are read_modbus_temperature, poll_modbus_temperature and
    # validate_coldplate_temperature — so filtering by slot drops every one of
    # them and the unit comes out with a verdict and no test behind it.
    #
    # So the filter is applied only where there is something to separate.
    per_chip = any(chips.chip_of(case.get("test_id") or "") is not None
                   for case in detail.get("test_cases") or [])

    out = []
    for part in parts:
        slot = part["slot"] if (per_slot and per_chip) else None
        record = {
            # One record per unit, so the id has to name the unit too — two
            # slots of one fixture are two runs here and must not collide.
            "runId": "{}#slot{}".format(run_id, part["slot"])
                     if per_slot else run_id,
            "level": level,
            "suite": suite,
            "version": suite,
            "dutSerial": entry_serial if override else part["dut"],
            # Kept whichever way round it came, because at the bake the carrier
            # is a real object somebody can go and find.
            "carrierSerial": part["dut"] if override else None,
            "startTs": started,
            "endTs": ended,
            "durationSec": duration,
            "status": _status(part["status"]),
            "stationKey": station,
            "tests": _tests_for(detail, slot),
            "station": entry.get("station_id"),
        }
        # Folds the tests into failure records and counts, exactly as the EOS
        # path does — the run's own status is already set, so it is kept.
        parse.summarize_tests(record)
        out.append(record)
    return out


def _mark_attempts(records: List[Dict[str, Any]]) -> None:
    """Number each DUT's runs at a station, in time order.

    Keyed on the *station* rather than the level: a controller's level is a
    whole family (four L10 stages share ``l10``), so keying on it would call a
    unit's first SFT its second attempt because it had already been through FAT.
    """
    seen: Dict[tuple, int] = {}
    for record in records:
        key = (record.get("stationKey"), record.get("dutSerial"))
        seen[key] = seen.get(key, 0) + 1
        record["attempt"] = seen[key]
