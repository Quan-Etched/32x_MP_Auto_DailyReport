"""Etched's own test records, from the EOS external test-log API.

WHY THIS IS A SEPARATE SOURCE FROM SFIS
---------------------------------------
SFIS ``process_events`` tell you a unit *visited a station and passed*. They are
Pega's route events: ``Assy1``, ``TIM Dispensing``, ``AQC``, ``PACK``, ``SHIP``,
one bit each. They do not carry a measurement, a failed test name, or a software
release. Everything that answers "why did it fail" is in EOS.

So a part SN's test history is the union of two vocabularies, and this module
supplies the half that has detail. See ``docs/JOIN.md`` for the full table.

THE JOIN THAT MAKES PART-LEVEL TEST RECORDS POSSIBLE
----------------------------------------------------
Verified live 2026-08-31, and it is the finding this whole tool is built on:

    EOS level=slt, suite=mlt, dutSerial=JE60701695202602090204

``JE607…`` is not a unit serial. It is the **Sohu interposer board barcode** —
the same string SFIS files as a ``BO`` component under a PV1 (``DUB``). So for
the Sohu module, the DUT that EOS tests *is* a part SN in the genealogy, and a
part SN gets a real test record with a timestamp, a station, a release and a
verdict. Cross-checking August: of 282 distinct SLT-level DUTs, **233 are
present in SFIS genealogy and 49 are not** — and those 49 are exactly the
"no ASIC SN linked in SFIS" class of escape that has been chased by email
one serial at a time since June.

WHAT EOS WILL NOT GIVE YOU
--------------------------
* **No status on ``/runs``.** Seven fields, and status is not among them. The
  verdict is only in the ``event_stream`` artifact (``testRunEnd``), which costs
  two more calls per run. ``verdict()`` fetches it; ``runs()`` does not, and a
  record whose verdict was not fetched says ``result: unknown`` rather than
  guessing ``pass``.
* **No station or fixture field, at any level.** Station is derived from
  (level, suite) through ``stations.py``.
* **One run per fixture, eight modules.** A ``fail`` on an MLT run means at
  least one of eight chips failed, not that all eight did. Attributing it to a
  slot needs the ESVM controller; until then the record carries
  ``fixture_scope: true`` so nobody reads it as a per-part verdict.

Do not fetch the ``resource_config`` role. It holds cleartext DUT SSH and BMC
credentials and no station identity — nothing to gain, a secret to leak.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import config
from .http import Response, get

#: Every level EOS serves. l11 is listed but its bucket is not readable with the
#: current key — asked for anyway, so the manifest records the refusal instead of
#: the tool quietly implying L11 has no tests.
LEVELS = ("l6", "l10", "l11", "slt", "module", "bringup")

#: Artifact roles that must never be requested. See the module docstring.
NEVER_FETCH = frozenset({"resource_config"})


#: A level sweep is a far bigger query than a single lookup — ``slt`` alone
#: returned 1,740 runs over a 120-day window — and the default timeout is sized
#: for lookups. Given its own value because raising the global one would make
#: every failure slower to discover.
SWEEP_TIMEOUT = float(os.environ.get("SHOPFLOOR_EOS_SWEEP_TIMEOUT", "180"))


def _call(path: str, *, timeout: Any = None, retries: int = 0, **params: Any) -> Response:
    return get(
        f"{config.EOS_BASE}{path}",
        params=params or None,
        token=config.EOS_API_KEY,
        ca_bundle=config.EOS_CA_BUNDLE,
        timeout=timeout,
        retries=retries,
    )


def available() -> bool:
    return bool(config.EOS_API_KEY)


def levels() -> Response:
    """``/levels`` — also the cheapest possible credential + reachability check."""
    return _call("/levels")


def window(days: Optional[int] = None) -> tuple:
    """The (from, to) instants to ask for, as EOS wants them.

    ``from``/``to`` are both inclusive. The window is returned to the caller so
    it can be written into the snapshot manifest: without it, "this part has no
    test records" is indistinguishable from "we only looked back 120 days".
    """
    days = config.EOS_DAYS if days is None else days
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return (
        (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def runs(
    level: str,
    *,
    dut: str = "",
    since: str = "",
    until: str = "",
    timeout: Any = None,
    retries: int = 0,
) -> Response:
    """``/runs`` for one level, optionally one DUT.

    Called per level rather than per serial: a level sweep over the window is one
    request that covers every part SN at once, where per-serial calls would be
    one request per node — hundreds per rack. The sweep is also what lets the
    gap report see DUTs that EOS tested and SFIS has never heard of, which a
    per-serial lookup structurally cannot find.
    """
    return _call(
        "/runs", timeout=timeout, retries=retries,
        level=level, dutSerial=dut, **{"from": since, "to": until},
    )


def sweep(since: str, until: str) -> Dict[str, Any]:
    """Every run at every level in the window, indexed by DUT serial.

    Returns ``{"by_dut": {sn: [run, ...]}, "levels": {level: status}}``. A level
    that refuses is recorded, not raised: an unreadable l11 bucket must not cost
    us the l10 and slt records that did come back.
    """
    by_dut: Dict[str, List[Dict[str, Any]]] = {}
    status: Dict[str, Any] = {}
    for level in LEVELS:
        response = runs(
            level, since=since, until=until,
            timeout=SWEEP_TIMEOUT, retries=2,
        )
        if not response.ok:
            # Recorded, not raised: an unreadable l11 bucket must not cost us the
            # l10 and slt records that did come back. `partial` is what the
            # renderer turns into a visible warning.
            status[level] = {"ok": False, "error": response.error}
            continue
        found = (response.data or {}).get("runs") or []
        status[level] = {"ok": True, "runs": len(found)}
        for run in found:
            run = dict(run, level=run.get("level") or level)
            by_dut.setdefault(run.get("dutSerial") or "", []).append(run)
    return {"by_dut": by_dut, "levels": status}


def verdict(level: str, dut: str, run_id: str) -> Dict[str, Any]:
    """Resolve one run's pass/fail from its ``event_stream``, plus failed tests.

    Two calls: ``/artifacts`` to find the roles, ``/artifact-content`` to read
    them. Expensive per run, which is why the CLI makes it opt-in and the
    snapshot caches the answer forever — a finished run's verdict never changes.
    """
    out: Dict[str, Any] = {"result": "unknown", "failed_tests": []}
    listing = _call("/artifacts", level=level, dutSerial=dut, runId=run_id)
    if not listing.ok:
        out["error"] = listing.error
        return out

    roles = {}
    for artifact in (listing.data or {}).get("artifacts") or []:
        role = artifact.get("role")
        if role and role not in NEVER_FETCH:
            roles.setdefault(role, artifact.get("relPath"))

    # The suite summary names what failed. Cheaper and more useful than the
    # event stream for the "which test" question, so it is read first.
    if "suite_summary" in roles:
        summary = get(
            f"{config.EOS_BASE}/artifact-content",
            params={
                "level": level,
                "dutSerial": dut,
                "runId": run_id,
                "relPath": roles["suite_summary"],
            },
            token=config.EOS_API_KEY,
            ca_bundle=config.EOS_CA_BUNDLE,
        )
        if summary.ok and isinstance(summary.data, list):
            failed = [
                entry.get("unique_id") or entry.get("test_name")
                for entry in summary.data
                if str(entry.get("status", "")).upper() in {"FAILED", "ERROR", "TIMEOUT"}
            ]
            out["failed_tests"] = [name for name in failed if name][:20]
            out["tests"] = len(summary.data)
            # A summary with a FAILED entry is a fail regardless of what the
            # event stream says; INTERRUPTED entries on an aborted run are not.
            out["result"] = "fail" if out["failed_tests"] else "pass"

    # The event stream is the only authority on the run verdict, so it overrides.
    if "event_stream" in roles:
        stream = get(
            f"{config.EOS_BASE}/artifact-content",
            params={
                "level": level,
                "dutSerial": dut,
                "runId": run_id,
                "relPath": roles["event_stream"],
            },
            token=config.EOS_API_KEY,
            ca_bundle=config.EOS_CA_BUNDLE,
            as_json=False,
        )
        if stream.ok:
            out.update(_parse_event_stream(stream.text))
    return out


def _parse_event_stream(text: str) -> Dict[str, Any]:
    """Pull the run verdict and duration out of OCP ``log.jsonl``.

    ``testRunEnd.status`` is COMPLETE / ERROR / SKIP and ``.result`` is
    PASS / FAIL / NOT_APPLICABLE; the pair, not either alone, is the verdict.
    """
    import json

    started = ended = None
    result: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "testRunStart" in event:
            started = event.get("timestamp") or started
        end = event.get("testRunEnd")
        if isinstance(end, dict):
            ended = event.get("timestamp") or ended
            status = str(end.get("status", "")).upper()
            verdict_value = str(end.get("result", "")).upper()
            if status in {"ERROR"}:
                result["result"] = "error"
            elif verdict_value == "PASS":
                result["result"] = "pass"
            elif verdict_value == "FAIL":
                result["result"] = "fail"
            elif status == "SKIP":
                result["result"] = "skip"
            result["run_status"] = status or None
    if started:
        result["started_at"] = started
    if ended:
        result["ended_at"] = ended
    return result
