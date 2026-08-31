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

from . import config, eos, sfis, stations


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
            "station_registry": stations.registry_source(),
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

    def collect_sfis(self, roots: Iterable[str], *, levels: Iterable[str] = ()) -> None:
        """Mirror the receiver for these roots.

        ``levels`` records which product levels were swept wholesale. That is not
        bookkeeping: a cross-check of "EOS tested a serial SFIS has never heard
        of" is only sound against a complete view of SFIS. Mirrored two racks and
        you will "find" that SFIS is missing every serial in the factory. So the
        scope is written into the manifest and ``gaps`` refuses the checks its
        snapshot cannot support.
        """
        source: Dict[str, Any] = {"base": config.SFIS_BASE, "ok": True, "serials": 0}
        self.manifest["sfis_scope"] = {
            "roots": list(dict.fromkeys(roots)),
            "levels_swept": list(levels),
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

        # Every node in every root's tree gets its own /api/serial call. That is
        # where MPN, MAC and slot confidence live — the receiver only exposes
        # them for a serial's *direct* children — so a tree walk without this is
        # a tree of bare serials. ~100 calls per 6U, seconds, and it is the
        # difference between an inventory and an attribute graph.
        queue: List[str] = list(dict.fromkeys(roots))
        fetched: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}

        while queue:
            sn = queue.pop(0)
            if not sn or sn in fetched or sn in errors:
                continue
            response = sfis.serial(sn)
            if not response.ok:
                errors[sn] = response.error
                continue
            payload = response.data or {}
            fetched[sn] = payload
            _write(self.root / "sfis" / "serial" / f"{sn}.json", payload)
            for entry in sfis.tree_nodes(payload):
                child_sn = str(entry["node"].get("serial") or "")
                if child_sn and child_sn not in fetched:
                    queue.append(child_sn)

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
         snapshot_dir: Optional[Path] = None) -> Snapshot:
    base = snapshot_dir or config.SNAPSHOT_DIR
    snap = Snapshot(base / new_id())
    snap.collect_sfis(roots, levels=levels)
    snap.collect_eos(days)
    snap.save_manifest()
    return snap
