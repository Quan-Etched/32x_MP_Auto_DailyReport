"""A read-only client for pega3 (ESVM), the station controller.

WHY THIS EXISTS
---------------
EOS records **one run per fixture with one DUT serial**, and the fixture drives
eight modules. The other seven serials are assigned by pega3 when it loads the
slots, and that assignment never reaches EOS: it is in neither
``suite_summary`` (five fields, no serial), ``event_stream`` (one ``dutInfoId``
plus the Devkit server's serial), ``suite_config`` (a test plan — zero lines
mentioning serial, slot or dut), ``bom_config`` (a static BOM with every
``serial_number: null``), nor any of the 997 per-chip logs. It was looked for in
all of them.

pega3 has it, and hands it over without asking::

    GET /api/test_suite_run/<suite_run_id>
      -> participating: [{dut_sn, slot_number, status} × 8]

That is the same mapping the line types into its tracker by hand, and the
serials come back matching the sheet row for row.

WHAT IT IS NOT
--------------
Not a second ETL. Nothing here is stored, aggregated or published on its own —
it exists so the daily tracker page can name the unit in a row instead of
saying "chip 3". The EOS pipeline remains the source for everything else.

The API needs **no credentials**. The ESVM login guards the web UI, not
``/api``; this was verified rather than assumed, and it is the reason no
password appears in this repo. If pega3 ever starts requiring one, this module
should degrade to unavailable rather than grow a secret.

REACHABILITY IS NOT ASSUMED
---------------------------
``pega3`` resolves on the office network and the VPN, and may or may not
resolve from a given host. Every call is short-timeout and every failure is
caught: callers get ``None`` and fall back to what EOS alone can tell them. A
tracker page that renders without pega3 is worth more than one that fails with
it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://pega3:3000"

#: Short: this is a nice-to-have on a page that must build without it.
TIMEOUT = 8.0

#: The list endpoint pages, and caps per_page well below what it is asked for.
PAGE_SIZE = 50
MAX_PAGES = 40


class PegaUnavailable(RuntimeError):
    """pega3 could not be reached. Never fatal — the caller degrades."""


#: Hosts whose first call failed, so a box with no route pays one timeout per
#: build rather than one per day rebuilt. Per host, not global: pega4 being
#: unreachable says nothing about pega3, and a shared flag would silently stop
#: reading a controller that was answering perfectly well. Reset per process, so
#: a restored route is picked up on the next tick without touching config.
_UNREACHABLE: set = set()


def base_url(host: Optional[str] = None) -> str:
    """The controller to talk to.

    ``host`` names one of the ESVM boxes — pega2 provisions VBB boards, pega3
    drives the module stations, pega4 L10, pega5 L11. FACTORY_PEGA_URL still
    overrides the default, and a host swaps the name inside it so an override
    pointing at an IP or a different port keeps working for all of them.
    """
    url = os.environ.get("FACTORY_PEGA_URL", DEFAULT_BASE_URL).rstrip("/")
    if host:
        url = re.sub(r"//[^/:]+", "//" + host, url, count=1)
    return url


def enabled() -> bool:
    """False turns the whole integration off without removing the code."""
    return os.environ.get("FACTORY_PEGA", "1").strip().lower() not in ("0", "false", "no")


#: Finished suite runs never change, and a day costs ~100 detail calls, so they
#: are cached on disk. Without this an hourly rebuild would re-fetch the same
#: immutable runs every hour for as long as the day stays in the window.
CACHE_DIR = config.RAW_DIR / "pega"


#: Hosts whose answer came from the cache after the network failed, this run.
#: A caller can ask, so a page built from a stale copy can say so instead of
#: presenting it as fresh.
_FELL_BACK: set = set()


def fell_back(host: Optional[str] = None) -> bool:
    """Did this host's data come from the cache after a failed fetch?"""
    if host is None:
        return bool(_FELL_BACK)
    return host in _FELL_BACK


def _default_host_name() -> str:
    """The name behind ``host=None``, so it shares an identity with the
    explicitly-named calls to the same machine."""
    base = base_url(None)
    for name in ("pega1", "pega2", "pega3", "pega4", "pega5", "pega6"):
        if "//{}:".format(name) in base or "//{}/".format(name) in base:
            return name
    return "default"


def _cache_path(path: str, host: Optional[str] = None) -> Path:
    # The host is part of the key: pega3 and pega4 answer the same paths with
    # different data, and a shared key would serve one line's runs to the other.
    # Literal, deliberately. Resolving `host=None` to a name here would make
    # the key depend on base_url(), which depends on FACTORY_PEGA_URL — so a
    # cache written before that variable changed could not be found after, and
    # every existing cache file would be orphaned by the rename. Callers name
    # their host instead (asserted in tests), which is what makes the collector
    # and the daily tracker share one entry.
    key = "{}|{}".format(host or "", path)
    return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def _read_cache(path: str, host: Optional[str] = None) -> Optional[Any]:
    cached = _cache_path(path, host)
    if not cached.exists():
        return None
    try:
        return json.loads(cached.read_text(encoding="utf-8"))
    except ValueError:
        cached.unlink()                              # corrupt: refetch
        return None


