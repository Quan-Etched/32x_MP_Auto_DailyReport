"""Wafer sort and final test, per die, from the systems that actually hold them.

WHAT THIS IS NOT
OCP/EOS does not carry WST or FT. That was worth checking rather than assuming,
and the answer is flat: ``levels()`` returns l6, l10, l11, slt, module, bringup,
and the readable ones hold only mlt, rdqs_sweep_training and
chip_tpm_hsm_token_check. There is no wafer-sort or final-test level to ask for.
So a pipeline for these two stations cannot be a copy of the pipeline for MLT
and HTT, however much it would like to be.

WHERE THE DATA IS, IN ORDER OF HOW MUCH IT DESERVES TO BE TRUSTED

0. SiVal — ``sival/`` in this repo, and the answer to "is there a backend that
   already counts this". Yes: a Flask + Postgres dashboard whose schema is built
   for exactly these three stages. ``lot_phase_stats`` carries
   ``(lot_id, test_phase, tested_dies, passed_dies, failed_dies, yield_pct,
   last_updated)`` with ``test_phase`` in Wafersort / FinalTest / SLT, kept by
   triggers. ``session_test_result`` carries ``session_type`` — the same three
   phases — with ``start_ts`` and ``overall_status``, which is per-insertion
   with a clock and therefore everything daily, weekly and hourly buckets need.
   This is the source. The other entries below are what to do until it is
   reachable.

   Reachability, probed 2026-08-30 from both a laptop and the dashboard host:
   ``sival-dashboard-dev0`` answers on :5001; ``sival-dashboard-prod0``
   refuses the connection on 80, 443 and 5001 and times out on 8080, 3000 and
   5432. Dev is seeded with placeholder lots — "Lot 1", "USHL Lot" — where the
   real ones are U8G375 and N8R264, its FinalTest and SLT counts are zero, and
   its newest session is February. So the shape is right and the data is not.

   What that costs, precisely: the collector below reads SiVal when it can, and
   one of two things unblocks the real numbers — the prod API exposed to the
   dashboard host, or read credentials for the replica in ``DB_READ_HOST``.

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

#: SiVal's API. Dev by default because it is the one that answers; point this
#: at prod the moment prod is reachable and nothing else changes.
SIVAL_URL = os.environ.get(
    "SIVAL_URL", "http://sival-dashboard-dev0.usw2.i.etched.com:5001")

#: SiVal's phase names, and ours. Its vocabulary is the STDF one.
SIVAL_PHASE = {"Wafersort": "wst", "FinalTest": "ft", "SLT": "slt"}

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


def sival(path: str) -> Any:
    """One SiVal API call."""
    url = "{}/{}".format(SIVAL_URL.rstrip("/"), path.lstrip("/"))
    try:
        return json.loads(_get(url).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ChipDataUnavailable("{}: {}".format(url, exc)) from exc


def sival_stations() -> Dict[str, Dict[str, Any]]:
    """WST, FT and SLT as SiVal counts them, per phase and per lot.

    Read from the rollups SiVal's own frontend reads, so a number here and a
    number on that dashboard cannot disagree — which is the point of using it
    rather than re-deriving yield from the datalogs a second time.
    """
    # project_yield_stats, not test_phase_breakdown.
    #
    # The breakdown endpoint's denominator is `total_dies` — every die in the
    # lot, whether that phase touched it or not. Dividing by that gave FinalTest
    # "0.0% over 19863 dies" when the truth is that FinalTest has tested none of
    # them. 0% and "not measured" are opposite claims about a station, and the
    # first one would have gone on a page. project_yield_stats reports
    # `*_tested` and `*_passed`, which are the two numbers a yield is made of.
    stats = sival("/api/project_yield_stats") or {}
    lots = sival("/api/lot_trend")

    counts = {
        "wst": (stats.get("wafersort_tested"), stats.get("wafersort_passed")),
        "ft": (stats.get("finaltest_tested"), stats.get("finaltest_passed")),
        "slt": (stats.get("slt_tested"), stats.get("slt_passed")),
    }

    out: Dict[str, Dict[str, Any]] = {}
    for key, (tested, passed) in counts.items():
        tested = tested or 0
        passed = passed or 0
        # A phase that has tested nothing is reported as untested, not as zero.
        if not tested:
            out[key] = {
                "station": key, "yield": None, "dies": 0, "passed": 0,
                "source": "sival:{}".format(SIVAL_URL),
                "sourceKind": "database", "hasClock": True,
                "note": "this phase has tested no dies in the database read",
                "collectedAt": datetime.now(timezone.utc).replace(
                    microsecond=0).isoformat(),
                "byWafer": [], "bins": [], "lots": [],
            }
            continue
        out[key] = {
            "station": key,
            "yield": _rate(passed, tested),
            "dies": tested,
            "passed": passed,
            "source": "sival:{}".format(SIVAL_URL),
            # A rollup kept live by triggers, not a file somebody exported.
            "sourceKind": "database",
            # session_test_result has start_ts, so daily and hourly are
            # available from this source — through SQL, see the note in
            # sival_daily().
            "hasClock": True,
            "collectedAt": datetime.now(timezone.utc).replace(
                microsecond=0).isoformat(),
            "byWafer": [],
            "bins": [],
            "lots": [],
        }

    # Per lot, which is the grain people actually ask about — "how did U8G384
    # come out" — and the grain the hand-reported figure is quoted at.
    for row in lots or []:
        name = row.get("lot_name") or ""
        for key, tested_field, passed_field in (
                ("wst", "ws_tested", "ws_passed"),
                ("ft", "ft_tested", "ft_passed")):
            station = out.get(key)
            if not station:
                continue
            tested = row.get(tested_field) or 0
            if not tested:
                continue
            station["byWafer"].append({
                "wafer": name, "dies": tested,
                "passed": row.get(passed_field) or 0,
                "yield": _rate(row.get(passed_field) or 0, tested),
            })
            if name not in station["lots"]:
                station["lots"].append(name)
    return out


#: What SiVal's ``passed_dies`` actually counts, and why it is not the yield.
#:
#: Traced on U8G590 wafer 1: 62 dies, exactly 2 with ``wafer_sort_complete``
#: true, exactly 2 with zero failing functional tests, and ``ws_pass`` = 2. So
#: the rule is "a die passed if every one of its ~3940 tests passed". On U8G621
#: no die clears that bar — every die has between 3 and 38 failures out of
#: ~3940 — so the lot reports 0 passed over 1426 tested.
#:
#: Wafer sort yield is not that. It is the bin-1 rate, and binning tolerates
#: failing tests that are not gating — redundancy, repairable lanes, and
#: parametric tests that inform rather than reject. That is the whole of the
#: gap the publishability guard keeps flagging: 4.84% from SiVal against 32.5%
#: reported is not missing data, it is a different definition. strata6's
#: die_yield_summary.csv, which does carry hard_bin, puts bin 1 at 41.1%.
#:
#: So the number to want from SiVal is a bin, and the bin is in the STDF it
#: ingests. Until ``passed_dies`` is derived from the bin rather than from a
#: clean sweep of every test, SiVal can say which lots ran and when — which it
#: does accurately — and cannot say what they yielded.
SIVAL_PASS_RULE = "every functional test passed (not the bin-1 rate)"


def sival_activity() -> List[Dict[str, Any]]:
    """Which lots were tested, how many dies, and when.

    The part of SiVal that is correct today and worth having. It answers the
    question Helen was answering by hand — "U8G621 completed last week, -623 and
    -624 are still being tested" — from the database, with the die counts and
    the session dates behind it.

    Deliberately separate from the yield. Die counts and dates are ingested and
    trustworthy; the pass determination is not the production one, so mixing
    them into one figure would launder a wrong number in beside right ones.
    """
    lots = sival("/api/lot_trend") or []
    out: List[Dict[str, Any]] = []
    for row in lots:
        tested = row.get("ws_tested") or 0
        if not tested:
            continue
        out.append({
            "lot": row.get("lot_name") or "",
            "lotId": row.get("lot_id"),
            "diesTested": tested,
            # Named, not called a yield: this is SiVal's clean-sweep count, and
            # the note says so wherever it is shown.
            "cleanSweepDies": row.get("ws_passed") or 0,
            "passRule": SIVAL_PASS_RULE,
        })
    return sorted(out, key=lambda item: -item["diesTested"])


def sival_daily() -> Dict[str, Any]:
    """The daily series, and what is missing from it.

    ``/api/yield_trend`` groups ``session_test_result`` by day, which proves the
    clock is there — but it is not usable as a per-station feed as it stands,
    for two reasons worth writing down because both are one-line fixes in
    SiVal rather than problems here:

      * it formats the day as ``TO_CHAR(..., 'Mon DD')`` — "Jan 28", with no
        year, so it cannot be bucketed into a week without guessing;
      * it does not filter or group by ``session_type``, so WST, FT and SLT are
        pooled into one number.

    Reported rather than worked around: a collector that parsed "Jan 28" and
    assumed a year would be inventing data, and one that presented a pooled
    figure as WST would be mislabelling it.
    """
    try:
        trend = sival("/api/yield_trend")
    except ChipDataUnavailable as exc:
        return {"available": False, "why": str(exc)}
    return {
        "available": False,
        "points": len(trend or []),
        "why": "yield_trend gives 'Mon DD' with no year and pools every "
               "session_type, so it cannot be split per station or bucketed "
               "into weeks. Needs either DATE(start_ts) and a GROUP BY "
               "session_type in SiVal, or direct SQL against the same table.",
        "sample": (trend or [])[:3],
    }


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
            "sivalPassRule": "SiVal's passed_dies counts dies where every "
                             "functional test passed — traced on U8G590: 2 of "
                             "62 dies clean-sweep, 2 wafer_sort_complete, "
                             "ws_pass 2. Wafer sort yield is the bin-1 rate, "
                             "which tolerates non-gating failures, so SiVal "
                             "reads 4.84% against 32.5% reported. That gap is "
                             "a definition, not missing data: derive "
                             "passed_dies from the hard bin and this becomes "
                             "the source.",
            "sival": "SiVal is the source: lot_phase_stats has per-phase "
                     "WST/FT/SLT counts and session_test_result has start_ts "
                     "for daily and hourly. prod0 refuses connections on 80, "
                     "443 and 5001 from the dashboard host; dev0 answers but "
                     "is seeded with placeholder lots and has no FinalTest "
                     "rows. Expose prod to the dashboard host, or give this "
                     "collector DB_READ_HOST credentials.",
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

    # SiVal first: it is the system built for this, and its rollups are what its
    # own dashboard shows.
    try:
        from_sival = sival_stations()
    except ChipDataUnavailable as exc:
        from_sival = {}
        out["problems"]["sival"] = str(exc)
    for name, summary in from_sival.items():
        _judge(name, summary, reported)
        out["stations"][name] = summary
    out["daily"] = sival_daily()
    try:
        out["activity"] = sival_activity()
    except ChipDataUnavailable as exc:
        out["problems"]["activity"] = str(exc)

    for name, fetch in (("wst", wafer_sort), ("ft", final_test)):
        try:
            summary = summarise(fetch())
        except ChipDataUnavailable as exc:
            out["problems"][name] = str(exc)
            continue
        _judge(name, summary, reported)
        # SiVal wins where it has anything: a live rollup beats a file someone
        # exported. The snapshot is kept beside it, because its bin Pareto is
        # real and SiVal's endpoints do not expose one.
        existing = out["stations"].get(name)
        if existing and existing.get("dies"):
            existing["snapshot"] = summary
        else:
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
