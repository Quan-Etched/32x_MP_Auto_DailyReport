"""Command line entry point.

    python -m factory.cli levels
    python -m factory.cli runs   --level l10 --from 2026-08-03 --to 2026-08-03
    python -m factory.cli inspect --level l10 --from 2026-08-03 --to 2026-08-03
    python -m factory.cli collect --level l10 --days 2
    python -m factory.cli demo    --days 2
    python -m factory.cli build
    python -m factory.cli report
    python -m factory.cli serve
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from . import collect as collect_mod
from . import build_dashboard, config, demo_data, hourly
from .eos_client import EOSClient, EOSError


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )
    config.load_dotenv()
    config.ensure_dirs()

    try:
        return args.handler(args)
    except EOSError as exc:
        print("EOS API error: {}".format(exc), file=sys.stderr)
        return 2
    except (RuntimeError, FileNotFoundError) as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1


# ------------------------------------------------------------------- subcommands

def cmd_trust(args: argparse.Namespace) -> int:
    """Install the internal CA bundle needed to reach the EOS host over TLS."""
    from . import trust

    try:
        path = trust.install(expected=args.fingerprint)
    except trust.TrustError as exc:
        print("Trust bootstrap failed: {}".format(exc), file=sys.stderr)
        return 3

    print("Installed internal CA bundle -> {}".format(path))
    print("Verified: a TLS connection to the EOS host now succeeds.")
    print("This path is picked up automatically; override it with EOS_CA_BUNDLE.")
    return 0


def cmd_levels(args: argparse.Namespace) -> int:
    client = EOSClient(use_cache=not args.no_cache)
    print(json.dumps(client.levels(), indent=2))
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    client = EOSClient(use_cache=not args.no_cache)
    window = _window(args)
    runs = client.runs(level=args.level, frm=window["from"], to=window["to"])
    print(json.dumps(runs[: args.limit], indent=2))
    print("\n{} runs in {} .. {}".format(len(runs), window["from"], window["to"]),
          file=sys.stderr)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Print the field names the live API actually returns.

    Use this the first time you point the ETL at real data: it tells you whether
    the alias tables in ``parse.py`` already cover this deployment's spelling.
    """
    client = EOSClient(use_cache=not args.no_cache)
    window = _window(args)
    runs = client.runs(level=args.level, frm=window["from"], to=window["to"])
    if not runs:
        print("No runs in window — widen --from/--to.", file=sys.stderr)
        return 1

    print("=== /runs entry keys ===")
    _print_keys(runs)
    sample = runs[0]
    print("\n=== first /runs entry ===")
    print(json.dumps(sample, indent=2)[:2000])

    record = collect_mod.parse.parse_run(sample, args.level)
    print("\n=== parsed by parse.parse_run() ===")
    print(json.dumps({k: v for k, v in record.items() if k != "tests"}, indent=2))
    _flag_unresolved(record)

    if not record.get("dutSerial"):
        print("\nNo dutSerial resolved — cannot inspect artifacts.", file=sys.stderr)
        return 1

    artifacts = client.artifacts(
        level=args.level,
        dut_serial=record["dutSerial"],
        run_id=record["runId"],
        role=config.ROLE_SUITE_SUMMARY,
    )
    print("\n=== /artifacts (role=suite_summary) ===")
    print(json.dumps(artifacts[:10], indent=2))

    rel_path = collect_mod._pick_summary_path(artifacts)
    if not rel_path:
        print("\nNo suite_summary artifact matched.", file=sys.stderr)
        return 1

    raw = client.artifact_content(
        level=args.level,
        dut_serial=record["dutSerial"],
        run_id=record["runId"],
        rel_path=rel_path,
    )
    print("\n=== suite_summary head ({}) ===".format(rel_path))
    print(raw.decode("utf-8", "replace")[:1500])

    tests = collect_mod.parse.parse_suite_summary(raw)
    print("\n=== parsed by parse.parse_suite_summary(): {} tests ===".format(len(tests)))
    print(json.dumps(tests[:3], indent=2))
    if not tests:
        print(
            "\nZERO tests parsed. Add this deployment's key spellings to the "
            "*_ALIASES tables in src/factory/parse.py.",
            file=sys.stderr,
        )
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    client = EOSClient(use_cache=not args.no_cache)
    window = _window(args)
    levels = args.levels or [args.level]
    payload = collect_mod.collect(
        client,
        levels=levels,
        frm=window["from"],
        to=window["to"],
        max_workers=args.workers,
        fetch_summaries=not args.no_summaries,
    )
    path = collect_mod.write_runs(payload)
    print("Wrote {} runs -> {}".format(payload["runCount"], path))
    if payload["problems"]:
        print("{} problems (first 5):".format(len(payload["problems"])), file=sys.stderr)
        for problem in payload["problems"][:5]:
            print("  - {}".format(problem), file=sys.stderr)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    payload = demo_data.generate(days=args.days, level=args.level, seed=args.seed)
    path = collect_mod.write_runs(payload)
    print("Wrote {} synthetic runs -> {}".format(payload["runCount"], path))
    return cmd_build(args)


