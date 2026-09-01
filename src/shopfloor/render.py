"""The YAML: one file per top-level serial, the shape a failure report needs.

THE SHAPE, AND WHY
------------------
``parts`` nests, mirroring the physical assembly, because the question being
asked is *where in this product*. A flat list of 100 serials cannot answer "what
else is on the tray that failed"; a tree can, at a glance.

Each part is keyed by its **slot**, not its serial. Three reasons:

* The slot is unique per parent — the receiver enforces exactly one active
  component per (parent, slot), which is its load-bearing invariant. Serial is
  *not* unique in the file: the same vendor barcode can legitimately appear in
  two different parents.
* The slot is what the image on the line shows, and what an operator says.
* A replaced part changes the serial and keeps the slot, so slot-keyed files
  diff into "``RMS1`` serial changed" instead of "one key vanished, another
  appeared".

``part_index`` then maps serial -> slot path, so finding a part by serial is one
grep and not a tree walk. It is redundant on purpose: this file is read during
an outage, by someone who has a serial and needs the rest.

Every part carries ``coverage`` before its records, so the first thing read is
whether an empty list means *nothing tested this* or *we could not look*.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import graph as graph_mod
from . import links as links_mod
from . import yamlout

#: Keys whose list values are one record per line.
FLOW = ("test_records", "inherited_records", "process_records", "macs",
        "replacements")


def _record(entry: Dict[str, Any]) -> Dict[str, Any]:
    """A test record, field order chosen for reading: when, where, what happened."""
    out: Dict[str, Any] = {
        "ts": entry.get("ts"),
        "station": entry.get("station"),
        "result": entry.get("result"),
        "source": entry.get("source"),
    }
    for key in ("kind", "suite", "release", "run_id", "level", "route", "section",
                "line", "slot_number", "on", "via", "fixture_scope", "failed_tests"):
        if entry.get(key) not in (None, "", [], False):
            out[key] = entry[key]
    # The raw-data link, inline on the record rather than in a table somewhere
    # else. A verdict without a way to reach what produced it is where a failure
    # investigation stalls, and this is the one per-run URL that exists.
    run_url = links_mod.for_record(entry).get("run")
    if run_url:
        out["raw"] = run_url
    return out


#: Per-serial provenance for the document being rendered. Module-level because
#: `_part` is called recursively and threading it through every frame for one
#: optional link would be worse than a value set once per document.
_INDEX: Dict[str, Any] = {}


def _part(part: graph_mod.Part) -> Dict[str, Any]:
    body: Dict[str, Any] = {"sn": part.sn}
    if part.component_type:
        body["type"] = part.component_type
    if part.component_name:
        body["name"] = part.component_name
    if part.mpn:
        body["mpn"] = part.mpn
    if part.epn:
        body["epn"] = part.epn
    if part.raw_location not in (None, ""):
        body["location"] = part.raw_location
    if part.slot_confidence and part.slot_confidence != "location":
        # Only worth the line when the position is *not* something Pega sent.
        body["slot_confidence"] = part.slot_confidence
    if part.linked_at:
        body["linked_at"] = part.linked_at
    if part.macs:
        body["macs"] = part.macs

    # By-serial links for every part, always the full set. A partial set reads
    # as "this part has no SPLM record" rather than "we did not look" -- these
    # are search URLs, so they resolve whether or not the system holds anything.
    body["links"] = links_mod.for_serial(part.sn, _INDEX.get(part.sn))
    body["coverage"] = part.coverage
    if part.traceability_gap:
        body["traceability_gap"] = True
    if part.subtree:
        body["subtree"] = dict(sorted(part.subtree.items()))
    body["test_records"] = [_record(r) for r in part.direct]
    if part.inherited:
        body["inherited_records"] = [_record(r) for r in part.inherited]
    if part.children:
        body["parts"] = {child.slot: _part(child) for child in part.children}
    return body


def _nest(parts: List[graph_mod.Part]) -> Dict[str, graph_mod.Part]:
    """Rebuild parent/child links from the flat part list, keyed by slot."""
    by_path = {part.path: part for part in parts}
    roots: Dict[str, graph_mod.Part] = {}
    for part in parts:
        part.children = []
    for part in parts:
        parent = by_path.get(part.path[:-1]) if len(part.path) > 1 else None
        if parent is not None:
            parent.children.append(part)
        else:
            roots[part.slot] = part
    return roots


def warnings(manifest: Dict[str, Any]) -> List[str]:
    """Everything about this snapshot that should change how the file is read.

    In the manifest already, but a manifest is a place a reader has to think to
    look. This list goes near the top of the document and is echoed to the
    terminal, because the failure mode is specific and was observed: one EOS
    level timed out, the file lost 8 of its 22 tested parts, and nothing about it
    looked wrong. A file that is quietly incomplete is worse than one that
    refuses to render.
    """
    out: List[str] = []
    sources = manifest.get("sources") or {}

    sfis_source = sources.get("sfis") or {}
    if not sfis_source.get("ok", True):
        out.append("SFIS: unavailable — topology is from an earlier snapshot or absent")
    failed = sfis_source.get("serials_failed") or 0
    if failed:
        out.append(
            f"SFIS: {failed} serial lookup(s) failed — those parts render as "
            f"coverage: not_observed, and are NOT counted as gaps. Re-mirror"
        )

    eos_source = sources.get("eos") or {}
    if not eos_source.get("ok", True):
        out.append(
            f"EOS: unavailable ({eos_source.get('reason', 'unknown')}) — "
            f"NO Etched test records in this file"
        )
    else:
        broken = sorted(
            level for level, state in (eos_source.get("levels") or {}).items()
            if not state.get("ok")
        )
        if broken:
            out.append(
                "EOS: level(s) " + ", ".join(broken) + " did not answer — test "
                "records from those levels are missing, not absent"
            )
        if not eos_source.get("verdicts_resolved"):
            out.append(
                "EOS: verdicts not resolved — every eos record reads "
                "result: unknown. Re-mirror with VERDICTS=1"
            )

    if not (manifest.get("sfis_scope") or {}).get("levels_swept"):
        out.append(
            "scope: roots only, no level sweep — cross-source gap checks are "
            "limited (see make gaps)"
        )
    return out


def document(
    built: Dict[str, Any],
    *,
    manifest: Dict[str, Any],
    product_level: str = "",
    serials: Optional[Dict[str, Any]] = None,
    serial_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    global _INDEX
    _INDEX = serial_index or {}
    parts: List[graph_mod.Part] = built["parts"]
    roots = _nest(parts)

    tally = graph_mod.counts(built)
    findings = graph_mod.gaps(built)

    out: Dict[str, Any] = {
        "unit": built["root"],
        "product_level": product_level or None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # The provenance block is not decoration. A file that cannot say which
        # sources answered, and how current they were, cannot be trusted six
        # weeks later during an FA — and "six weeks later during an FA" is the
        # only time anyone opens it.
        # Read this before anything below it.
        "warnings": warnings(manifest),
        "sources": manifest.get("sources", {}),
        "snapshot": {
            "id": manifest.get("id"),
            "taken_at": manifest.get("taken_at"),
            "sfis_payloads_through": manifest.get("sfis_payloads_through"),
            "eos_window": manifest.get("eos_window"),
        },
        "summary": {
            "parts": tally.get("parts", 0),
            "tested": tally.get("tested", 0),
            "process_only": tally.get("process_only", 0),
            "inherited_only": tally.get("inherited_only", 0),
            "none_expected": tally.get("none_expected", 0),
            "not_observed": tally.get("not_observed", 0),
            "traceability_gap": tally.get("traceability_gap", 0),
        },
        "self": {
            "sn": built["root"],
            "links": links_mod.for_serial(built["root"], _INDEX.get(built["root"])),
            "test_records": [_record(r) for r in built["root_direct"]],
        },
        "parts": {slot: _part(part) for slot, part in roots.items()},
        # Parts that have left this unit. Flat and top-level: a removed part has
        # no node in the current tree to hang it on, and nesting it under the
        # slot's current occupant would read as that occupant's history.
        "replacements": graph_mod.history(built, serials or {}),
        "findings": findings,
    }
    return out


HEADER = (
    "Local shopfloor topology + test records — generated, do not hand-edit.",
    "One file per top-level serial. Rebuild with: make sfis-unit SN=<serial>",
    "",
    "coverage:  tested          a test names this part SN directly",
    "           process_only    SFIS route/assembly events only, no test",
    "           inherited_only  no test names it; ancestors were tested while it",
    "                           was installed (window-bounded)",
    "           none_expected   vendor part no station tests by SN — not a gap",
    "           not_observed    this snapshot never fetched the part, so its own",
    "                           records are UNKNOWN, not empty. Any",
    "                           inherited_records shown are still real. Re-mirror.",
    "",
    "traceability_gap: true  Pega serialized this part but has no route history",
    "                        for it — an escape, independent of coverage above.",
    "",
    "links:      by-serial searches that always resolve (SFIS UI, controller",
    "            history, SPLM). `raw:` on a record is the controller's own page",
    "            for that run — the only per-run URL that exists. EOS has no UI",
    "            and OCP Logs has no per-run route, so those records carry the",
    "            by-serial links instead.",
)


def to_text(document: Dict[str, Any]) -> str:
    return yamlout.dumps(document, header=HEADER, flow_lists=FLOW)
