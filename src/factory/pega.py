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
import urllib.error
import urllib.request
from datetime import datetime, timedelta
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


def base_url() -> str:
    return os.environ.get("FACTORY_PEGA_URL", DEFAULT_BASE_URL).rstrip("/")


def enabled() -> bool:
    """False turns the whole integration off without removing the code."""
    return os.environ.get("FACTORY_PEGA", "1").strip().lower() not in ("0", "false", "no")


#: Finished suite runs never change, and a day costs ~100 detail calls, so they
#: are cached on disk. Without this an hourly rebuild would re-fetch the same
#: immutable runs every hour for as long as the day stays in the window.
CACHE_DIR = config.RAW_DIR / "pega"


def _cache_path(path: str) -> Path:
    return CACHE_DIR / (hashlib.sha1(path.encode("utf-8")).hexdigest() + ".json")


def _get(path: str, cache: bool = False) -> Any:
    if cache:
        cached = _cache_path(path)
        if cached.exists():
            try:
                return json.loads(cached.read_text(encoding="utf-8"))
            except ValueError:
                cached.unlink(missing_ok=True)      # corrupt: refetch

    url = "{}{}".format(base_url(), path)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PegaUnavailable("{}: {}".format(url, exc)) from exc

    if cache:
        # Only a finished run is safe to keep: one still running would freeze
        # mid-flight and never update.
        if str(payload.get("status", "")).lower() not in ("running", "", "none"):
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _cache_path(path).write_text(json.dumps(payload), encoding="utf-8")
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

def day_suite_runs(day: str) -> List[Dict[str, Any]]:
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

    collected: List[Dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        payload = _get(
            "/api/history/data-analysis/suite-runs"
            "?start={start}&end={end}&page={page}&per_page={size}".format(
                start=start, end=end, page=page, size=PAGE_SIZE))
        batch = payload.get("suite_runs") or []
        collected.extend(batch)
        total = payload.get("total")
        if not batch or (total is not None and len(collected) >= total):
            break
    return collected


def _next_day(day: str) -> str:
    moment = datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)
    return moment.strftime("%Y-%m-%d")


def suite_run(run_id: str) -> Dict[str, Any]:
    """One suite run, including the slot -> DUT serial map."""
    return _get("/api/test_suite_run/{}".format(run_id), cache=True)


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


def run_url(run_id: str, slot: Optional[int]) -> str:
    """The link the tracker sheet itself uses, rebuilt exactly."""
    url = "{}/suite_run/{}".format(base_url(), run_id)
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