def cmd_refresh(args: argparse.Namespace) -> int:
    """One scheduler tick: collect, record fetch state, rebuild both bundles.

    Distinguishes a fetch from an update. A tick that returns the same data
    advances only ``lastFetchAt``; ``lastUpdateAt`` moves only when the content
    hash changes. Exit code is 0 for both — "nothing changed" is a healthy
    outcome, not a failure.

    With ``--with-items`` it also ingests the event streams of any newly seen
    runs before building, so the releases page moves with the rest. That is the
    chain the Update button and the hourly agent both run.
    """
    from . import fetchstate, items as items_mod, stations

    client_levels = args.levels or stations.levels_to_collect() + stations.blocked_levels()
    window = collect_mod.default_window(days=args.days)

    _step("collect", "Fetching runs from EOS")
    try:
        client = EOSClient(use_cache=False)  # a scheduler must never serve a cache
        payload = collect_mod.collect(
            client,
            levels=client_levels,
            frm=window["from"],
            to=window["to"],
            max_workers=args.workers,
        )
    except (EOSError, RuntimeError) as exc:
        fetchstate.record_failure(str(exc))
        print("Fetch FAILED: {}".format(exc), file=sys.stderr)
        # EOS being down must not freeze the pages that do not come from EOS.
        # Half this dashboard is built from the controllers now, and stopping
        # here left the station page, both trackers and the validation page
        # sitting at whatever they said when EOS last answered — stale without
        # looking stale. So rebuild from the last stored payload: the
        # EOS-sourced pages repeat themselves, the pega-sourced ones move, and
        # every page's header carries the failed fetch. Still exit 2, because
        # the fetch really did fail and the log should say so.
        try:
            _step("build", "EOS unreachable - rebuilding what does not need it")
            cmd_build(args)
        except Exception as build_exc:                    # noqa: BLE001
            print("Rebuild after failed fetch also failed: {}".format(build_exc),
                  file=sys.stderr)
        return 2

    # An unreachable EOS does not raise: the collector records the failure per
    # level and returns an empty payload, which then overwrote the stored runs
    # with nothing and published a dashboard reading zero everywhere. Measured,
    # not theorised — one pointed-at-a-dead-host run reduced a 30-day snapshot
    # to 0 runs and the station bundle from 145 KB to 18 KB.
    #
    # So an empty payload with errors on it is a failed fetch, not a fetch that
    # found nothing. A genuinely quiet window has no level errors and is still
    # written.
    if _is_empty_failure(payload):
        try:
            held = collect_mod.read_runs()
        except (OSError, ValueError):
            held = {}
        if held.get("runs"):
            detail = "; ".join("{}: {}".format(level, str(err)[:80])
                               for level, err in payload["levelErrors"].items())
            fetchstate.record_failure(detail)
            print("Fetch FAILED, keeping the {} runs already collected: {}".format(
                len(held["runs"]), detail), file=sys.stderr)
            try:
                _step("build", "EOS unreachable - rebuilding what does not need it")
                cmd_build(args)
            except Exception as build_exc:                # noqa: BLE001
                print("Rebuild after failed fetch also failed: {}".format(build_exc),
                      file=sys.stderr)
            return 2

    collect_mod.write_runs(payload)
    state = fetchstate.record_fetch(payload)

    # Before the build: the releases bundle is compiled *from* the item store,
    # so ingesting after it would publish items one tick late.
    if getattr(args, "with_items", False):
        _step("items", "Flattening new runs to test items")
        conn = items_mod.open_db()
        try:
            stats = items_mod.ingest_runs(
                conn, EOSClient(use_cache=True), _ingestable_runs(payload),
                on_progress=lambda done, added, total: print(
                    "  ingested {}/{} runs, {} item rows".format(done, total, added)),
                on_error=lambda run_id, err: print(
                    "  {}: {}".format(run_id[:44], err[:80]), file=sys.stderr),
            )
        finally:
            conn.close()
        print("Items  : {} new runs, {} rows ({} already present{})".format(
            stats["runs"], stats["rows"], stats["skipped"],
            ", {} failed".format(stats["failed"]) if stats["failed"] else ""))

    _step("build", "Rebuilding the dashboard bundles")
    cmd_build(args)

    changed = state.get("changed")
    print("Fetch  : {}  ({} runs)".format(state["lastFetchAt"], state.get("runCount")))
    if changed:
        print("Update : {}  <- content changed".format(state["lastUpdateAt"]))
    else:
        print("Update : {}  (unchanged for {} consecutive fetches)".format(
            state.get("lastUpdateAt") or "never", state.get("consecutiveNoChange")))
    if payload.get("levelErrors"):
        for level, err in payload["levelErrors"].items():
            print("  level {} unavailable: {}".format(level, err[:120]), file=sys.stderr)
    return 0


