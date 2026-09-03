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
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://pega3:3000"

#: The earliest day worth asking the controllers for.
#:
#: A floor date, not a day count, because the data has a fixed *start* — the
#: line's first runs — while "the last N days" walks away from it. That is not
#: hypothetical: the collector asked for 90 days, chosen when 90 days back was
#: 2026-05-27 and the earliest run on any controller was 05-21, so it covered
#: everything. By 09-02 the same 90 days began on 06-04 and had quietly dropped
#: a fortnight of pega3's history. Nothing said so; the window simply got
#: shorter every day.
#:
#: Probed 2026-09-02: pega3 answers from 2026-05-21, pega5 from 05-23, pega4
#: from 06-12. Reaching all the way back to those first runs is what 05-01 did,
#: and it was too expensive to keep: the floor sets the number of day-listings
#: every build walks, per host, and it sets NEW_INPUT_LOOKBACK with it, so a
#: date four months back made the daily tracker 73 tabs and the page slow
#: enough to be reported as broken.
#:
#: 08-01 is the line's own reporting horizon — the ramp people actually review
#: — and it is what was asked for on 2026-09-03 after the wider window landed.
#: May, June and July are bring-up rather than line performance, so the history
#: being dropped here is history nobody was reading. Set FACTORY_PEGA_FROM to
#: reach further back for a one-off investigation; nothing else needs changing.
CONTROLLER_FROM = os.environ.get("FACTORY_PEGA_FROM", "2026-08-01")

#: How long to wait on one controller call.
#:
#: Eight seconds was measured from a laptop sitting in the same city as the
#: controllers, where every call answers in well under one. The dashboard host
#: is in us-west-2 and the pega boxes are in Hong Kong, with no direct path
#: between them: Tailscale relays the traffic through a DERP node, and the
#: *connect* alone measured 5.1s, 7.3s and 12.5s on 2026-09-02, with one pega5
#: call taking over 45s. Once connected the transfer is quick — it is the
#: hole-punch that is slow.
#:
#: At 8s that path reads as a dead host, and because the first failure used to
#: write the host off for the whole build (see _UNREACHABLE), one slow connect
#: at the start of a tick meant pega3, pega4 and pega5 were all served from
#: cache for every day of the run. That is exactly how the published weekly
#: tracker froze at W32 while the box collected happily every hour: the cache
#: it fell back to had last been warm on 08-09, and nothing in the log said the
#: numbers were three weeks old.
TIMEOUT = float(os.environ.get("FACTORY_PEGA_TIMEOUT", "30"))

#: Consecutive timeouts before a host is written off for the rest of the build.
#:
#: A timeout is not proof of a dead host — see TIMEOUT — so one of them must
#: not be allowed to decide. A host with genuinely no route reaches this count
#: in three calls and stops costing anything after that, which is the whole
#: point of the write-off; a merely slow one answers and the count resets.
TIMEOUT_STRIKES = int(os.environ.get("FACTORY_PEGA_STRIKES", "3"))

#: The list endpoint pages, and caps per_page well below what it is asked for.
PAGE_SIZE = 50
MAX_PAGES = 40


class PegaUnavailable(RuntimeError):
    """pega3 could not be reached. Never fatal — the caller degrades."""


#: Hosts written off for the rest of this build, so a box with no route pays a
#: few timeouts per build rather than one per day rebuilt. Per host, not
#: global: pega4 being unreachable says nothing about pega3, and a shared flag
#: would silently stop reading a controller that was answering perfectly well.
#: Reset per process, so a restored route is picked up on the next tick without
#: touching config.
_UNREACHABLE: set = set()

#: Consecutive timeouts seen per host, against TIMEOUT_STRIKES. A timeout is
#: the one failure that routinely lies — see TIMEOUT — so it takes several in a
#: row to condemn a host, and any answer at all clears the count.
_TIMEOUTS: Dict[str, int] = {}


def _is_timeout(exc: BaseException) -> bool:
    """Was this a timeout rather than a refusal or a bad name?

    urllib wraps the socket error, so the timeout can arrive as
    ``socket.timeout`` (an alias of ``TimeoutError`` since 3.10), as a
    ``URLError`` carrying one, or — for a read that stalls after connecting —
    as a bare ``TimeoutError``. The text check catches the URLError form,
    whose ``reason`` is sometimes only a string.
    """
    seen = exc
    for _ in range(3):                     # reason chains are shallow
        if isinstance(seen, (socket.timeout, TimeoutError)):
            return True
        reason = getattr(seen, "reason", None)
        if reason is None:
            break
        seen = reason
    return "timed out" in str(exc).lower()


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


