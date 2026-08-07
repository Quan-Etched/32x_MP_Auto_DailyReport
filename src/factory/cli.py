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


def cmd_build(args: argparse.Namespace) -> int:
    payload = collect_mod.read_runs()
    bundle = build_dashboard.build_bundle(payload)
    path = build_dashboard.write_bundle(bundle)
    size_kb = path.stat().st_size / 1024
    print(
        "Bundled {} runs ({:.0f} KB) -> {}".format(len(bundle["runs"]), size_kb, path)
    )
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

    build = subparsers.add_parser("build", help="compile runs.json into the dashboard bundle")
    build.set_defaults(handler=cmd_build)

    report = subparsers.add_parser("report", help="print the hourly metrics as text")
    report.add_argument("--limit", type=int, default=12)
    report.set_defaults(handler=cmd_report)

    serve = subparsers.add_parser("serve", help="serve the dashboard locally")
    serve.add_argument("--port", type=int, default=8787)
    serve.set_defaults(handler=cmd_serve)

    return parser


if __name__ == "__main__":
    sys.exit(main())