def _is_empty_failure(payload: Dict[str, Any]) -> bool:
    """Did this fetch come back empty *because it failed*?

    An unreachable EOS does not raise — the collector records the failure per
    level and returns a payload with no runs. Written to disk, that replaces
    the collected history with nothing. A genuinely quiet window looks the same
    except that nothing errored, and it is still written.
    """
    return not payload.get("runs") and bool(payload.get("levelErrors"))


def cmd_build(args: argparse.Namespace) -> int:
    from . import build_runs, build_stations, fetchstate, items as items_mod, releases

    payload = collect_mod.read_runs()
    bundle = build_dashboard.build_bundle(payload)
    path = build_dashboard.write_bundle(bundle)
    size_kb = path.stat().st_size / 1024
    print(
        "Bundled {} runs ({:.0f} KB) -> {}".format(len(bundle["runs"]), size_kb, path)
    )

    state = fetchstate.load()
    # Station yield from the controllers, alongside the EOS-sourced one. Its
    # own page, because the two disagree and the difference is the point.
    from . import pega_collect
    pega_bundle = None
    try:
        pega_payload = pega_collect.collect(days=30)
    except Exception as exc:                              # noqa: BLE001
        print("Pega stations skipped ({})".format(exc))
    else:
        if pega_payload["runs"]:
            pega_bundle = build_stations.build_bundle(
                pega_payload, pega_collect.fetch_state(pega_payload))
            pega_path = build_stations.write_bundle(
                pega_bundle, config.DASHBOARD_DATA_DIR / "pega_stations.js")
            print("Pega stations ({:.0f} KB, {} unit runs) -> {}".format(
                pega_path.stat().st_size / 1024, pega_payload["runCount"], pega_path))
        else:
            print("Pega stations skipped (controllers returned nothing)")

    stations_bundle = build_stations.build_bundle(payload, state)
    # Both pages now exist, so the difference between them can be measured
    # rather than described. It goes on the EOS page, which is the one a reader
    # lands on and the one whose numbers get challenged.
    if pega_bundle is not None:
        from . import compare
        stations_bundle["comparison"] = compare.build(stations_bundle, pega_bundle)
    stations_path = build_stations.write_bundle(stations_bundle)
    print("Stations bundle ({:.0f} KB) -> {}".format(
        stations_path.stat().st_size / 1024, stations_path))

    # The run-level drill-down every number on the station page links into.
    runs_bundle = build_runs.build_bundle(payload, state)
    runs_path = build_runs.write_bundle(runs_bundle)
    print("Runs bundle ({:.0f} KB, {} runs, {} test names) -> {}".format(
        runs_path.stat().st_size / 1024, len(runs_bundle["runs"]),
        len(runs_bundle["testNames"]), runs_path))

    # What we need from other systems, with the checkable asks re-checked. The
    # probes reach the network, so failures are swallowed inside build_bundle:
    # an unreachable host is an answer here, not an error.
    from . import requests as requests_mod
    requests_bundle = requests_mod.build_bundle(payload)
    requests_path = requests_mod.write_bundle(requests_bundle)
    print("Requests ({} open with other teams, {} blocking) -> {}".format(
        len(requests_bundle["requests"]), requests_bundle["openBlocking"],
        requests_path))

    # The L10 tracker, straight from pega4. No workbook behind it, so an
    # unreachable controller means no page rather than a failed build.
    from . import build_l10
    try:
        l10_bundle = build_l10.build_bundle()
    except Exception as exc:                              # noqa: BLE001
        print("L10 tracker skipped ({})".format(exc))
    else:
        if l10_bundle["tabs"]:
            l10_path = build_l10.write_bundle(l10_bundle)
            print("L10 tracker ({:.0f} KB, {} days) -> {}".format(
                l10_path.stat().st_size / 1024, len(l10_bundle["tabs"]), l10_path))
        else:
            print("L10 tracker skipped (pega4 returned no runs)")

    # The line's hand-kept tracker. It has no API behind it, so a repo without
    # the export simply does not get the page — never a failed build.
    from . import build_dailyexcel
    try:
        daily_bundle = build_dailyexcel.build_bundle(payload)
    except FileNotFoundError as exc:
        print("Daily tracker skipped ({})".format(exc))
    else:
        daily_path = build_dailyexcel.write_bundle(daily_bundle)
        print("Daily tracker ({:.0f} KB, {} tabs) -> {}".format(
            daily_path.stat().st_size / 1024, len(daily_bundle["tabs"]), daily_path))
        for warning in daily_bundle["warnings"]:
            print("  WARNING {}".format(warning), file=sys.stderr)

    # The week's first-pass yield, one row per test step — the summary the
    # Monday meeting reads. Cheap: it reuses the controller payload above.
    if pega_bundle is not None:
        from . import build_fpy
        try:
            fpy_path = build_fpy.write_bundle(build_fpy.build_bundle(pega_payload))
            print("FPY summary ({:.0f} KB) -> {}".format(
                fpy_path.stat().st_size / 1024, fpy_path))
        except Exception as exc:                          # noqa: BLE001
            print("FPY summary skipped ({})".format(exc))

    # The weekly tracker — every week Monday to Sunday, and the unit rows
    # behind each number so anyone can check it.
    if pega_bundle is not None:
        from . import build_weekly
        try:
            wk_path = build_weekly.write_bundle(
                build_weekly.build_bundle(pega_payload))
            print("Weekly tracker ({:.0f} KB) -> {}".format(
                wk_path.stat().st_size / 1024, wk_path))
        except Exception as exc:                          # noqa: BLE001
            print("Weekly tracker skipped ({})".format(exc))

    # The releases page needs the item store; skip rather than fail when it has
    # not been built yet (`make items`).
    if items_mod.DB_PATH.exists():
        conn = items_mod.open_db()
        try:
            # NB: not `bundle` -- that name is still the hourly bundle below.
            rel_bundle = releases.build_bundle(conn, payload)
            n_releases = len(rel_bundle["releases"])
            n_items = len(rel_bundle["items"])
            rel_path, n_detail = releases.write_bundle(rel_bundle)
            print("Releases index ({:.0f} KB, {} releases, {} items) + {} detail "
                  "files -> {}".format(rel_path.stat().st_size / 1024, n_releases,
                                       n_items, n_detail, rel_path))
        finally:
            conn.close()
    else:
        print("  no item store yet — run `make items` to enable the releases page",
              file=sys.stderr)
    if bundle["notes"]["runsDroppedNoTimestamp"]:
        print(
            "  {} runs dropped: no usable start time".format(
                bundle["notes"]["runsDroppedNoTimestamp"]
            ),
            file=sys.stderr,
        )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    payload = collect_mod.read_runs()
    runs = payload["runs"]
    tz_name = payload.get("timezone")

    head = hourly.summary(runs, tz_name)
    print("=" * 72)
    print("Manufacturing summary  {} .. {}  ({})".format(
        payload["window"].get("from"), payload["window"].get("to"), tz_name))
    print("=" * 72)
    print("  runs             {}".format(head["runs"]))
    print("  units            {}".format(head["units"]))
    print("  active hours     {}".format(head["activeHours"]))
    print("  units / hour     {}".format(_num(head["unitsPerHour"], 2)))
    print("  pass rate        {}".format(_pct(head["passRate"])))
    print("  first-pass yield {}".format(_pct(head["firstPassYield"])))
    print("  cycle p50 / p90  {} / {}".format(
        _dur(head["cycleTimeMedian"]), _dur(head["cycleTimeP90"])))

    print("\n--- hourly ---")
    print("  {:<15} {:>5} {:>6} {:>8} {:>8} {:>9}".format(
        "hour", "runs", "units", "pass%", "FPY%", "p50"))
    for row in hourly.hourly_metrics(runs, tz_name):
        print("  {:<15} {:>5} {:>6} {:>8} {:>8} {:>9}".format(
            row["hour"], row["runs"], row["units"],
            _pct(row["passRate"]), _pct(row["firstPassYield"]),
            _dur(row["cycleTimeMedian"])))

    print("\n--- failure pareto ---")
    for row in hourly.failure_pareto(runs, limit=args.limit):
        print("  {:<32} {:>5}  {:>6}  cum {:>6}  {}".format(
            row["test"][:32], row["failures"], _pct(row["share"]),
            _pct(row["cumulativeShare"]), row["topCode"] or ""))

    print("\n--- stations ---")
    for row in hourly.station_breakdown(runs):
        print("  {:<12} runs {:>5}  units {:>5}  pass {:>7}  p50 {:>9}".format(
            row["station"], row["runs"], row["units"],
            _pct(row["passRate"]), _dur(row["cycleTimeMedian"])))

    repeats = [row for row in hourly.dut_breakdown(runs) if row["failures"] > 1]
    if repeats:
        print("\n--- repeat-failure DUTs ---")
        for row in repeats[:15]:
            print("  {:<16} runs {:>3}  failures {:>3}  last {}".format(
                row["dut"], row["runs"], row["failures"], row["lastStatus"]))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print fetch vs update state — the scheduler's health, at a glance."""
    from . import fetchstate, stations

    state = fetchstate.load()
    if not state.get("lastFetchAttemptAt"):
        print("No fetch has run yet. Try `make refresh`.")
        return 0

    print("last fetch   {}  [{}]".format(
        state.get("lastFetchAttemptAt"), state.get("lastFetchStatus")))
    print("last update  {}".format(state.get("lastUpdateAt") or "never"))
    if state.get("consecutiveNoChange"):
        print("             unchanged for {} consecutive fetches".format(
            state["consecutiveNoChange"]))
    if state.get("lastFetchError"):
        print("last error   {}".format(state["lastFetchError"][:200]))
    print("runs         {}".format(state.get("runCount", "—")))

    print("\nper station:")
    labels = {s["key"]: s["label"] for s in stations.registry()}
    for key, entry in sorted(state.get("stations", {}).items()):
        print("  {:<16} {:>5} runs   last update {}".format(
            labels.get(key, key), entry.get("runs", 0),
            entry.get("lastUpdateAt") or "never"))

    for level, err in (state.get("levelErrors") or {}).items():
        print("\n  level {} unavailable: {}".format(level, err[:160]))
    return 0