def _write_cache(path: str, payload: Any, host: Optional[str] = None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(path, host).write_text(json.dumps(payload), encoding="utf-8")


def _get(path: str, cache: bool = False, stale_ok: bool = False,
         host: Optional[str] = None) -> Any:
    """Fetch, preferring the cache where the answer cannot change.

    ``stale_ok`` marks a request whose answer *does* change — a day's run list
    grows while the day is running — but where a cached copy still beats
    nothing. The network is tried first for those, and the cache catches the
    fall.

    THE CACHE IS ALSO A TRANSPORT. The dashboard host has no route to pega3
    (its DNS does not know the name), so it can never populate this itself.
    A laptop on the VPN can, and ``data/raw/pega/`` copies across like the CA
    bundle does — which is why a cache read must not depend on the network
    being reachable, and why the unreachable short-circuit is checked *after*
    the cache rather than before it.
    """
    if cache and not stale_ok:
        hit = _read_cache(path, host)
        if hit is not None:
            return hit

    # One machine, one identity. `host=None` and `host="pega3"` build the same
    # URL, and treating them as two names meant a single timeout under
    # "default" marked that name dead for the rest of the process while the
    # pega3-named calls carried on working. The daily tracker was the only
    # caller using the unnamed form, so it was the only one that silently fell
    # back to a stale listing — on 2026-08-27 that cost it eight runs and it
    # said nothing. Callers should name their host; this makes the two agree
    # anyway.
    who = host or _default_host_name()
    if who in _UNREACHABLE:
        if cache:
            hit = _read_cache(path, host)
            if hit is not None:
                _FELL_BACK.add(who)
                return hit
        raise PegaUnavailable("{} was unreachable earlier in this run".format(who))

    url = "{}{}".format(base_url(host), path)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # A name that does not resolve or a host with no route will not fix
        # itself between one day and the next; stop paying the timeout.
        if isinstance(exc, (urllib.error.URLError, OSError)):
            _UNREACHABLE.add(who)
            # Only claim the cache when this call can actually use one. Saying
            # "using a cached copy instead" on a probe that reads no cache is a
            # log line asserting something it does not know.
            log.info("%s unreachable (%s); %s", who, exc,
                     "falling back to the cache" if cache
                     else "this call has no cache to fall back to")
        if cache:
            hit = _read_cache(path, host)
            if hit is not None:
                _FELL_BACK.add(who)
                return hit
        raise PegaUnavailable("{}: {}".format(url, exc)) from exc

    if cache:
        # Only a finished run is safe to keep: one still running would freeze
        # mid-flight and never update.
        if stale_ok or str(payload.get("status", "")).lower() not in ("running", "", "none"):
            _write_cache(path, payload, host)
    return payload


def available() -> bool:
    """One cheap probe, so a caller can decide before doing real work."""
    if not enabled():
        return False
    try:
        _get("/api/history/data-analysis/suite-runs?per_page=1")
        return True
    except PegaUnavailable as exc:
        log.info("pega3 unavailable (%s)", exc)
        return False


# ------------------------------------------------------------------ endpoints

def day_suite_runs(day: str, host: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every suite run pega3 recorded on a calendar day.

    One entry per run, carrying the run's *filed* unit. The other slots come
    from :func:`suite_run`.
    """
    # The window is `start`/`end` as full ISO instants, and `end` is
    # EXCLUSIVE. The obvious-looking start_date/end_date are silently ignored:
    # passing them returns every recent run regardless of the day asked for,
    # which looks like a working filter until two different days come back
    # byte-identical.
    start = "{}T00:00:00.000Z".format(day)
    end = "{}T00:00:00.000Z".format(_next_day(day))

    # A finished day's run list cannot change, so only *today* is worth going
    # to the network for. Without this a 30-day collect made 120 listing calls
    # on every build — enough to push `make build` past two minutes on a warm
    # cache, for answers that were already on disk.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    still_running = day >= today

    collected: List[Dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        payload = _get(
            "/api/history/data-analysis/suite-runs"
            "?start={start}&end={end}&page={page}&per_page={size}".format(
                start=start, end=end, page=page, size=PAGE_SIZE),
            cache=True, stale_ok=still_running, host=host)
        batch = payload.get("suite_runs") or []
        collected.extend(batch)
        total = payload.get("total")
        if not batch or (total is not None and len(collected) >= total):
            break
    return collected


def _next_day(day: str) -> str:
    moment = datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)
    return moment.strftime("%Y-%m-%d")


def suite_run(run_id: str, host: Optional[str] = None) -> Dict[str, Any]:
    """One suite run, including the slot -> DUT serial map."""
    return _get("/api/test_suite_run/{}".format(run_id), cache=True, host=host)


def participants(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The slots a run drove, normalized.

    A full fixture run returns eight; a single-slot retest returns one. Falls
    back to the run's own ``dut_sn`` so a run is never silently unit-less.
    """
    rows = detail.get("participating")
    if isinstance(rows, list) and rows:
        return [
            {
                "dut": str(row.get("dut_sn") or "").strip(),
                "slot": row.get("slot_number"),
                "status": _status(row.get("status")),
            }
            for row in rows if row.get("dut_sn")
        ]
    dut = str(detail.get("dut_sn") or "").strip()
    if not dut:
        return []
    return [{
        "dut": dut,
        "slot": detail.get("module_slot_number", detail.get("slot_number")),
        "status": _status(detail.get("status")),
    }]


def run_url(run_id: str, slot: Optional[int], host: Optional[str] = None) -> str:
    """The link the tracker sheet itself uses, rebuilt exactly."""
    url = "{}/suite_run/{}".format(base_url(host), run_id)
    if slot is not None:
        url += "?slot_number={}".format(slot)
    return url


def _status(value: Optional[str]) -> str:
    """pega3 says 'Passed'/'failed' in either case; the sheet says Passed/Failed."""
    text = str(value or "").strip().lower()
    if text.startswith("pass"):
        return "pass"
    if text.startswith("fail"):
        return "fail"
    return text or "unknown"
