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
    """
    from . import fetchstate, stations

    client_levels = args.levels or stations.levels_to_collect() + stations.blocked_levels()
    window = collect_mod.default_window(days=args.days)

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
        return 2

    collect_mod.write_runs(payload)
    state = fetchstate.record_fetch(payload)

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


def cmd_build(args: argparse.Namespace) -> int:
    from . import build_stations, fetchstate

    payload = collect_mod.read_runs()
    bundle = build_dashboard.build_bundle(payload)
    path = build_dashboard.write_bundle(bundle)
    size_kb = path.stat().st_size / 1024
    print(
        "Bundled {} runs ({:.0f} KB) -> {}".format(len(bundle["runs"]), size_kb, path)
    )

    stations_bundle = build_stations.build_bundle(payload, fetchstate.load())
    stations_path = build_stations.write_bundle(stations_bundle)
    print("Stations bundle ({:.0f} KB) -> {}".format(
        stations_path.stat().st_size / 1024, stations_path))
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
    from .collect import _pick_role_path

    payload = collect_mod.read_runs()
    runs = [r for r in payload["runs"] if r.get("dutSerial") and r.get("runId")]
    if args.station:
        runs = [r for r in runs if r.get("stationKey") == args.station]
    if args.limit:
        runs = sorted(runs, key=lambda r: r.get("startTs") or 0, reverse=True)[: args.limit]

    conn = items_mod.open_db()
    client = EOSClient(use_cache=True)

    done = added = skipped = 0
    for record in runs:
        if not args.rebuild and items_mod.already_ingested(conn, record["runId"]):
            skipped += 1
            continue
        try:
            artifacts = client.artifacts(level=record["level"],
                                         dut_serial=record["dutSerial"],
                                         run_id=record["runId"])
            path = _pick_role_path(artifacts, config.ROLE_EVENT_STREAM)
            if not path:
                continue
            raw = client.artifact_content(level=record["level"],
                                         dut_serial=record["dutSerial"],
                                         run_id=record["runId"], rel_path=path)
        except EOSError as exc:
            print("  {}: {}".format(record["runId"][:44], str(exc)[:80]), file=sys.stderr)
            continue
        rows = items_mod.extract_items(raw, record)
        added += items_mod.ingest(conn, record["runId"], rows)
        done += 1
        if done % 10 == 0:
            print("  ingested {} runs, {} item rows".format(done, added), file=sys.stderr)

    print("Ingested {} runs ({} rows); {} already present.".format(done, added, skipped))
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


def cmd_serve(args: argparse.Namespace) -> int:
    import functools
    import http.server
    import socketserver

    if not config.DASHBOARD_BUNDLE.exists():
        print(
            "No data bundle yet — run `make demo` or `make collect build` first.",
            file=sys.stderr,
        )
        return 1

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(config.DASHBOARD_DIR)
    )
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print("Dashboard: http://127.0.0.1:{}/  (Ctrl-C to stop)".format(args.port))
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


# ----------------------------------------------------------------------- helpers

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

    serve = subparsers.add_parser("serve", help="serve the dashboard locally")
    serve.add_argument("--port", type=int, default=8787)
    serve.set_defaults(handler=cmd_serve)

    return parser


if __name__ == "__main__":
    sys.exit(main())
