"""A read-only client for the TY2 receiver (``pega-sfis``).

WHAT THE RECEIVER IS
--------------------
Pega POSTs two payload families to it hourly — ``/linking`` (parent + component
list, LINK/DELINK) and ``/process`` (one row per station visit). The receiver
journals every payload to disk *before* parsing, then indexes it into SQLite;
the derived read endpoints used here are views over that index.

WHAT THAT MEANS FOR US
----------------------
1. **Pega has no query API.** As of 2026-08-25 it is item 4 on Pegatron's
   roadmap, TBD, and has been an open ask for months. So this receiver is the
   only way to ask "what is under serial X", and if it is down there is no
   upstream to fall back to. That is the entire argument for mirroring.
2. **The index is rebuildable, the journal is not.** Krish's own design note.
   Our snapshots are the same bet one layer out.
3. **Only Etched-numbered serials carry process events.** Verified 2026-08-31
   across a live L11 rack and a live 6U: all 21 rack-level parts
   (``JCS0R…``, ``JPN…``, ``28G5…``, PDU, MFH) return **zero** process events,
   while the Etched-numbered ``ND`` node and ``DUB`` PV1 return 7 and 3. This is
   not a bug and not missing data — Pega routes assemblies it serialized, and
   vendor barcodes are scanned in, never tested by SN. ``graph.py`` turns that
   into an explicit ``none_expected`` verdict rather than an empty list.

ENDPOINTS USED, AND WHY EACH
----------------------------
``/api/serial/{sn}``   everything about one serial in one call: process events,
                       genealogy as parent and as child, the recursive
                       ``current_tree``, MACs, inferred replacements. This is
                       the workhorse; one call per node.
``/api/pairs``         Sohu board <-> PV1. The bridge that makes a *part* SN
                       testable: the ``JE607…`` interposer serial is the DUT
                       serial EOS files MLT under.
``/api/units``         the serials at a product level, so a mirror can be told
  ``/api/levels``      "every L11" instead of a hand-typed list.
``/api/recent``        payload freshness. A snapshot that cannot say how current
                       the upstream was is an undated photograph.
``/api/health``        needs the *write* token, so it is probed but never
                       required.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

from . import config
from .http import Response, get


def _segment(value: str) -> str:
    """Percent-encode one path segment.

    Not defensive boilerplate — real serials contain spaces. The Sohu stiffener
    is recorded as ``1006470-H 202606260068`` (part number, space, date-serial),
    and ``urllib`` refuses a URL with a raw space outright, so five parts per 4U
    node silently arrived with no attributes at all until this was added.
    Encoding and letting the receiver decide what the serial means is correct;
    stripping or splitting it here would be this tool inventing a canonical form
    that the receiver does not share.
    """
    return urllib.parse.quote(str(value), safe="")


def _auth() -> Dict[str, Any]:
    """Bearer if we have one, basic otherwise.

    Both are documented read paths on the receiver. A token is preferred because
    a read token cannot write; basic auth stays because it is what the team
    actually has in hand today.
    """
    if config.SFIS_TOKEN:
        return {"token": config.SFIS_TOKEN}
    return {"basic": (config.SFIS_USER, config.SFIS_PASSWORD)}


def call(path: str, *, retries: int = 0, **params: Any) -> Response:
    return get(
        f"{config.SFIS_BASE}{path}",
        params=params or None,
        verify=config.SFIS_VERIFY,
        retries=retries,
        **_auth(),
    )


# --- the calls ---------------------------------------------------------------


def serial(sn: str) -> Response:
    """Everything the receiver holds about one serial."""
    # Retried: a mirror walks ~100 serials and one transient timeout would drop
    # a whole branch's attributes from the snapshot.
    return call(f"/api/serial/{_segment(sn)}", retries=2)


def pairs(sns: str = "") -> Response:
    """Sohu board <-> PV1 pairs. ``sns`` filters, and expands a higher-level SN
    to every PV1 beneath it."""
    return call("/api/pairs", retries=2, sns=sns)


def levels() -> Response:
    return call("/api/levels")


def units(level: str) -> Response:
    return call("/api/units", level=level)


def recent(limit: int = 5, sn_limit: int = 0) -> Response:
    return call("/api/recent", limit=limit, sn_limit=sn_limit)


def identifiers(sn: str) -> Response:
    """RMS / TOR / MSW / PDU / NIC records under a top-level serial, with MACs.

    Mostly redundant with a full tree walk — but not entirely: it is the
    receiver's own opinion about which identifiers matter at rack level, it
    resolves NIC records at any depth, and it names a ``product_level``. Mirrored
    for roots that parent an ``RMS*`` slot, which is the receiver's own
    structural test for "this is an L11 rack".
    """
    return call(f"/api/serial/{_segment(sn)}/identifiers")


# --- shapes -----------------------------------------------------------------


def tree_nodes(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten ``current_tree`` into (depth, path, node) records, depth-first.

    ``current_tree`` nests, and nesting is real: a 6U reaches its motherboard
    through ``DUT -> MAD -> CA -> MB`` and its PV1s through a nested DUT. Live
    shapes go three levels deep with ~100 nodes, so a walk is cheap — but it
    must be a walk. Every "check one level down" version of this in the
    receiver's own history classified whole product families as neither 6U nor
    2U (see ty2-receiver ARCHITECTURE.md §6).
    """
    out: List[Dict[str, Any]] = []

    def walk(node: Dict[str, Any], depth: int, path: tuple) -> None:
        for child in node.get("children") or []:
            here = path + (child.get("slot") or child.get("component_type") or "?",)
            out.append({"depth": depth + 1, "path": here, "node": child})
            walk(child, depth + 1, here)

    root = payload.get("current_tree") or {}
    walk(root, 0, ())
    return out


def process_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """SFIS process events, normalised to this repo's test-record shape."""
    records = []
    for event in payload.get("process_events") or []:
        records.append(
            {
                "ts": event.get("process_ts"),
                "station": event.get("station"),
                "result": event.get("result"),
                "route": event.get("route"),
                "section": event.get("section"),
                "line": event.get("line"),
                "source": "sfis",
            }
        )
    records.sort(key=lambda r: (r["ts"] or "", r["station"] or ""))
    return records