def cmd_items(args: argparse.Namespace) -> int:
    """Flatten test cases down to test items, into SQLite, then report.

    The event streams are already fetched for run timing, so this re-reads them
    (from the HTTP cache where possible) and keeps the measurements instead of
    discarding them.
    """
    from . import items as items_mod

    payload = collect_mod.read_runs()
    runs = _ingestable_runs(payload, station=args.station)
    if args.limit:
        runs = sorted(runs, key=lambda r: r.get("startTs") or 0, reverse=True)[: args.limit]

    conn = items_mod.open_db()
    stats = items_mod.ingest_runs(
        conn, EOSClient(use_cache=True), runs, rebuild=args.rebuild,
        on_progress=lambda done, added, total: print(
            "  ingested {}/{} runs, {} item rows".format(done, total, added),
            file=sys.stderr),
        on_error=lambda run_id, err: print(
            "  {}: {}".format(run_id[:44], err[:80]), file=sys.stderr),
    )

    print("Ingested {} runs ({} rows); {} already present.".format(
        stats["runs"], stats["rows"], stats["skipped"]))
    counts = items_mod.summary_counts(conn)
    print("\n=== item store ===")
    print("  rows            {:,}".format(counts["rows"]))
    print("  distinct items  {:,}   (from {:,} raw instance names)".format(
        counts["items"], counts["instances"]))
    print("  runs / DUTs     {} / {}".format(counts["runs"], counts["duts"]))
    print("  value kinds     {}".format(counts["kinds"]))
    print("  PUBLISHED LIMITS: {}   <- OCP `validators` is empty upstream".format(
        counts["withPublishedLimits"]))

    print("\n=== item catalog (most measurable across DUTs) ===")
    print("  {:<40} {:>5} {:>6} {:>7}  {:<9} {}".format(
        "item", "DUTs", "runs", "samples", "unit", "range"))
    for row in items_mod.catalog(conn, station=args.station, limit=args.top):
        span = "—"
        if row["lo"] is not None:
            span = "{:.4g} .. {:.4g}".format(row["lo"], row["hi"])
        print("  {:<40} {:>5} {:>6} {:>7}  {:<9} {}".format(
            row["item"][:40], row["duts"], row["runs"], row["samples"],
            (row["unit"] or "")[:9], span))

    if args.show:
        _show_item(conn, items_mod, args.show, args.station)
    return 0


