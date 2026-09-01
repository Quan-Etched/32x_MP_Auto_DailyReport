"""Compile a snapshot into the browser bundle the traceability tree renders from.

WHY A BUNDLE AND NOT A FETCH PER SERIAL
---------------------------------------
The dashboard is a static directory — nginx or Pages, no server of its own — and
every other page here ships pre-aggregated data for the same reason. A tree walk
that fetched a serial at a time would need an API that does not exist on the
published copy, and would break the moment ``pega-sfis`` was unreachable, which
is precisely when somebody is looking a unit up.

SHORT KEYS IN ``nodes``
-----------------------
``nodes`` is the widest structure in the bundle — every serial in every mirrored
tree, ~100 per 6U — and the same precedent applies as in ``factory.build_runs``:
short keys there, readable keys everywhere else. The legend is ``NODE_KEYS``
below and it is also emitted into the bundle, so the page and this file cannot
drift on what ``c`` means.

WHAT IS DELIBERATELY *NOT* IN HERE
----------------------------------
**Controller runs.** ``customize.html`` already loads the full run bundle for its
range and serial views, so the page has every controller run in memory keyed by
``dutSerial``. Copying them in here would add megabytes to say a second time what
is already loaded, and the copy would go stale against whichever runs bundle the
page actually has. So the bundle ships ``controllers`` — the stationKey → ESVM
host map — and the page joins and builds ``/suite_run/`` URLs itself.

The YAML is a different case: it has no page around it, so ``cli.py`` folds
controller runs into it server-side via :func:`controller_runs_by_dut`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import graph as graph_mod, links as links_mod, mirror, render

#: The legend for ``nodes``. Emitted into the bundle as well as documented here.
NODE_KEYS = {
    "u": "top-level unit serial this node belongs to",
    "p": "parent serial ('' for the unit itself)",
    "s": "slot label within the parent",
    "t": "component type (DI, LAN, DUB, BO, …)",
    "n": "component name as Pega sent it",
    "m": "manufacture part number",
    "e": "etched part number",
    "a": "MAC addresses",
    "l": "linked_at — when Pega says the part was fitted",
    "c": "coverage: tested | process_only | inherited_only | none_expected | not_observed",
    "g": "1 when traceability_gap — serialized by Pega, no route history",
    "k": "child serials",
    "r": "records: [ts, station, result, source, kind, runId, release, stationKey]",
    "h": "inherited records, same shape, plus the ancestor serial in place of runId",
}

#: Record tuple positions, so the page indexes by name rather than by number.
RECORD_FIELDS = ("ts", "station", "result", "source", "kind", "run", "release", "sk")


def _record_tuple(entry: Dict[str, Any]) -> List[Any]:
    return [
        entry.get("ts") or "",
        entry.get("station") or "",
        entry.get("result") or "",
        entry.get("source") or "",
        entry.get("kind") or "",
        entry.get("run_id") or entry.get("on") or "",
        entry.get("release") or entry.get("suite") or "",
        entry.get("station_key") or "",
    ]


def controller_runs_by_dut(dashboard_data: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Controller runs from whichever run bundle ``make build`` last wrote.

    Read off disk rather than re-collected: a fresh ESVM sweep is minutes of
    network for records the last build already has, and this is a rendering step.
    Absent bundle -> empty dict, and the caller renders without them.

    ``runs_pega.js`` is preferred over ``runs.js`` because the controller bundle
    is one record per *unit* where the EOS one is one per *fixture* — the whole
    reason ``factory.pega_collect`` exists.
    """
    for name in ("runs_pega.js", "runs.js"):
        path = dashboard_data / name
        if not path.is_file():
            continue
        try:
            text = path.read_text()
            payload = json.loads(re.sub(r"^[^{]*", "", text).rstrip().rstrip(";"))
        except (OSError, ValueError):
            continue
        if payload.get("source") != "pega" and name == "runs.js":
            # runs.js is the EOS-sourced bundle; its runs are already collected
            # straight from EOS by the mirror, so re-reading them here would
            # double every record.
            return {}
        labels = payload.get("stationLabels") or {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for run in payload.get("runs") or []:
            dut = str(run.get("d") or "")
            if not dut:
                continue
            started = run.get("t")
            out.setdefault(dut, []).append({
                "runId": run.get("i"),
                "dutSerial": dut,
                "stationKey": run.get("k"),
                "suite": labels.get(run.get("k")) or run.get("su"),
                "status": run.get("s"),
                "startedAt": (
                    datetime.fromtimestamp(started, timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ") if started else ""
                ),
            })
        return out
    return {}


def build(
    snapshot: mirror.Snapshot,
    *,
    controller_by_dut: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    with_yaml: bool = True,
) -> Dict[str, Any]:
    """One bundle from one snapshot: every mirrored unit, every node beneath it."""
    serials = snapshot.serials()
    eos_by_dut = snapshot.eos_by_dut()
    verdicts = snapshot.verdicts()
    controller_by_dut = controller_by_dut or {}

    if verdicts:
        for runs in eos_by_dut.values():
            for run in runs:
                found = verdicts.get(run.get("runId"))
                if isinstance(found, dict):
                    run["result"] = found.get("result", "unknown")

    # A root is a serial nothing else in the snapshot parents. Derived rather
    # than taken from sfis_scope.roots, because a mirror seeded with a mid-tree
    # serial still produces a tree and that tree's own top is the useful root.
    parented = set()
    for payload in serials.values():
        for child in payload.get("current_tree", {}).get("children") or []:
            parented.add(str(child.get("serial") or ""))
        for entry in payload.get("current_children") or []:
            parented.add(str(entry.get("component_sn") or ""))
    roots = [sn for sn in serials if sn not in parented]

    nodes: Dict[str, Any] = {}
    units: List[Dict[str, Any]] = []
    yaml_texts: Dict[str, str] = {}

    for root in sorted(roots):
        built = graph_mod.build(
            root, serials=serials, eos_by_dut=eos_by_dut,
            controller_by_dut=controller_by_dut,
        )
        parts = built["parts"]
        children_of: Dict[str, List[str]] = {}
        for part in parts:
            children_of.setdefault(part.parent_sn, []).append(part.sn)

        nodes[root] = {
            "u": root, "p": "", "s": "", "t": "", "n": "",
            "c": "unit", "k": children_of.get(root, []),
            "r": [_record_tuple(r) for r in built["root_direct"]],
        }
        for part in parts:
            node = {
                "u": root,
                "p": part.parent_sn,
                "s": part.slot,
                "t": part.component_type,
                "n": part.component_name,
                "c": part.coverage,
                "k": children_of.get(part.sn, []),
                "r": [_record_tuple(r) for r in part.direct],
            }
            if part.mpn:
                node["m"] = part.mpn
            if part.epn:
                node["e"] = part.epn
            if part.macs:
                node["a"] = part.macs
            if part.linked_at:
                node["l"] = part.linked_at
            if part.traceability_gap:
                node["g"] = 1
            if part.inherited:
                node["h"] = [_record_tuple(r) for r in part.inherited]
            # A serial can legitimately appear under two parents in different
            # units. Last writer wins for the node body, but every unit it
            # appears in is recorded so the page can say so instead of showing
            # one and hiding the other.
            existing = nodes.get(part.sn)
            if existing and existing.get("u") != root:
                also = set(existing.get("also") or []) | {existing["u"], root}
                node["also"] = sorted(also)
            nodes[part.sn] = node

        tally = graph_mod.counts(built)
        units.append({
            "sn": root,
            "parts": tally.get("parts", 0),
            "tested": tally.get("tested", 0),
            "gaps": tally.get("traceability_gap", 0),
        })
        if with_yaml:
            document = render.document(
                built, manifest=snapshot.manifest, serials=serials
            )
            yaml_texts[root] = render.to_text(document)

    manifest = snapshot.manifest
    from factory import stations as factory_stations

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot": {
            "id": manifest.get("id"),
            "takenAt": manifest.get("taken_at"),
            "sfisPayloadsThrough": manifest.get("sfis_payloads_through"),
            "eosWindow": manifest.get("eos_window"),
        },
        "warnings": render.warnings(manifest),
        "nodeKeys": NODE_KEYS,
        "recordFields": list(RECORD_FIELDS),
        "linkTemplates": links_mod.templates(),
        # stationKey -> ESVM host, so the page builds /suite_run/ URLs for the
        # controller runs it already has loaded without a second source of truth.
        "controllers": {
            entry["key"]: entry.get("controller") or ""
            for entry in factory_stations.registry()
            if entry.get("controller")
        },
        "stationLabels": {
            entry["key"]: entry.get("label") or entry["key"]
            for entry in factory_stations.registry()
        },
        "units": sorted(units, key=lambda u: u["sn"]),
        "nodes": nodes,
        "yaml": yaml_texts,
    }


