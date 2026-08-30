"""Wafer sort and final test, per die, from the systems that actually hold them.

WHAT THIS IS NOT
OCP/EOS does not carry WST or FT. That was worth checking rather than assuming,
and the answer is flat: ``levels()`` returns l6, l10, l11, slt, module, bringup,
and the readable ones hold only mlt, rdqs_sweep_training and
chip_tpm_hsm_token_check. There is no wafer-sort or final-test level to ask for.
So a pipeline for these two stations cannot be a copy of the pipeline for MLT
and HTT, however much it would like to be.

WHERE THE DATA IS, IN ORDER OF HOW MUCH IT DESERVES TO BE TRUSTED

1. SPLM — ``https://splm.i.etched.com/api/v1/query``, read-only SQL. Up and
   answering; it wants a bearer token and we do not have one, so it replies
   ``{"code":"TOKEN_MISSING"}``. This is the source this module is *written
   for*: a query language over the datalog store can give per-insertion rows
   with timestamps, which is what daily and hourly buckets require. Set
   ``SPLM_TOKEN`` and it becomes the primary with no other change.

2. strata6 — ``http://strata6.sv9.i.etched.com:8235``, which is a
   ``SimpleHTTP`` directory listing of somebody's working directory. It holds
   real per-die analysis: ``die_yield_summary.csv`` is 497 dies with hard and
   soft bins, ``hbm_ft_vs_slt.csv`` is 319 dies with FT bins joined to their SLT
   verdict. Both are used here, and both are treated as **snapshots, not
   feeds**, because that is what they are: a person's output file, rewritten
   when that person next runs their script.

THE LIMIT THAT MATTERS, STATED PLAINLY
Neither CSV has a date column. Not one — checked, zero date-ish fields in
either. So these sources can support a *standing figure* for a station ("wafer
sort is running at N%"), and they cannot support the daily or hourly buckets the
other stations have, because there is no time to bucket on. Presenting a
snapshot on a daily chart would draw a flat line across every day and imply a
measurement per day that nobody made.

What unblocks daily and hourly is (1) an SPLM token, or (2) read access to the
``bringup`` bucket in EOS, which holds the chip screening these dies go through
and is refused today with ``level_unavailable`` on
``etched-mfg-prod-bringup-raw``. Either one turns this module into the same
shape as every other station. Until then it computes the number that used to be
typed by hand, and says where it came from and that it has no clock.

THE JOIN, WHICH DOES WORK
The station registry says joining chip data to this dashboard is blocked because
we have no chip serial — pega3 returns ``asic_lot_code`` and it is empty on
every run. True of pega3, and not the whole picture: ``hbm_ft_vs_slt.csv``
carries ``serial``, the 22-character JE… serial, and the EOS ``slt`` level
reports on those same serials. So FT rows can be joined to SLT rows today, and
``die`` (``LOT_Wnn_Xn_Yn``) gives the wafer coordinate for a per-wafer rollup.
"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import config

#: Read-only SQL over the datalog store. The source this module is written for.
SPLM_URL = os.environ.get("SPLM_URL", "https://splm.i.etched.com/api/v1/query")

#: A person's working directory, served over HTTP. Not an API, and treated
#: accordingly: every figure from here is labelled a snapshot.
STRATA_BASE = os.environ.get(
    "FACTORY_STRATA_URL", "http://strata6.sv9.i.etched.com:8235")

#: Per-die wafer sort: wafer, lot, wafer_num, x, y, hard_bin, soft_bin,
#: pass_fail, failing_blocks.
WST_FILE = "die_yield_summary.csv"

#: Per-die final test joined to its SLT verdict, carrying ft_sbin, ft_status,
#: repaired lanes — and the JE serial that makes the join to our own rows
#: possible.
FT_FILE = "hbm_ft_vs_slt.csv"

TIMEOUT = 25.0

#: FT's verdict is the **soft bin**, not ``ft_status``.
#:
#: ``ft_status`` is the HBM repair state — Clean / Repairable / Non-repairable —
#: and reading it as the verdict gave 0% pass over 318 dies, which is how the
#: mistake announced itself. ``ft_sbin`` 1 is the clean pass; every other bin
#: names a way the die failed (SA_FUNC, HBM_REP, MATMUL_FUNC, …).
FT_CLEAN_BIN = "1"

#: Bins that are a pass which cost a repair. Deliberately *not* folded into the
#: yield here: whether a repaired die counts as FT output is a question for
#: whoever owns FT, and this module reporting one answer as fact would settle it
#: by accident. Counted and named, so the choice is visible and cheap to make.
FT_REPAIR_BINS = ("HBM_REP", "HBM_REP_F_DFTM")


class ChipDataUnavailable(RuntimeError):
    """No source answered. The caller decides whether that is fatal."""


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def splm_token() -> str:
    return os.environ.get("SPLM_TOKEN", "").strip()


def splm(query: str) -> List[Dict[str, Any]]:
    """One read-only SQL query. Raises if there is no token or it is refused."""
    token = splm_token()
    if not token:
        raise ChipDataUnavailable(
            "no SPLM_TOKEN; SPLM answers TOKEN_MISSING without one")
    body = json.dumps({"query": query}).encode("utf-8")
    request = urllib.request.Request(SPLM_URL, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise ChipDataUnavailable("SPLM {}: {}".format(
            exc.code, exc.read()[:200].decode("utf-8", "replace"))) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ChipDataUnavailable("SPLM unreachable: {}".format(exc)) from exc
    if isinstance(payload, dict):
        return payload.get("rows") or payload.get("results") or []
    return payload or []


def _strata_csv(name: str) -> List[Dict[str, str]]:
    url = "{}/{}".format(STRATA_BASE.rstrip("/"), name)
    try:
        raw = _get(url).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise ChipDataUnavailable("{}: {}".format(url, exc)) from exc
    return list(csv.DictReader(io.StringIO(raw)))


def wafer_sort() -> Dict[str, Any]:
    """Wafer sort, per die, from whichever source answers.

    No timestamps in the CSV path, so the result carries ``hasClock: False`` and
    the caller must not bucket it by day.
    """
    rows = _strata_csv(WST_FILE)
    dies: List[Dict[str, Any]] = []
    for row in rows:
        verdict = (row.get("pass_fail") or "").strip().upper()
        if not verdict:
            continue
        dies.append({
            "die": "{}_X{}_Y{}".format(row.get("wafer") or "",
                                       row.get("x") or "", row.get("y") or ""),
            "wafer": row.get("wafer") or "",
            "lot": row.get("lot") or "",
            "hardBin": row.get("hard_bin") or "",
            "softBin": row.get("soft_bin") or "",
            "pass": verdict == "PASS",
            "failingBlocks": row.get("failing_blocks") or "",
        })
    return {
        "station": "wst",
        "source": "strata6:{}".format(WST_FILE),
        "sourceKind": "snapshot",
        "hasClock": False,
        "dies": dies,
    }


def ft_die(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """One CSV row to one die.

    Its own function so the mapping can be tested without the network. The
    first version of the test re-implemented this mapping instead of calling
    it, which meant it verified the test's copy and let a broken module pass.
    """
    sbin = (row.get("ft_sbin") or "").strip()
    name = (row.get("ft_sbin_name") or "").strip().upper()
    if not sbin and not name:
        return None
    return {
        "die": row.get("die") or "",
        "lot": row.get("lot") or "",
        # The join key to our own rows: EOS reports the slt level on these same
        # 22-character serials.
        "serial": row.get("serial") or "",
        "sbin": sbin,
        "sbinName": name,
        # The HBM repair state, kept because it is what the file is about — but
        # not the verdict.
        "repairState": (row.get("ft_status") or "").strip(),
        "pass": sbin == FT_CLEAN_BIN,
        "repaired": name in FT_REPAIR_BINS,
        "insertions": row.get("ft_insertions") or "",
        "sltVerdict": (row.get("slt_verdict_type") or "").strip().upper(),
    }


def final_test() -> Dict[str, Any]:
    """Final test, per die, with the SLT verdict beside it where there is one."""
    dies = [die for die in (ft_die(row) for row in _strata_csv(FT_FILE))
            if die is not None]
    return {
        "station": "ft",
        "source": "strata6:{}".format(FT_FILE),
        "sourceKind": "snapshot",
        "hasClock": False,
        "dies": dies,
    }


def _rate(passed: int, total: int) -> Optional[float]:
    return (passed / total) if total else None


def summarise(got: Dict[str, Any]) -> Dict[str, Any]:
    """One station's dies to the shape the weekly page already reads."""
    dies = got.get("dies") or []
    total = len(dies)
    passed = sum(1 for die in dies if die["pass"])
    repaired = sum(1 for die in dies if die.get("repaired"))
    out = {
        "station": got["station"],
        "yield": _rate(passed, total),
        "dies": total,
        "passed": passed,
        "source": got["source"],
        "sourceKind": got["sourceKind"],
        # False means: do not draw this on a per-day axis. There is no date in
        # the source, so a daily series would be one number repeated.
        "hasClock": got["hasClock"],
        "collectedAt": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
    }
    if repaired:
        # NOT in `yield` above. A repaired die is a pass that cost a repair, and
        # whether FT counts it as output is a decision this module must not make
        # silently — so it is counted, named, and left for the owner.
        out["repaired"] = repaired
        out["repairRate"] = _rate(repaired, total)
        out["yieldWithRepairs"] = _rate(passed + repaired, total)
    # Why the failures failed. This is the part of these files that is useful
    # regardless of the population question below — a bin Pareto for the two
    # stations that have never had one here.
    bins: Dict[str, int] = {}
    for die in dies:
        key = die.get("sbinName") or die.get("hardBin") or ""
        if key:
            bins[key] = bins.get(key, 0) + 1
    out["bins"] = [{"bin": k, "dies": v} for k, v in
                   sorted(bins.items(), key=lambda kv: (-kv[1], kv[0]))]
    out["lots"] = sorted({die.get("lot") for die in dies if die.get("lot")})
    # Per wafer, because wafer sort is a wafer-level question and a single
    # line-wide percentage hides a bad wafer inside a good lot.
    per_wafer: Dict[str, Dict[str, int]] = {}
    for die in dies:
        key = die.get("wafer") or die.get("lot") or ""
        if not key:
            continue
        bucket = per_wafer.setdefault(key, {"dies": 0, "passed": 0})
        bucket["dies"] += 1
        bucket["passed"] += 1 if die["pass"] else 0
    out["byWafer"] = [
        {"wafer": key, "dies": v["dies"], "passed": v["passed"],
         "yield": _rate(v["passed"], v["dies"])}
        for key, v in sorted(per_wafer.items())
    ]
    return out