def _show_item(conn, items_mod, item: str, station: Optional[str]) -> None:
    """Distribution of one item, and the per-DUT view behind it."""
    print("\n=== {} ===".format(item))
    overall = items_mod.item_stats(conn, item, station)
    if not overall.get("samples"):
        print("  no numeric samples")
        return
    for population in (None, "COMPLETE", "ERROR"):
        stats = items_mod.item_stats(conn, item, station, only_status=population)
        if not stats.get("samples"):
            continue
        print("  {:<9} n={:<7} min={:<11.4g} p25={:<11.4g} median={:<11.4g} "
              "p75={:<11.4g} p99={:<11.4g} max={:<11.4g}".format(
                  stats["population"], stats["samples"], stats["min"], stats["p25"],
                  stats["median"], stats["p75"], stats["p99"], stats["max"]))

    rows = items_mod.per_dut(conn, item, station, agg="MAX")
    print("\n  worst value per DUT (two-level aggregation: worst instance, then across units)")
    print("    {:<18} {:<8} {:<10} {:>7}  {}".format("DUT", "release", "step", "lanes", "worst"))
    for row in rows[:12]:
        sigma = items_mod.margin(row["value"], overall)
        flag = "  ({:+.1f}sd)".format(sigma) if sigma is not None else ""
        print("    {:<18} {:<8} {:<10} {:>7}  {:.4g}{}".format(
            str(row["dut"])[:18], str(row["release"] or "—"),
            str(row["step_status"] or "—")[:10], row["lanes"], row["value"], flag))


def cmd_requests(args: argparse.Namespace) -> int:
    """Re-check the asks against other systems and rebuild that page."""
    from . import requests as requests_mod

    try:
        payload = collect_mod.read_runs()
    except (OSError, ValueError):
        payload = {}

    bundle = requests_mod.build_bundle(payload, probe=not args.no_probe)
    path = requests_mod.write_bundle(bundle)
    for entry in bundle["requests"]:
        status = entry["status"]
        print("  {:<10} {:<9} {:<24} {}".format(
            entry["priority"], status["state"], entry["key"], status["note"][:60]))
    print("{} asks, {} blocking automation -> {}".format(
        len(bundle["requests"]), bundle["openBlocking"], path))
    print("Checked on {} — a probe is only true where it ran.".format(bundle["builtOn"]))
    return 0