def offline(host: Optional[str] = None) -> bool:
    """Should this controller be served from the on-disk cache, never fetched?

    Per host, because the box's problem is per host. It reaches pega2 in 0.7s
    and pega6 in 2s — those are on the corporate side of the network and answer
    normally — while pega3, pega4 and pega5 are DERP-relayed and effectively
    unreachable. Switching the whole integration to the cache took the two
    working hosts down with the three broken ones and cost 696 unit runs, which
    is how this stopped being a boolean.

        FACTORY_PEGA_OFFLINE=pega3,pega4,pega5   # what the box runs
        FACTORY_PEGA_OFFLINE=1                   # every host, for a laptop
                                                 # off the VPN

    For a host that HAS the data but cannot fetch it. The dashboard box is
    exactly that: measured 2026-09-03, one 50-run listing took 180s to deliver
    8,452 of 26,400 bytes — 46 bytes/second — because its Tailscale path to the
    pega hosts is relayed through a DERP node in Hong Kong instead of going
    direct. The same request from a laptop on the same tailnet takes 0.09s.

    So the cache is warmed on a laptop and rsynced across, which is the
    transport docs/deploy.md has always described for a host with no route, and
    this flag stops the box spending five to eight minutes per build proving
    again that it has none. Every page still says its controller data came from
    a cached copy, because `fell_back` is set exactly as it would be after a
    failed fetch — the reader is not told anything different from the truth.

    Turn it off the moment the path is fixed: `enabled()` is the switch for
    dropping the integration, this one is for keeping it on borrowed data.
    """
    setting = os.environ.get("FACTORY_PEGA_OFFLINE", "0").strip().lower()
    if not setting or setting in ("0", "false", "no"):
        return False
    if setting in ("1", "true", "yes"):
        return True
    named = [part.strip() for part in setting.split(",") if part.strip()]
    # An unnamed call is the default host, the same resolution _get uses, so
    # naming pega3 covers the calls that reach it without saying so.
    return (host or _default_host_name()).lower() in named


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


def _partial_path(path: str, host: Optional[str] = None) -> Path:
    """Marker beside an entry whose answer was not final when it was written.

    A separate file rather than a field in the payload, so the 4,000 entries
    already on disk keep their shape and an entry with no marker means exactly
    what it used to: a complete answer.
    """
    return _cache_path(path, host).with_suffix(".partial")


def _read_cache(path: str, host: Optional[str] = None,
                complete_only: bool = False) -> Optional[Any]:
    """The cached answer, or None.

    ``complete_only`` rejects an entry that was written while its answer could
    still change — see :func:`_write_cache`. Callers falling back after a
    failed fetch leave it off: a provisional copy beats nothing, and that path
    already records the fallback so the page can say so.
    """
    cached = _cache_path(path, host)
    if not cached.exists():
        return None
    if complete_only and _partial_path(path, host).exists():
        return None
    try:
        return json.loads(cached.read_text(encoding="utf-8"))
    except ValueError:
        cached.unlink()                              # corrupt: refetch
        return None