#: How far a computed figure may sit from the reported one before this module
#: refuses to call it publishable. Five points is generous; the gaps found are
#: nine and forty-eight.
REPORTED_TOLERANCE = 0.05


def _reported() -> Dict[str, Any]:
    """The hand-reported figures, for comparison only."""
    path = config.REPO_ROOT / "weekly" / "external_yields.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _judge(station: str, computed: Dict[str, Any],
           reported: Dict[str, Any]) -> None:
    """Decide whether a computed figure may replace the reported one.

    THE POINT OF THIS FUNCTION
    It would be easy to compute a number off these CSVs, put it on the weekly
    page, and retire the hand-typed one. It would also be wrong, and the data
    says so out loud:

      * WST computes 41.1% over lots U8G375 and U8G384; the reported figure is
        32.5% over "two lots". Nine points apart.
      * FT computes 36.2% clean over lots U8G386/387/388/401 — a different set
        of lots entirely — against a reported 84.3%. The file is named
        hbm_ft_vs_slt and its bin mix is 107 SA_FUNC out of 318, which is a
        screening population, not a production one.

    So these are somebody's analysis subsets: the right dies for the question
    that person was asking, and the wrong dies for "what is the line yielding".
    A subset is not a smaller version of the whole — it is a different
    population — and swapping one for the other on a page people quote is how a
    dashboard starts lying with real data.

    The figures are still worth having as diagnostics, above all the bin
    Pareto, which neither station has ever had here. They are marked
    unpublishable until a source arrives that covers the production population,
    and the gap is recorded so the marking can be checked rather than believed.
    """
    said = reported.get(station) or {}
    theirs = said.get("yield")
    ours = computed.get("yield")
    computed["reportedYield"] = theirs
    computed["reportedAsOf"] = said.get("asOf")
    if theirs is None or ours is None:
        computed["publishable"] = False
        computed["whyNotPublishable"] = (
            "nothing to compare against" if theirs is None
            else "no dies in the source")
        return
    gap = abs(ours - theirs)
    computed["gapToReported"] = round(gap, 4)
    if gap <= REPORTED_TOLERANCE:
        computed["publishable"] = True
        return
    computed["publishable"] = False
    computed["whyNotPublishable"] = (
        "computed {:.1%} over {} dies in lots {} against {:.1%} reported as of "
        "{} — {:.0f} points apart, so this source is not the production "
        "population and must not replace the reported figure"
        .format(ours, computed.get("dies"),
                ", ".join(computed.get("lots") or []) or "unknown",
                theirs, said.get("asOf") or "unknown", gap * 100))