def cmd_weekly(args: argparse.Namespace) -> int:
    """The weekly tracker: every week's yield, and the rows behind it."""
    from . import build_weekly, pega_collect

    payload = pega_collect.collect(days=build_weekly.build_fpy.HISTORY_DAYS)
    if not payload["runs"]:
        print("No runs from the controllers.", file=sys.stderr)
        return 1
    bundle = build_weekly.build_bundle(payload, weeks=args.weeks)
    path = build_weekly.write_bundle(bundle)
    print("Weekly tracker ({:.0f} KB, {} weeks) -> {}".format(
        path.stat().st_size / 1024, len(bundle["weeks"]), path))
    for week in bundle["weeks"]:
        print("  {}  {} .. {}{}  {} steps, {} unit runs".format(
            week["week"], week["from"], week["to"],
            " (partial)" if week["partial"] else "",
            len(week["rows"]), len(week["units"])))
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    """Pack a week out, so a later week has something to compare against."""
    from . import weekly as weekly_mod

    try:
        written = weekly_mod.archive(label=args.label,
                                     current=args.current)
    except FileNotFoundError as exc:
        print("Nothing to archive: {}".format(exc), file=sys.stderr)
        return 1
    for path in written:
        print("  {:>7} KB  {}".format(int(path.stat().st_size / 1024) or "<1",
                                      path))
    return 0


def cmd_fpy(args: argparse.Namespace) -> int:
    """First-pass yield across every measured stage, for the week."""
    from . import build_fpy, pega_collect

    payload = pega_collect.collect(days=build_fpy.HISTORY_DAYS)
    if not payload["runs"]:
        print("No runs from the controllers.", file=sys.stderr)
        return 1
    bundle = build_fpy.build_bundle(
        payload, days=args.days or build_fpy.DEFAULT_DAYS)
    path = build_fpy.write_bundle(bundle)
    window = bundle["window"]
    print("FPY {} .. {} ({} stations) -> {}".format(
        window["from"], window["to"], len(bundle["rows"]), path))
    for row in bundle["rows"]:
        print("  {:<18}{:>5} units  FPY {:>6}  final {:>6}  retest {:>6}".format(
            row["label"], row["units"],
            "n/a" if row["fpy"] is None else "{:.1%}".format(row["fpy"]),
            "{:.1%}".format(row["finalYield"]),
            "n/a" if row["retestRatio"] is None
            else "{:.1%}".format(row["retestRatio"])))
    rolled = bundle["totals"]["rolledFpy"]
    if rolled is not None:
        print("  rolled first-pass across {} stages: {:.1%}".format(
            len(bundle["totals"]["rolledOver"]), rolled))
    return 0


def cmd_pega_stations(args: argparse.Namespace) -> int:
    """Station yield computed from pega2-pega5 rather than from EOS.

    Same metrics, same bundle, same page — the difference is that a controller
    reports one result per unit where EOS reports one per fixture, which is the
    discrepancy this page exists to make visible.
    """
    from . import build_stations, pega_collect

    payload = pega_collect.collect(days=args.days)
    if not payload["runs"]:
        print("No runs from the controllers ({}).".format(
            payload["levelErrors"] or "nothing in the window"), file=sys.stderr)
        return 1

    bundle = build_stations.build_bundle(payload, pega_collect.fetch_state(payload))
    path = build_stations.write_bundle(
        bundle, config.DASHBOARD_DATA_DIR / "pega_stations.js")
    print("Pega stations ({:.0f} KB, {} unit runs) -> {}".format(
        path.stat().st_size / 1024, payload["runCount"], path))
    for host, error in (payload["levelErrors"] or {}).items():
        print("  {} unavailable: {}".format(host, str(error)[:80]), file=sys.stderr)
    return 0


def build_l10_default_days() -> int:
    from . import build_l10
    return build_l10.DEFAULT_DAYS


def cmd_l10(args: argparse.Namespace) -> int:
    """Build the L10 daily tracker (FAT, SFT, RIN, 2U) from pega4."""
    from . import build_l10

    bundle = build_l10.build_bundle(days=args.days)
    if not bundle["tabs"]:
        print("No L10 runs from pega4 in the last {} days.".format(args.days),
              file=sys.stderr)
        return 1
    path = build_l10.write_bundle(bundle)
    print("L10 tracker ({:.0f} KB, {} days: {}) -> {}".format(
        path.stat().st_size / 1024, len(bundle["tabs"]),
        ", ".join("{} x {}".format(t["label"], len(t["rows"])) for t in bundle["tabs"]),
        path))
    return 0


