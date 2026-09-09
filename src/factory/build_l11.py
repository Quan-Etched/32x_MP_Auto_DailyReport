"""L11 — rack provisioning and rack test, from pega5.

A third table under the module and L10 ones, for the same reason L10 got the
second: the subject changes. The module tracker follows a fifteen-digit unit
through MLT and HTT, L10 follows a twelve-digit chassis through four stages,
and L11 follows a *rack* — four 6U chassis, each holding many modules. Three
different things, one row each, three tables.

WHAT IS DIFFERENT ABOUT L11
---------------------------
**It is still in bring-up, and the page must not hide that.** Both L11 stations
are marked ``blocked`` in the station registry with unverified suite patterns,
and pega5 has answered for four suite names in total. Two consequences show on
the page rather than in a comment:

*Aborted is a real outcome here.* A third of the runs pega5 returns end
``aborted`` — the rack never reached a verdict. L10's builder writes a result
cell only for pass and fail, which would leave those rows blank and read as "no
run today". This one writes ``Aborted`` explicitly, tallied as no-verdict but
visible, because on a station being brought up the difference between "failed"
and "never got that far" is most of the information.

*Provisioning runs under an engineer's name.* Every provisioning run pega5 has
is ``kamil_L11_provisioning_rms_pdu_cdu``. It is counted — a rack really was
provisioned — but flagged non-release through the same mechanism the module
tracker uses for debug bundles, so the tile prints the release figure beside
the total and nobody reads a bring-up campaign as line yield.

WHY TWO STAGES AND NOT MORE
---------------------------
The Aug 3 flowchart draws L11 as ASSY → L11 Provisioning → L11 Test, and the
station registry carries exactly ``l11_provision`` and ``l11_test``. Naming them
the same here is what lets the tracker and the station page be compared; L10
learned that the hard way when a renamed suite zeroed a station.

Rack serials are twelve digits, like an L10 chassis, so the two cannot be told
apart by shape — which is another argument for separate tables over a shared
one with a type column.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import build_dailyexcel, pega, rootcause, xlsx

#: The two L11 stages, in the order the line runs them, with the spellings
#: pega5 has used. Provisioning is matched first: ``kamil_L11_provisioning…``
#: contains ``L11`` too, and a test-first order would swallow it.
STAGES = (
    ("provision", "L11 Provision", r"provision"),
    ("test",      "L11 Test",      r"(^|_)L11[_A-Za-z0-9]*"),
)

#: Not a stage: dry runs, output directories, smoke tests, ticket-named runs.
#:
#: Deliberately NOT here: ``kamil_``. An engineer's name in a suite name means
#: the suite is not a release build, which is a different claim from "this run
#: did not happen" — see ``NON_RELEASE`` in the module tracker, which is where
#: it is handled instead. Dropping it would leave the provisioning stage empty
#: on every day pega5 has, which is a worse lie than counting it.
ENGINEERING = re.compile(
    r"(_out_dir|_SAM|_SMOKE|_etch\d+|^DRY_?RUN|^test_)", re.IGNORECASE)

#: Stage key -> the station key the rest of the dashboard uses.
STATION_OF = {"provision": "l11_provision", "test": "l11_test"}


def _matcher():
    return [(key, label, re.compile(pattern, re.IGNORECASE))
            for key, label, pattern in STAGES]


def stage_of(suite: Optional[str]) -> Optional[str]:
    """Which L11 stage a pega5 suite name belongs to, if any."""
    name = (suite or "").strip()
    if not name or ENGINEERING.search(name):
        return None
    for key, _label, pattern in _matcher():
        if pattern.search(name):
            return key
    return None


def unit_failures(detail: Dict[str, Any]) -> str:
    """Every test case that failed in the run, oldest first, one per line.

    Failures only, not aborts. When a rack aborts, every case after the one
    that stopped it is also marked aborted, so listing them would bury the one
    line that says what happened under five that say what did not get a chance
    to happen.
    """
    seen: List[str] = []
    for case in sorted(detail.get("test_cases") or [],
                       key=lambda c: c.get("start_time") or ""):
        status = str(case.get("status") or "").lower()
        if not status.startswith(("fail", "error")):
            continue
        name = (case.get("test_name") or "").strip()
        if not name or rootcause.is_container(name) or name in seen:
            continue
        seen.append(name)
    return "\n".join(seen)


def _columns() -> List[Dict[str, Any]]:
    """Date, rack, part, then four columns per stage.

    The module tracker's shape — result, version, failure, link — so all three
    tables read alike and share one renderer and one tally.
    """
    columns = [
        {"key": "A", "title": "Date", "width": None},
        # "SN", not "Rack SN" — see the note in build_l10._columns. The
        # heading above the table says L11 and counts racks.
        {"key": "B", "title": "SN", "width": 16.0},
        {"key": "C", "title": "DUT PN", "width": 12.0},
    ]
    index = 3
    for key, label, _pattern in STAGES:
        station = STATION_OF[key]
        columns.append({
            "key": xlsx.column_letters(index), "title": "{} Results".format(label),
            "width": 11.0, "station": station,
        })
        columns.append({
            "key": xlsx.column_letters(index + 1),
            "title": "{} Suite".format(label), "width": 34.0,
            "kind": "version", "station": station,
        })
        columns.append({
            "key": xlsx.column_letters(index + 2),
            "title": "{} Failure Test Case".format(label), "width": 34.0,
        })
        columns.append({
            "key": xlsx.column_letters(index + 3), "title": "FI Test Link",
            "width": 10.0,
        })
        index += 4
    return columns


def stage_index(first: str, last: str
                ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """Every attempt each stage made over a whole span, read once.

    The per-tab walk this replaces re-read the same runs for every day the
    tracker published — affordable only while the history reached 30 days and
    the tracker began in August. Over the controllers' full retention it was
    tens of seconds per tab.
    """
    return build_dailyexcel.attempt_index(
        "pega5", [key for key, _l, _p in STAGES],
        lambda entry: stage_of(entry.get("suite_name")),
        lambda run_id, slot: pega.run_url(run_id, slot, host="pega5"),
        first, last)


def _seen_before(day: str, lookback: Optional[int] = None
                 ) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """Every attempt each L11 stage made on a rack before ``day``.

    Same ten-day rule as the other two tables, so "new input" means one thing
    across the page. It matters more here than anywhere else on the dashboard:
    L11 has run two racks all month, so almost every row is a returning one and
    a count-all yield is mostly the same rack being retried.
    """
    # Late-bound rather than a default argument: the reach is derived from
    # pega.HISTORY_FROM, and a default freezes it at import, so moving the
    # floor left this function reaching a distance nothing else used.
    if lookback is None:
        lookback = build_dailyexcel.NEW_INPUT_LOOKBACK

    # FACTORY_PEGA=0 means no controllers, here as well as on the module
    # tracker — build_dailyexcel._seen_before has always had this guard and
    # these two never did. It went unnoticed while the reach was 30 days of
    # mostly-cached listings; deepening it to the history floor on 2026-09-08
    # turned the same path into 144 live requests inside a test suite that
    # believed it had switched the integration off.
    if not pega.enabled():
        return {key: {} for key, _label, _pattern in STAGES}

    start = datetime.strptime(day, "%Y-%m-%d").date()
    first = max(pega.HISTORY_FROM,
                (start - timedelta(days=lookback)).strftime("%Y-%m-%d"))
    last = (start - timedelta(days=1)).strftime("%Y-%m-%d")
    return build_dailyexcel.slice_before(
        stage_index(first, last), day, lookback)


def _day(day: str, history_index: Optional[Dict[str, Any]] = None
         ) -> Optional[Dict[str, Any]]:
    """One day's L11 tab. ``index`` as in :func:`build_l10._day`."""
    # Switched off means switched off. The call site cannot know: it guards
    # the shared span read with pega.enabled() and then asks for the day
    # anyway, so the guard belongs here, where the request is made.
    if not pega.enabled():
        return None
    try:
        listing = pega.day_suite_runs(day, host="pega5")
    except pega.PegaUnavailable:
        return None

    columns = _columns()
    index = {column["key"]: position for position, column in enumerate(columns)}
    slot_of = {key: xlsx.column_letters(3 + position * 4)
               for position, (key, _l, _p) in enumerate(STAGES)}

    units: Dict[str, Dict[str, Any]] = {}
    runs_seen = 0
    attempts_of: Dict[str, Dict[str, int]] = {}
    for entry in listing:
        stage = stage_of(entry.get("suite_name"))
        if not stage:
            continue
        run_id = entry.get("suite_run_id") or ""
        try:
            detail = pega.suite_run(run_id, host="pega5")
        except pega.PegaUnavailable:
            continue
        runs_seen += 1
        started = entry.get("start_time") or ""

        for part in pega.participants(detail):
            unit = units.setdefault(part["dut"], {
                "pn": entry.get("dut_part_number") or "",
            })
            # How many times the rack was put through this stage today. L11 is
            # retried hard during bring-up — six attempts on one rack in an
            # afternoon — and a table showing only the last one would make a
            # day of firefighting look like a single quiet test.
            attempts_of.setdefault(part["dut"], {}).setdefault(stage, 0)
            attempts_of[part["dut"]][stage] += 1

            # The same attempts again, with their verdicts and links, for the
            # Test History strip. The count above is every run including the
            # aborts; the strip is only what returned a verdict, so the two
            # are kept apart rather than derived from each other.
            if part["status"] in ("pass", "fail"):
                unit.setdefault(stage + build_dailyexcel.ATTEMPTS_KEY,
                                []).append({
                                    "day": day,
                                    "status": part["status"],
                                    "url": pega.run_url(run_id, part["slot"],
                                                        host="pega5"),
                                    "suite": entry.get("suite_name") or "",
                                    "started": started,
                                })

            previous = unit.get(stage)
            if previous and previous["started"] >= started:
                continue
            unit[stage] = {
                "suite": entry.get("suite_name") or "",
                "status": part["status"],
                "fail": unit_failures(detail) if part["status"] == "fail" else "",
                "url": pega.run_url(run_id, part["slot"], host="pega5"),
                "short": run_id.rsplit("_run_", 1)[-1],
                "started": started,
            }

    if not units:
        return None

    def sort_key(item):
        dut, unit = item
        bad = any((unit.get(k) or {}).get("status") != "pass"
                  for k, _l, _p in STAGES if k in unit)
        return (not bad, dut)

    history = (build_dailyexcel.slice_before(
                   history_index, day, build_dailyexcel.NEW_INPUT_LOOKBACK)
               if history_index is not None else _seen_before(day))

    rows = []
    for dut, unit in sorted(units.items(), key=sort_key):
        row = [{} for _ in columns]
        row[index["A"]] = {"v": day}
        serial: Dict[str, Any] = {"v": dut}
        for key, _label, _pattern in STAGES:
            if key not in unit:
                continue
            station = STATION_OF[key]
            past = (history.get(key) or {}).get(dut) or []
            today = build_dailyexcel._day_attempts(unit, key)
            # New input is still decided on the days before this one; the
            # strip is what carries today. It matters most here — L11 retries
            # a rack six times in an afternoon, and a strip that stopped at
            # yesterday said nothing about any of them.
            if past:
                serial.setdefault("seen", {})[station] = past[-1]["day"]
            if past or len(today) > 1:
                serial.setdefault("history", {})[station] = \
                    build_dailyexcel._numbered_history(past, today)
        serial["new"] = "seen" not in serial
        row[index["B"]] = serial
        if unit.get("pn"):
            row[index["C"]] = {"v": unit["pn"]}
        for key, _label, _pattern in STAGES:
            got = unit.get(key)
            if not got:
                continue
            offset = xlsx.column_index(slot_of[key])
            status = got["status"]
            if status == "pass":
                row[offset] = {"v": "Passed", "t": "pass"}
            elif status == "fail":
                row[offset] = {"v": "Failed", "t": "fail"}
            else:
                # Aborted, error, whatever else pega5 reports: shown, and
                # tallied as no verdict. A blank cell would read as "the rack
                # did not go through this stage today", which is false.
                row[offset] = {"v": status.title() or "—", "t": "abort"}
            # Attempts belong on the verdict, not appended to the suite
            # name: the suite name is what the release tally is matched
            # against, and a count glued to it would leak into that.
            tries = (attempts_of.get(dut) or {}).get(key, 1)
            if tries > 1:
                row[offset]["tries"] = tries
            row[offset + 1] = {"v": got["suite"]}
            if got["fail"]:
                row[offset + 2] = {"v": got["fail"]}
            row[offset + 3] = {"v": got["short"], "h": got["url"]}
        rows.append(row)

    return {
        "name": "{} (from pega5)".format(day),
        "label": day[5:],
        "day": day,
        "claimedUnits": None,
        "derived": True,
        "derivedFrom": {
            "runs": runs_seen,
            "source": "pega5",
            "versions": {},
            "note": "Rebuilt from pega5, which drives the L11 rack stations.",
        },
        "columns": columns,
        "rows": rows,
        "counts": _counts(rows, columns),
        "crossref": {"matched": 0, "duts": len(units)},
    }


def _counts(rows, columns) -> Dict[str, Any]:
    """Pass/fail per stage — the module tracker's tally, reused.

    Shared rather than reimplemented, for the same reason L10 shares it: three
    copies of this arithmetic would be three chances to count one day three
    ways on one page.
    """
    return build_dailyexcel._counts(rows, columns)
