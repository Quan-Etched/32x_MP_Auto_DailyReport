"""Take a snapshot: copy what the upstreams say onto local disk, verbatim.

THE ARGUMENT FOR THIS FILE
--------------------------
Pegatron's SFIS has **no query API**. As of 2026-08-25 it is item 4 on their
roadmap with no date, and it has been an open ask since April. The only way to
ask "what is under serial X" is Krish's receiver, and the receiver is a single
VM with a SQLite index. It has already been down or degraded in ways that cost
real work:

* ``database disk image is malformed`` — WAL on NFS. Payloads were journalled
  but not indexed, so the API answered "no ASIC SN linked" for a board that was
  linked. Chased by email, one serial at a time, for two days.
* Pega treated ``status: "ok"`` with ``db.ingested: false`` as success and did
  not resend, so payloads were silently absent from the index.
* The VBB flashing station was blocked on 2026-08-03 because SFIS was
  unreachable (ETCH-36858).

Every one of those is a moment when the answer to "which parts are in this
rack" had to come from somewhere other than a live query. That somewhere is this
directory.

THE DESIGN IS BORROWED, DELIBERATELY
------------------------------------
The receiver already separates an immutable journal from a rebuildable index,
and says so as its first design property. This is the same split one layer out:
``snapshots/<id>/`` holds raw API responses, never rewritten, and every YAML is
derived from one of them. So a bug in ``graph.py`` is fixable after the fact
against the data we already had, and only a snapshot we never took is
unrecoverable.

WHAT IS AND IS NOT MIRRORED
---------------------------
Mirrored: ``/api/serial/{sn}`` for the root and for every node in its tree
(that is where MPN, MAC and slot confidence live, one level at a time),
``/api/pairs``, ``/api/levels``, ``/api/units``, ``/api/recent``, and one EOS
run sweep per level over the window.

Not mirrored: EOS artifact bodies beyond the verdict, and never
``resource_config`` — it carries cleartext DUT credentials and no station
identity, so there is nothing to gain and a secret to leak.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import config, eos, sfis


def new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


class Snapshot:
    """A directory of raw upstream responses, plus a manifest describing it."""

    def __init__(self, root: Path):
        self.root = root
        self.manifest: Dict[str, Any] = {
            "id": root.name,
            "taken_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": {},
        }

    # --- reading (works with no network at all) -----------------------------

    @classmethod
    def load(cls, root: Path) -> "Snapshot":
        snap = cls(root)
        path = root / "manifest.json"
        if path.is_file():
            snap.manifest = json.loads(path.read_text())
        return snap

    def serials(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for path in sorted((self.root / "sfis" / "serial").glob("*.json")):
            out[path.stem] = json.loads(path.read_text())
        return out

    def eos_by_dut(self) -> Dict[str, List[Dict[str, Any]]]:
        path = self.root / "eos" / "by_dut.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def serial_index(self) -> Dict[str, Dict[str, Any]]:
        """Per-serial provenance from ``/api/recent``'s ``recent_sns``.

        Carries ``first_seen`` / ``last_received`` / ``payload_count`` / ``sources``
        and a ``spldb_url`` naming that serial's CLF session — a real deep link,
        where everything else this repo builds for SPLM is a search.
        """
        path = self.root / "sfis" / "serial_index.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def mcu_serials(self) -> Dict[str, str]:
        """VBB 'N' serial -> MCU serial. Exists only behind its own endpoint."""
        path = self.root / "sfis" / "mcu.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def pairs(self) -> List[Dict[str, Any]]:
        path = self.root / "sfis" / "pairs.json"
        return (json.loads(path.read_text()).get("pairs") or []) if path.is_file() else []

    # --- writing ------------------------------------------------------------

    def save_manifest(self) -> None:
        _write(self.root / "manifest.json", self.manifest)
        latest = self.root.parent / "latest"
        # A plain file, not a symlink: this directory gets rsynced and zipped,
        # and a dangling symlink inside a restored archive is a worse failure
        # than a one-line pointer.
        latest.write_text(self.root.name + "\n")

    def collect_sfis(self, roots: Iterable[str], *, levels: Iterable[str] = (),
                     wide: Optional[bool] = None) -> None:
        """Mirror the receiver for these roots.

        ``levels`` records which product levels were swept wholesale. That is not
        bookkeeping: a cross-check of "EOS tested a serial SFIS has never heard
        of" is only sound against a complete view of SFIS. Mirrored two racks and
        you will "find" that SFIS is missing every serial in the factory. So the
        scope is written into the manifest and ``gaps`` refuses the checks its
        snapshot cannot support.
        """
        # `wide` decides whether the module population is pulled in as well as
        # the named roots. Defaults to on for a sweep and OFF for an explicit
        # serial: seeding ~1,150 pairs and climbing each of them turns
        # `make sfis-mirror SN=x` -- the one-off the page tells a reader to run
        # when it cannot find a serial -- from seconds into many minutes, which
        # would make the escape hatch useless.
        roots = list(dict.fromkeys(roots))
        levels = list(levels)
        if wide is None:
            wide = bool(levels) or not roots

        source: Dict[str, Any] = {"base": config.SFIS_BASE, "ok": True, "serials": 0,
                                  "wide": wide}
        self.manifest["sfis_scope"] = {
            "roots": roots,
            "levels_swept": levels,
            "wide": wide,
        }

        freshness = sfis.recent(limit=1)
        if freshness.ok:
            payloads = (freshness.data or {}).get("recent_payloads") or []
            if payloads:
                self.manifest["sfis_payloads_through"] = payloads[0].get("received_at")
                _write(self.root / "sfis" / "recent.json", freshness.data)
        else:
            source["recent_error"] = freshness.error

        levels_response = sfis.levels()
        for name, response in (
            ("levels", levels_response),
            ("pairs", sfis.pairs()),
        ):
            if response.ok:
                _write(self.root / "sfis" / f"{name}.json", response.data)
            else:
                source[f"{name}_error"] = response.error

        # The serial -> product level map, one cheap call per level. Needed for
        # two things a per-root mirror cannot otherwise know: which level a root
        # is (the receiver's prefix map does not cover every new prefix — this
        # rack classifies structurally, not by prefix), and the complete serial
        # universe that makes the `gaps` cross-checks sound.
        by_level: Dict[str, List[str]] = {}
        for level in ((levels_response.data or {}).get("levels") or {}) if levels_response.ok else {}:
            listing = sfis.units(level)
            if listing.ok:
                by_level[level] = (listing.data or {}).get("serials") or []
        if by_level:
            _write(self.root / "sfis" / "units.json", by_level)

        seeds: List[str] = list(roots)
        for level in levels or []:
            seeds.extend(by_level.get(level) or [])

        # /api/pairs is the module population, and it is the half /api/units
        # cannot see: every Sohu board and every PV1, whether or not it has been
        # fitted into anything. One call.
        pairs_path = self.root / "sfis" / "pairs.json"
        if wide and pairs_path.is_file():
            for pair in json.loads(pairs_path.read_text()).get("pairs") or []:
                for key in ("pv1_sn", "sohu_sn"):
                    value = str(pair.get(key) or "")
                    if value:
                        seeds.append(value)

        # Per-serial provenance: first seen, last seen, which sources it came
        # through, and its SPLDB CLF session -- a real deep link, unlike the
        # search URL built by hand elsewhere. Always fetched: it is ONE call, and
        # the expensive part of `recent_sns` was never getting it, it was seeding
        # a climb from every serial in it. So the links are there even for a
        # one-serial mirror; only the seeding is gated.
        recent_index = sfis.recent_serials()
        if recent_index.ok:
            rows = (recent_index.data or {}).get("recent_sns") or []
            _write(self.root / "sfis" / "serial_index.json",
                   {row["sn"]: row for row in rows if row.get("sn")})
            if wide:
                seeds.extend(row["sn"] for row in rows if row.get("sn"))
        else:
            source["recent_sns_error"] = recent_index.error

        # --- seeds -> climb to the top -> walk down -------------------------
        #
        # `/api/units` returns only 6U/4U/2U/L11 tops, and that is NOT the serial
        # universe. A Sohu module that has been built and tested but not yet
        # fitted into a tray belongs to no product level at all, so no level
        # sweep reaches it or anything under it -- which is how a PV1 with 15
        # process events of its own read as "not in the traceability snapshot".
        #
        # So seeds come from the levels AND from `/api/pairs` (every Sohu board
        # and every PV1, ~1,150 of them, one call), and each seed is CLIMBED to
        # whatever parents it before the tree below that is walked. Climbing is
        # what turns a loose module into a root; without it a seed's siblings and
        # its own parent stay invisible.
        queue: List[str] = []
        fetched: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}

        def payload_for(sn: str) -> Optional[Dict[str, Any]]:
            """One /api/serial, memoised. Climb and descent share the cache, so a
            family is never fetched twice however it was reached."""
            if sn in fetched:
                return fetched[sn]
            if sn in errors:
                return None
            response = sfis.serial(sn)
            if not response.ok:
                errors[sn] = response.error
                return None
            payload = response.data or {}
            fetched[sn] = payload
            _write(self.root / "sfis" / "serial" / f"{sn}.json", payload)
            return payload

        def climb(sn: str) -> str:
            """Follow active parents to the top of this serial's family."""
            seen = set()
            cursor = sn
            while cursor and cursor not in seen:
                seen.add(cursor)
                payload = payload_for(cursor)
                if payload is None:
                    return cursor
                parents = payload.get("active_parents") or []
                nxt = str(parents[0].get("parent_sn") or "") if parents else ""
                if not nxt:
                    return cursor
                cursor = nxt
            return cursor

        tops: List[str] = []
        for seed in dict.fromkeys(seeds):
            top = climb(seed)
            if top:
                tops.append(top)
        tops = list(dict.fromkeys(tops))
        source["seeds"] = len(seeds)
        source["tops"] = len(tops)

        # Every node in every top's tree gets its own /api/serial call. That is
        # where MPN, MAC and slot confidence live -- the receiver only exposes
        # them for a serial's *direct* children -- so a tree walk without this is
        # a tree of bare serials.
        # `expanded` is separate from `fetched` on purpose. The climb already put
        # every top in the payload cache, so a descent that skipped anything
        # cached would skip the tops themselves and never enqueue their children
        # -- which it did: a PV1 and its parent came back as a two-serial
        # "family" with the interposer beneath it missing.
        expanded: set = set()
        queue = list(tops)
        while queue:
            sn = queue.pop(0)
            if not sn or sn in expanded or sn in errors:
                continue
            expanded.add(sn)
            payload = payload_for(sn)
            if payload is None:
                continue
            for entry in sfis.tree_nodes(payload):
                child_sn = str(entry["node"].get("serial") or "")
                if child_sn and child_sn not in expanded:
                    queue.append(child_sn)

        # The VBB's MCU serial exists only behind its own endpoint -- it never
        # travels in a payload -- so it is fetched for the serials that can have
        # one. Cheap: only 'N'-prefixed boards qualify.
        mcu_map: Dict[str, str] = {}
        for sn in list(fetched):
            if not sn[:1].upper() == "N":
                continue
            response = sfis.mcu(sn)
            if response.ok:
                found = (response.data or {}).get("mcu_sn")
                if found:
                    mcu_map[sn] = found
        if mcu_map:
            _write(self.root / "sfis" / "mcu.json", mcu_map)
        source["mcu_mapped"] = len(mcu_map)

        # Rack roots additionally get /identifiers: the receiver's own view of
        # RMS/TOR/MSW/PDU/NIC records and MACs, plus a product_level. Keyed on
        # the same structural test the receiver uses — parents an RMS slot.
        for sn, payload in list(fetched.items()):
            slots = {
                str(child.get("normalized_slot") or "")
                for child in payload.get("current_children") or []
            }
            if any(slot.startswith("RMS") for slot in slots):
                response = sfis.identifiers(sn)
                if response.ok:
                    _write(
                        self.root / "sfis" / "identifiers" / f"{sn}.json", response.data
                    )

        source["serials"] = len(fetched)
        if errors:
            # Grouped by error class, with an example. An ungrouped list put
            # forty copies of one message in the manifest and buried the one
            # that was different.
            grouped: Dict[str, Dict[str, Any]] = {}
            for sn, message in errors.items():
                klass = message.split(":", 1)[0]
                bucket = grouped.setdefault(
                    klass, {"count": 0, "example_serial": sn, "example": message}
                )
                bucket["count"] += 1
            source["serial_errors"] = grouped
            source["serials_failed"] = len(errors)
            source["ok"] = len(fetched) > 0
        self.manifest["sources"]["sfis"] = source

    def collect_eos(self, days: Optional[int] = None) -> None:
        if not eos.available():
            self.manifest["sources"]["eos"] = {
                "ok": False,
                "reason": "EOS_API_KEY not set — Etched test records omitted",
            }
            return
        since, until = eos.window(days)
        self.manifest["eos_window"] = [since, until]
        probe = eos.levels()
        if not probe.ok:
            self.manifest["sources"]["eos"] = {"ok": False, "reason": probe.error}
            return
        swept = eos.sweep(since, until)
        _write(self.root / "eos" / "by_dut.json", swept["by_dut"])
        _write(self.root / "eos" / "levels.json", swept["levels"])
        self.manifest["sources"]["eos"] = {
            "ok": True,
            "base": config.EOS_BASE,
            "window": [since, until],
            "levels": swept["levels"],
            "duts": len(swept["by_dut"]),
        }

    def resolve_verdicts(self, duts: Iterable[str], limit: int = 400) -> None:
        """Fill in pass/fail for the runs that matter, and cache them forever.

        EOS ``/runs`` carries no status, so a verdict costs two extra calls. Only
        the runs belonging to serials actually in the graph are resolved, and a
        finished run's verdict never changes — so the cache is permanent and a
        re-render is free.
        """
        by_dut = self.eos_by_dut()
        cache_path = self.root / "eos" / "verdicts.json"
        cache: Dict[str, Any] = (
            json.loads(cache_path.read_text()) if cache_path.is_file() else {}
        )
        wanted = [sn for sn in dict.fromkeys(duts) if sn in by_dut]
        resolved = 0
        for sn in wanted:
            for run in by_dut[sn]:
                run_id = run.get("runId")
                if not run_id or run_id in cache:
                    continue
                if resolved >= limit:
                    cache["_truncated"] = True
                    break
                cache[run_id] = eos.verdict(run.get("level") or "", sn, run_id)
                resolved += 1
            if resolved >= limit:
                break
        _write(cache_path, cache)
        self.manifest.setdefault("sources", {}).setdefault("eos", {})[
            "verdicts_resolved"
        ] = sum(1 for k in cache if not k.startswith("_"))

    def verdicts(self) -> Dict[str, Any]:
        path = self.root / "eos" / "verdicts.json"
        return json.loads(path.read_text()) if path.is_file() else {}


def latest(snapshot_dir: Optional[Path] = None) -> Optional[Path]:
    """The most recent snapshot, by the ``latest`` pointer or by name."""
    base = snapshot_dir or config.SNAPSHOT_DIR
    pointer = base / "latest"
    if pointer.is_file():
        candidate = base / pointer.read_text().strip()
        if candidate.is_dir():
            return candidate
    dirs = sorted(p for p in base.glob("*") if p.is_dir())
    return dirs[-1] if dirs else None


def take(roots: List[str], *, days: Optional[int] = None,
         levels: Iterable[str] = (),
         wide: Optional[bool] = None,
         snapshot_dir: Optional[Path] = None) -> Snapshot:
    base = snapshot_dir or config.SNAPSHOT_DIR
    snap = Snapshot(base / new_id())
    snap.collect_sfis(roots, levels=levels, wide=wide)
    snap.collect_eos(days)
    snap.save_manifest()
    return snap