def cmd_dailyexcel(args: argparse.Namespace) -> int:
    """Publish the module line's hand-kept tracker tabs as a dashboard page."""
    from . import build_dailyexcel

    # The run table is only used to decide which DUT serials can be linked into
    # the drill-down, so a repo that has not collected yet still gets the page.
    try:
        payload = collect_mod.read_runs()
    except (OSError, ValueError):
        payload = {}

    try:
        bundle = build_dailyexcel.build_bundle(payload, path=args.workbook)
    except FileNotFoundError as exc:
        print("No tracker workbook: {}".format(exc), file=sys.stderr)
        return 1

    path = build_dailyexcel.write_bundle(bundle)
    tabs = bundle["tabs"]
    print("Daily tracker ({:.0f} KB, {} tabs: {}) -> {}".format(
        path.stat().st_size / 1024, len(tabs),
        ", ".join("{} × {}".format(tab["label"], len(tab["rows"])) for tab in tabs),
        path))
    cross = bundle["crossref"]
    print("  {} of {} DUT serials resolve into the run table".format(
        cross["matched"], cross["duts"]))
    for warning in bundle["warnings"]:
        print("  WARNING {}".format(warning), file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import functools
    import socketserver

    from . import control

    if not config.DASHBOARD_BUNDLE.exists():
        print(
            "No data bundle yet — run `make demo` or `make collect build` first.",
            file=sys.stderr,
        )
        return 1

    handler = functools.partial(
        control.ControlHandler, directory=str(config.DASHBOARD_DIR)
    )
    # Threaded: an update takes minutes, and the page polls /api/update while it
    # runs. On a single-threaded server that poll would queue behind nothing at
    # all — but the browser also keeps a connection open for the static files,
    # and one slow request would stall the page.
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("127.0.0.1", args.port), handler) as httpd:
        print("Dashboard: http://127.0.0.1:{}/  (Ctrl-C to stop)".format(args.port))
        print("Update button enabled — it runs collect + build + publish.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


# ----------------------------------------------------------------------- helpers

def _step(key: str, label: str) -> None:
    """Announce a pipeline stage to whoever is driving this process.

    Silent on a normal CLI run. The control server behind the dashboard's Update
    button sets ``FACTORY_PROGRESS=1`` and parses these markers to drive its
    progress list, so the browser reports the stage the pipeline is actually in
    rather than a spinner that means nothing.
    """
    if os.environ.get("FACTORY_PROGRESS") == "1":
        print("::step {} {}".format(key, label), flush=True)


def _ingestable_runs(payload: Dict[str, Any],
                     station: Optional[str] = None) -> List[Dict[str, Any]]:
    """Runs that can be flattened to items — they need an identity to key on."""
    runs = [r for r in payload["runs"] if r.get("dutSerial") and r.get("runId")]
    if station:
        runs = [r for r in runs if r.get("stationKey") == station]
    return runs


def _window(args: argparse.Namespace) -> Dict[str, str]:
    if getattr(args, "frm", None) and getattr(args, "to", None):
        return {"from": args.frm, "to": args.to}
    return collect_mod.default_window(days=getattr(args, "days", 1) or 1)


def _print_keys(entries: List[Dict[str, Any]]) -> None:
    keys: Dict[str, int] = {}
    for entry in entries:
        if isinstance(entry, dict):
            for key in entry:
                keys[key] = keys.get(key, 0) + 1
    for key, count in sorted(keys.items(), key=lambda kv: -kv[1]):
        print("  {:<28} present in {}/{}".format(key, count, len(entries)))


def _flag_unresolved(record: Dict[str, Any]) -> None:
    missing = [
        field
        for field in ("dutSerial", "startTs", "station", "suite", "status")
        if record.get(field) in (None, "unknown")
    ]
    if missing:
        print(
            "\n!! unresolved fields: {}\n   Add the real key names to the "
            "*_ALIASES tables in src/factory/parse.py.".format(", ".join(missing)),
            file=sys.stderr,
        )


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else "{:.1f}%".format(value * 100)


def _num(value: Optional[float], places: int = 1) -> str:
    return "—" if value is None else "{:.{}f}".format(value, places)


def _dur(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    if seconds < 90:
        return "{:.0f}s".format(seconds)
    return "{:.0f}m{:02.0f}s".format(seconds // 60, seconds % 60)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="factory", description="EOS test-log ETL and hourly manufacturing metrics"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_window(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--level", default=config.default_level())
        sub.add_argument("--from", dest="frm", help="YYYY-MM-DD or ISO-8601 (inclusive)")
        sub.add_argument("--to", dest="to", help="YYYY-MM-DD or ISO-8601 (inclusive)")
        sub.add_argument("--days", type=int, default=1,
                         help="window size when --from/--to are omitted")
        sub.add_argument("--no-cache", action="store_true",
                         help="bypass the on-disk HTTP cache")

    trust_cmd = subparsers.add_parser(
        "trust", help="fetch and verify Etched's internal CA bundle (fixes TLS errors)"
    )
    trust_cmd.add_argument(
        "--fingerprint",
        help="expected SHA-256 of a known certificate in the bundle; required "
             "when the corporate root is not in this machine's keychain",
    )
    trust_cmd.set_defaults(handler=cmd_trust)

    levels = subparsers.add_parser("levels", help="list allowed test levels")
    levels.add_argument("--no-cache", action="store_true")
    levels.set_defaults(handler=cmd_levels)

    runs = subparsers.add_parser("runs", help="list run descriptors (raw)")
    add_window(runs)
    runs.add_argument("--limit", type=int, default=5)
    runs.set_defaults(handler=cmd_runs)

    inspect = subparsers.add_parser(
        "inspect", help="show live field names and how parse.py resolves them"
    )
    add_window(inspect)
    inspect.set_defaults(handler=cmd_inspect)

    collect = subparsers.add_parser("collect", help="fetch runs + suite summaries")
    add_window(collect)
    collect.add_argument("--levels", nargs="*", help="collect several levels at once")
    collect.add_argument("--workers", type=int, default=8)
    collect.add_argument("--no-summaries", action="store_true",
                         help="skip artifact fetches (run metadata only)")
    collect.set_defaults(handler=cmd_collect)

    demo = subparsers.add_parser("demo", help="generate synthetic data and build")
    demo.add_argument("--days", type=int, default=2)
    demo.add_argument("--level", default=config.default_level())
    demo.add_argument("--seed", type=int, default=7)
    demo.set_defaults(handler=cmd_demo)

    build = subparsers.add_parser("build", help="compile runs.json into the dashboard bundles")
    build.set_defaults(handler=cmd_build)

    refresh = subparsers.add_parser(
        "refresh", help="one scheduler tick: collect + record fetch state + rebuild"
    )
    refresh.add_argument("--days", type=int, default=30,
                         help="window to collect (default 30, so release trends stay whole)")
    refresh.add_argument("--levels", nargs="*", help="override the levels to collect")
    refresh.add_argument("--workers", type=int, default=8)
    refresh.add_argument("--with-items", action="store_true",
                         help="also ingest new runs into the item store, so the "
                              "releases page moves with the rest")
    refresh.set_defaults(handler=cmd_refresh)

    status = subparsers.add_parser("status", help="show last fetch / last update")
    status.set_defaults(handler=cmd_status)

    items = subparsers.add_parser(
        "items", help="flatten test cases to test items (numeric) into SQLite"
    )
    items.add_argument("--station", help="restrict to one station key, e.g. l10_sft")
    items.add_argument("--limit", type=int, default=0,
                       help="only the N most recent runs (0 = all)")
    items.add_argument("--rebuild", action="store_true",
                       help="re-ingest runs already in the store")
    items.add_argument("--top", type=int, default=25, help="catalog rows to print")
    items.add_argument("--show", help="print the distribution of one item template")
    items.set_defaults(handler=cmd_items)

    report = subparsers.add_parser("report", help="print the hourly metrics as text")
    report.add_argument("--limit", type=int, default=12)
    report.set_defaults(handler=cmd_report)

    requests_cmd = subparsers.add_parser(
        "requests", help="re-check what we need from other systems"
    )
    requests_cmd.add_argument("--no-probe", action="store_true",
                              help="list the asks without checking them")
    requests_cmd.set_defaults(handler=cmd_requests)

    pega_stations = subparsers.add_parser(
        "pega-stations",
        help="build the station page straight from the ESVM controllers")
    pega_stations.add_argument("--days", type=int, default=30)
    pega_stations.set_defaults(handler=cmd_pega_stations)

    weekly = subparsers.add_parser(
        "weekly", help="the weekly tracker: every week's yield and its rows")
    weekly.add_argument("--weeks", type=int, default=12)
    weekly.set_defaults(handler=cmd_weekly)

    archive = subparsers.add_parser(
        "archive", help="pack a week out under weekly/ for later comparison")
    archive.add_argument("--label", default=None,
                         help="ISO week to archive, e.g. 2026-W33")
    archive.add_argument("--current", action="store_true",
                         help="archive the week in progress rather than the "
                              "most recent completed one")
    archive.set_defaults(handler=cmd_archive)

    fpy = subparsers.add_parser(
        "fpy", help="end-to-end first-pass yield, one row per test step")
    fpy.add_argument("--days", type=int, default=None)
    fpy.set_defaults(handler=cmd_fpy)

    l10 = subparsers.add_parser("l10", help="build the L10 daily tracker from pega4")
    l10.add_argument("--days", type=int, default=build_l10_default_days())
    l10.set_defaults(handler=cmd_l10)

    dailyexcel = subparsers.add_parser(
        "dailyexcel", help="compile the line's daily MLT/HTT tracker tabs"
    )
    dailyexcel.add_argument("--workbook", help="path to the .xlsx export "
                                               "(default: newest in daily/)")
    dailyexcel.set_defaults(handler=cmd_dailyexcel)

    serve = subparsers.add_parser("serve", help="serve the dashboard locally")
    serve.add_argument("--port", type=int, default=8787)
    serve.set_defaults(handler=cmd_serve)

    return parser


if __name__ == "__main__":
    sys.exit(main())