def write(bundle: Dict[str, Any], path: Path) -> Path:
    """Write the bundle, and the per-unit YAML beside it as separate files.

    The YAML does NOT travel inside the bundle. It was, and at production scale
    that was 1.8 MB of text nobody reads unless they click Download -- on a page
    that already ships a 9.5 MB run bundle and takes minutes to become
    interactive over the VPN. Sitting in `data/trace/<sn>.yaml`, it costs
    nothing until somebody asks for it, and the download button becomes an
    ordinary link.

    Same text either way: both come from `render.to_text`, so the file and what
    `make sfis-unit` writes cannot disagree.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    texts = bundle.pop("yaml", {}) or {}
    yaml_dir = path.parent / "trace"
    if texts:
        yaml_dir.mkdir(parents=True, exist_ok=True)
        for unit, text in texts.items():
            (yaml_dir / f"{unit}.yaml").write_text(text)
        bundle["yamlPath"] = f"{yaml_dir.name}/{{sn}}.yaml"
        bundle["yamlUnits"] = sorted(texts)

    body = json.dumps(bundle, separators=(",", ":"), sort_keys=True)
    path.write_text(
        "// Generated by `python -m shopfloor trace` — do not edit.\n"
        "window.__FACTORY_TRACE__ = " + body + ";\n"
    )
    return path
