"""``python3 -m shopfloor <command>`` — four verbs, one of which needs no network.

    doctor              can we reach each source, and with what credential
    mirror  SN...       snapshot the upstreams for these roots (or a whole level)
    unit    SN          render one YAML from a snapshot          [offline]
    gaps                the findings across a snapshot           [offline]

``unit`` and ``gaps`` read only the snapshot directory. That separation is the
product: during an outage the answer still comes out, from the last snapshot,
and the file says how old it is.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import config, eos, graph as graph_mod, mirror, render, sfis


def _resolve_roots(args) -> List[str]:
    roots = list(args.serial or [])
    if args.level:
        response = sfis.units(args.level)
        if not response.ok:
            print(f"! /api/units?level={args.level}: {response.error}", file=sys.stderr)
        else:
            roots.extend((response.data or {}).get("serials") or [])
    return list(dict.fromkeys(roots))


def cmd_doctor(args) -> int:
    print(f"sfis   {config.SFIS_BASE}")
    cred = "bearer token" if config.SFIS_TOKEN else f"basic ({config.SFIS_USER})"
    levels = sfis.levels()
    print(f"       auth: {cred}")
    print(f"       /api/levels: {'ok ' + json.dumps(levels.data) if levels.ok else 'FAIL ' + levels.error}")
    fresh = sfis.recent(limit=1)
    if fresh.ok:
        payloads = (fresh.data or {}).get("recent_payloads") or []
        if payloads:
            print(f"       freshest payload: {payloads[0].get('received_at')} ({payloads[0].get('target')})")

    print(f"eos    {config.EOS_BASE}")
    if not eos.available():
        print("       EOS_API_KEY not set — test records will be omitted")
    else:
        probe = eos.levels()
        print(f"       /levels: {'ok' if probe.ok else 'FAIL ' + probe.error}")
        if probe.ok:
            print(f"       levels: {(probe.data or {}).get('levels')}")

    from . import stations
    print(f"stations  registry: {stations.registry_source()}")
    snap = mirror.latest()
    print(f"snapshot  latest: {snap.name if snap else '(none yet — run: make mirror)'}")
    return 0 if levels.ok else 1


def cmd_mirror(args) -> int:
    roots = _resolve_roots(args)
    if not roots:
        print("nothing to mirror: pass a serial or --level L11", file=sys.stderr)
        return 2
    print(f"mirroring {len(roots)} root serial(s)…")
    snap = mirror.take(
        roots, days=args.days, levels=[args.level] if args.level else []
    )
    if args.verdicts:
        # Only the DUTs present in the mirrored genealogy — resolving every run
        # in the window would be thousands of calls for records nobody asked for.
        known = set(snap.serials())
        snap.resolve_verdicts(known, limit=args.verdict_limit)
        snap.save_manifest()
    source = snap.manifest.get("sources", {})
    print(f"snapshot {snap.root.name}")
    print(f"  sfis: {source.get('sfis', {}).get('serials', 0)} serials"
          f"  ok={source.get('sfis', {}).get('ok')}")
    eos_source = source.get("eos", {})
    print(f"  eos : ok={eos_source.get('ok')} duts={eos_source.get('duts', 0)}"
          f" verdicts={eos_source.get('verdicts_resolved', 0)}")
    return 0


def _build(snap: mirror.Snapshot, sn: str):
    serials = snap.serials()
    by_dut = snap.eos_by_dut()
    verdicts = snap.verdicts()
    if verdicts:
        # Fold cached verdicts into the run records so the renderer never has to
        # know where a result came from.
        for runs in by_dut.values():
            for run in runs:
                found = verdicts.get(run.get("runId"))
                if isinstance(found, dict):
                    run["result"] = found.get("result", "unknown")
                    if found.get("failed_tests"):
                        run["failed_tests"] = found["failed_tests"]
    return graph_mod.build(sn, serials=serials, eos_by_dut=by_dut)


def _product_level(snap: mirror.Snapshot, sn: str) -> str:
    """L11 / 6U / 4U / 2U for one serial, from the mirrored ``/api/units`` map.

    ``/api/levels`` is counts only, so the level of a *specific* serial comes
    from the per-level listings. The receiver classifies 6U/4U/2U structurally
    and L11 both by prefix and by "parents an RMS slot" — worth taking its answer
    rather than deriving a second one here, which would disagree eventually.
    Returns "" rather than a guess when the map was not mirrored.
    """
    units = snap.root / "sfis" / "units.json"
    if units.is_file():
        for level, serials in json.loads(units.read_text()).items():
            if sn in serials:
                return level
    identifiers = snap.root / "sfis" / "identifiers" / f"{sn}.json"
    if identifiers.is_file():
        return json.loads(identifiers.read_text()).get("product_level") or ""
    return ""


def cmd_unit(args) -> int:
    root = Path(args.snapshot) if args.snapshot else mirror.latest()
    if not root:
        print("no snapshot yet — run: make mirror SN=<serial>", file=sys.stderr)
        return 2
    snap = mirror.Snapshot.load(root)
    serials = snap.serials()
    if args.serial[0] not in serials:
        print(f"{args.serial[0]} is not in snapshot {root.name}"
              f" ({len(serials)} serials). Mirror it first.", file=sys.stderr)
        return 2
    built = _build(snap, args.serial[0])
    document = render.document(
        built,
        manifest=snap.manifest,
        product_level=_product_level(snap, args.serial[0]),
        serials=serials,
    )
    text = render.to_text(document)
    for line in document["warnings"]:
        print(f"  ! {line}", file=sys.stderr)
    if args.stdout:
        sys.stdout.write(text)
    else:
        config.OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = config.OUT_DIR / f"{args.serial[0]}.yaml"
        out.write_text(text)
        summary = document["summary"]
        print(f"{out}  {summary['parts']} parts"
              f"  tested={summary['tested']}"
              f"  inherited={summary['inherited_only']}"
              f"  process_only={summary['process_only']}"
              f"  none_expected={summary['none_expected']}"
              f"  not_observed={summary['not_observed']}"
              f"  traceability_gap={summary['traceability_gap']}")
    return 0


#: Serials that are not product. EOS carries dev and bring-up DUTs — bare
#: ``1234``, ``RENAME_TEST_0``, ``ZZTEST…`` — and SFIS deliberately drops
#: ``factory: "TEST"`` payloads. Counting those as traceability escapes buries
#: the real ones, which is the failure mode this whole report exists to avoid.
NON_PRODUCTION = (
    r"^\d{1,8}$",          # 1234 / 12345 / 123456 — hand-typed at a station
    r"(?i)^zztest",
    r"(?i)rename_test",
    r"(?i)^test",
    r"(?i)^dut\d*$",
)

#: A Sohu interposer barcode. ``/api/pairs`` is a *complete* view of these, so a
#: tested Sohu board absent from pairs is a sound finding from any snapshot.
SOHU_BARCODE = r"^JE\d{8,}\d*$"


def _is_non_production(sn: str) -> bool:
    import re

    return any(re.search(pattern, sn or "") for pattern in NON_PRODUCTION)


def cmd_gaps(args) -> int:
    """Findings that need a person, and only the ones this snapshot can support."""
    import re

    root = Path(args.snapshot) if args.snapshot else mirror.latest()
    if not root:
        print("no snapshot yet", file=sys.stderr)
        return 2
    snap = mirror.Snapshot.load(root)
    serials = snap.serials()
    by_dut = snap.eos_by_dut()
    pairs = snap.pairs()
    scope = snap.manifest.get("sfis_scope") or {}
    swept = list(scope.get("levels_swept") or [])

    print(f"snapshot {root.name}   taken {snap.manifest.get('taken_at')}")
    print(f"  EOS window : {snap.manifest.get('eos_window')}")
    print(f"  SFIS scope : {len(scope.get('roots') or [])} root(s)"
          f"{', levels swept: ' + ','.join(swept) if swept else ', no level sweep'}")
    print()

    # --- the one universe-wide check any snapshot can support ----------------
    # /api/pairs is complete for Sohu boards regardless of what was mirrored, so
    # "EOS tested this board and SFIS never linked it" is sound here and nowhere
    # else. This is the "no ASIC SN linked in SFIS" class, found in bulk.
    paired = {p.get("sohu_sn") for p in pairs} | {p.get("pv1_sn") for p in pairs}
    sohu_tested = [sn for sn in by_dut if re.match(SOHU_BARCODE, sn or "")]
    sohu_unlinked = sorted(
        sn for sn in sohu_tested if sn not in paired and not _is_non_production(sn)
    )
    print(f"Sohu boards tested by EOS but never linked in SFIS: "
          f"{len(sohu_unlinked)} of {len(sohu_tested)} tested")
    if not pairs:
        print("  (no pairs.json in this snapshot — check not run)")
    for sn in sohu_unlinked[: args.limit]:
        runs = by_dut[sn]
        first = min(runs, key=lambda r: r.get("startedAt") or "")
        print(f"  {sn:26} {len(runs):2} run(s)  first {first.get('startedAt')}"
              f"  {first.get('level')}/{first.get('suite')}")
    if len(sohu_unlinked) > args.limit:
        print(f"  … {len(sohu_unlinked) - args.limit} more")

    # --- the check that needs a full sweep ----------------------------------
    print()
    if not swept:
        print("Other DUT classes (VBB, L10, L11 units): not checked.")
        print("  A 'tested but unlinked' verdict needs a complete view of SFIS;")
        print("  this snapshot has roots only. Run: make mirror-level LEVEL=6U")
    else:
        known = set(serials) | paired
        for payload in serials.values():
            for entry in sfis.tree_nodes(payload):
                known.add(str(entry["node"].get("serial") or ""))
        other = sorted(
            sn for sn in by_dut
            if sn and sn not in known
            and not re.match(SOHU_BARCODE, sn)
            and not _is_non_production(sn)
        )
        print(f"Other serials tested by EOS but absent from SFIS: {len(other)}")
        for sn in other[: args.limit]:
            runs = by_dut[sn]
            first = min(runs, key=lambda r: r.get("startedAt") or "")
            print(f"  {sn:26} {len(runs):2} run(s)  {first.get('level')}/{first.get('suite')}")

    skipped = sorted(sn for sn in by_dut if _is_non_production(sn))
    if skipped:
        print()
        print(f"Non-production DUTs excluded from the counts above: {len(skipped)}"
              f"  e.g. {', '.join(skipped[:6])}")

    # --- per-unit findings ---------------------------------------------------
    for sn in args.serial or []:
        if sn not in serials:
            print(f"\n{sn}: not in this snapshot", file=sys.stderr)
            continue
        built = _build(snap, sn)
        findings = graph_mod.gaps(built)
        print(f"\n{sn}:")
        for name, rows in findings.items():
            print(f"  {name}: {len(rows)}")
            for row in rows[: args.limit]:
                print(f"    {row.get('slot','?'):18} {row.get('sn','?'):24} {row.get('type','')}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="shopfloor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="reachability + credentials")
    doctor.set_defaults(func=cmd_doctor)

    take = sub.add_parser("mirror", help="snapshot the upstreams")
    take.add_argument("serial", nargs="*")
    take.add_argument("--level", default="", help="mirror every serial at a level")
    take.add_argument("--days", type=int, default=None)
    take.add_argument("--verdicts", action="store_true",
                      help="resolve EOS pass/fail (2 extra calls per run, cached)")
    take.add_argument("--verdict-limit", type=int, default=400)
    take.set_defaults(func=cmd_mirror)

    unit = sub.add_parser("unit", help="render one YAML from a snapshot [offline]")
    unit.add_argument("serial", nargs=1)
    unit.add_argument("--snapshot", default="")
    unit.add_argument("--stdout", action="store_true")
    unit.set_defaults(func=cmd_unit)

    gaps = sub.add_parser("gaps", help="findings across a snapshot [offline]")
    gaps.add_argument("serial", nargs="*")
    gaps.add_argument("--snapshot", default="")
    gaps.add_argument("--limit", type=int, default=15)
    gaps.set_defaults(func=cmd_gaps)

    args = parser.parse_args(argv)
    return args.func(args)