def collect() -> Dict[str, Any]:
    """Both stations, with whatever each source could give and why."""
    out: Dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "stations": {},
        "problems": {},
        # Recorded so the page can say what is blocking daily/hourly rather
        # than leaving a reader to wonder why these two stations are different.
        "blocked": {
            "eos": "OCP/EOS carries no wafer-sort or final-test level. Readable "
                   "levels are l6, l10, slt, module.",
            "bringup": "EOS level 'bringup' holds the chip screening these dies "
                       "go through and is refused: level_unavailable on "
                       "etched-mfg-prod-bringup-raw. Read access there would "
                       "give chip level the same pipeline as every other "
                       "station.",
            "splm": ("no SPLM_TOKEN set; SPLM is reachable and answers "
                     "TOKEN_MISSING. A token is what unblocks daily and hourly."
                     if not splm_token() else ""),
            "clock": "The strata6 CSVs carry no date column, so these figures "
                     "are snapshots and cannot be bucketed by day or hour.",
        },
    }
    reported = _reported()
    for name, fetch in (("wst", wafer_sort), ("ft", final_test)):
        try:
            summary = summarise(fetch())
        except ChipDataUnavailable as exc:
            out["problems"][name] = str(exc)
            continue
        _judge(name, summary, reported)
        out["stations"][name] = summary
    out["blocked"] = {k: v for k, v in out["blocked"].items() if v}
    return out


def write_bundle(bundle: Dict[str, Any], path=None):
    target = path or (config.DASHBOARD_DATA_DIR / "chips.js")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "// Generated by `python -m factory.cli chips` — do not edit.\n"
        "window.__FACTORY_CHIPS__ = "
        + json.dumps(bundle, separators=(",", ":"), sort_keys=True)
        + ";\n", encoding="utf-8")
    return target