def _write_cache(path: str, payload: Any, host: Optional[str] = None,
                 complete: bool = True) -> None:
    """Store an answer, recording whether it was final when it was fetched.

    WHY THE MARKER EXISTS. A day's run list grows while the day runs, and the
    listing calls say so — that is what ``stale_ok`` means. But the entry they
    wrote was indistinguishable from one fetched after the day ended, and the
    day-listing reader trusts any past day's entry without going to the
    network. So a listing fetched at 17:34 on a Tuesday was served as Tuesday's
    complete record for ever after, and every rebuild since agreed with it.

    Measured on 2026-09-02, before this: 09-01 was cached at 17:34 on 09-01 and
    held 16 of the day's 32 pega4 runs, 4 of pega3's 33 and 8 of pega5's 14.
    08-21 held 0 of 69. The daily tracker's 09-01 tab showed 23 units where the
    controllers had 41, and 08-24 showed 6 where they had 65 — for days that
    looked settled and had been for a week. Nothing anywhere said so.

    A finished run's *detail* is genuinely immutable, so it is still written
    complete and none of those entries change.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(path, host).write_text(json.dumps(payload), encoding="utf-8")
    marker = _partial_path(path, host)
    if complete:
        # A later complete fetch settles an entry that was provisional.
        if marker.exists():
            marker.unlink()
    else:
        marker.write_text("", encoding="utf-8")


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
        # complete_only: this caller wants a final answer, so an entry written
        # while its answer could still change is a miss, not a hit.
        hit = _read_cache(path, host, complete_only=True)
        if hit is not None:
            # Normally a hit here is the design working and says nothing about
            # freshness. Offline it is the only thing that can happen, and the
            # page should say its controller data is a cached copy — nothing is
            # being refreshed, today included.
            if offline(host):
                _FELL_BACK.add(host or _default_host_name())
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

    # Read at call time, not at import: a test flips it, and so does an
    # operator who has just had the network path repaired.
    if offline(host):
        if cache:
            hit = _read_cache(path, host)
            if hit is not None:
                _FELL_BACK.add(who)
                return hit
        raise PegaUnavailable(
            "{}: FACTORY_PEGA_OFFLINE is set and this is not in the cache"
            .format(path))

    url = "{}{}".format(base_url(host), path)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # A name that does not resolve or a host with no route will not fix
        # itself between one day and the next; stop paying the timeout.
        #
        # A *timeout* is the exception to that, and treating it as proof of a
        # dead host is what froze the published weekly tracker for three weeks.
        # The relayed path to Hong Kong takes 5-12s to connect and occasionally
        # much longer, so it takes TIMEOUT_STRIKES of them in a row — and any
        # answer at all resets the count.
        if isinstance(exc, (urllib.error.URLError, OSError)):
            # Only claim the cache when this call can actually use one. Saying
            # "using a cached copy instead" on a probe that reads no cache is a
            # log line asserting something it does not know.
            fallback = ("falling back to the cache" if cache
                        else "this call has no cache to fall back to")
            if not _is_timeout(exc):
                _UNREACHABLE.add(who)
                log.info("%s unreachable (%s); %s", who, exc, fallback)
            else:
                _TIMEOUTS[who] = _TIMEOUTS.get(who, 0) + 1
                strikes = _TIMEOUTS[who]
                if strikes >= TIMEOUT_STRIKES:
                    _UNREACHABLE.add(who)
                    # Said plainly, because this is the line that was missing
                    # while the weekly tracker served three-week-old numbers:
                    # the build carried on and reported success, and nothing
                    # anywhere said the figures had stopped moving.
                    log.warning(
                        "%s timed out %d times in a row (%.0fs each); serving "
                        "it from the cache for the REST OF THIS BUILD — any "
                        "day it has no cached copy of will be missing from the "
                        "output", who, strikes, TIMEOUT)
                else:
                    log.info("%s timed out after %.0fs (%d of %d before it is "
                             "given up on); %s", who, TIMEOUT, strikes,
                             TIMEOUT_STRIKES, fallback)
        if cache:
            hit = _read_cache(path, host)
            if hit is not None:
                _FELL_BACK.add(who)
                return hit
        raise PegaUnavailable("{}: {}".format(url, exc)) from exc

    # It answered, so whatever the earlier timeouts were, they were not this
    # host being gone.
    _TIMEOUTS.pop(who, None)

    if cache:
        # Only a finished run is safe to keep: one still running would freeze
        # mid-flight and never update.
        if stale_ok or str(payload.get("status", "")).lower() not in ("running", "", "none"):
            # `stale_ok` is the caller saying this answer can still change, so
            # it is exactly the condition that makes the entry provisional.
            _write_cache(path, payload, host, complete=not stale_ok)
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


def day_range(first: str, last: str) -> List[str]:
    """Every calendar day from ``first`` to ``last``, inclusive.

    Empty when ``last`` precedes ``first``, so a caller with an inverted span
    walks nothing rather than looping backwards for ever.
    """
    start = datetime.strptime(first, "%Y-%m-%d").date()
    end = datetime.strptime(last, "%Y-%m-%d").date()
    out: List[str] = []
    while start <= end:
        out.append(start.strftime("%Y-%m-%d"))
        start += timedelta(days=1)
    return out


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
