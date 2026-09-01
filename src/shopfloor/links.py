"""Deep links, and a short list of the ones that do not exist.

THE RULE
--------
A link is built here only if somebody has watched it resolve. ``factory.links``
learned this the expensive way — an afternoon spent looking for a per-run OCP URL
that does not exist — and its conclusion is recorded there rather than
rediscovered here. A column of dead links is worse than a column of serials,
because a serial can be pasted into a search box and a 404 cannot.

Every template below was probed on 2026-09-01. A ``303`` to ``/login`` counts as
alive: these are links for a person with a browser session, not for a script.

WHAT LINKS, AND BY WHAT KEY
---------------------------
Almost everything is keyed by **serial**, not by run id, and that is the whole
reason these work. Search-by-serial is a supported route on every one of these
systems; per-run permalinks mostly are not.

    pega-sfis /lookup?sn=      the genealogy UI — what the line pastes in Slack
    pega-sfis /sheets/         the same unit as a sheet
    pega-sfis  export.xlsx     the receiver's own export
    pega3     /history/…?uut_sn=   every suite run pega3 saw for a unit
    SPLM      /tests/runs?q=   test sessions by serial

The pega3 and SPLM templates are not guesses: the receiver publishes them itself
on ``/api/pairs`` (``pv1_history_url``, ``splm_runs_url``), so they stay correct
if it changes them.

THE ONE PER-RUN LINK THAT DOES EXIST
------------------------------------
``http://<controller>:3000/suite_run/<suite_run_id>?slot_number=<n>`` — the same
URL ``factory.pega.run_url()`` builds, and the one the line's own tracker sheet
uses. It is available only for **controller** runs, because the id is minted by
the controller and appears in its run list. Which controller is a property of the
station (pega2 VBB, pega3 module, pega4 L10, pega5 L11, pega6 TIM) and comes from
``factory.stations``.

WHAT DOES NOT EXIST — DO NOT ADD THESE
--------------------------------------
* **A per-run OCP Logs URL.** Confirmed by observation: the RUNS tab holds its
  filter and selection in memory and the address bar never changes. Not a gap in
  this file; a fact about OCP. See ``factory.links`` before spending an afternoon
  on it.
* **An EOS run permalink.** EOS is an API, not a UI.
* **A pega4 suite-run link derived from an EOS run.** pega4 mints ids that appear
  nowhere in the EOS payload, so there is nothing to build the URL from. A
  controller-sourced run is a different matter — that is the case above.

For those, this module returns the serial-keyed search link instead, which is
what a person would have to do by hand anyway.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote

#: Overridable so a differently-addressed factory network does not need a patch.
SFIS_UI = os.environ.get("SHOPFLOOR_SFIS_UI", "https://pega-sfis").rstrip("/")
SPLM_UI = os.environ.get("SHOPFLOOR_SPLM_UI", "https://splm.i.etched.com").rstrip("/")
CONTROLLER_PORT = int(os.environ.get("SHOPFLOOR_CONTROLLER_PORT", "3000"))

#: The controller a station's runs live on. Read from ``factory.stations`` so the
#: two cannot disagree; the fallback is only for a station the registry has not
#: got a controller for yet, where no link is better than a wrong one.
def controller_for(station_key: Optional[str]) -> str:
    if not station_key:
        return ""
    try:
        from factory import stations as factory_stations
    except ImportError:  # pragma: no cover - factory is a sibling package
        return ""
    for entry in factory_stations.registry():
        if entry.get("key") == station_key:
            return str(entry.get("controller") or "")
    return ""


def for_serial(sn: str) -> Dict[str, str]:
    """Every by-serial link for one part. All of them, or none — a partial set
    reads as "this part has no SPLM record" rather than "we did not look"."""
    if not sn:
        return {}
    safe = quote(str(sn), safe="")
    return {
        "sfis": f"{SFIS_UI}/lookup?sn={safe}",
        "sfis_sheet": f"{SFIS_UI}/sheets/{safe}",
        "sfis_xlsx": f"{SFIS_UI}/api/serial/{safe}/export.xlsx",
        "controller_history": f"http://pega3:{CONTROLLER_PORT}/history/data-analysis?uut_sn={safe}",
        "splm": f"{SPLM_UI}/tests/runs?q={safe}",
    }


def suite_run(run_id: str, station_key: str = "", host: str = "") -> str:
    """The controller's own page for one suite run, slot included when the run
    id carries it.

    ``pega_collect`` encodes a fixture's eight units as ``<run_id>#slot<n>`` so
    two slots of one run cannot collide as records. That suffix is this repo's,
    not the controller's, so it is split back off before building the URL and
    re-attached as the ``slot_number`` query the controller understands.
    """
    if not run_id:
        return ""
    slot = None
    if "#slot" in run_id:
        run_id, _, raw = run_id.partition("#slot")
        slot = raw.strip() or None
    host = host or controller_for(station_key)
    if not host:
        return ""
    url = f"http://{host}:{CONTROLLER_PORT}/suite_run/{quote(run_id, safe='')}"
    if slot is not None:
        url += f"?slot_number={quote(slot, safe='')}"
    return url


def for_record(record: Dict[str, Any]) -> Dict[str, str]:
    """Links for one test record, by source.

    Only a controller record gets a per-run link. An EOS record gets the search
    links for its DUT instead, stated as such, because EOS has no UI and OCP has
    no per-run route.
    """
    out: Dict[str, str] = {}
    source = record.get("source")
    if source == "controller":
        url = suite_run(str(record.get("run_id") or ""), str(record.get("station_key") or ""))
        if url:
            out["run"] = url
    dut = str(record.get("dut_sn") or "")
    if dut:
        by_serial = for_serial(dut)
        out["controller_history"] = by_serial["controller_history"]
        out["splm"] = by_serial["splm"]
    return out


def templates() -> Dict[str, str]:
    """The same links as ``{sn}`` templates, for the browser to expand.

    Shipped once instead of expanded per node: a 2,000-node bundle carrying five
    URLs each is megabytes of nearly identical text, and the substitution is one
    line of JavaScript.
    """
    return {
        "sfis": f"{SFIS_UI}/lookup?sn={{sn}}",
        "sfis_sheet": f"{SFIS_UI}/sheets/{{sn}}",
        "sfis_xlsx": f"{SFIS_UI}/api/serial/{{sn}}/export.xlsx",
        "controller_history": f"http://pega3:{CONTROLLER_PORT}/history/data-analysis?uut_sn={{sn}}",
        "splm": f"{SPLM_UI}/tests/runs?q={{sn}}",
        "suite_run": f"http://{{host}}:{CONTROLLER_PORT}/suite_run/{{run}}",
    }
