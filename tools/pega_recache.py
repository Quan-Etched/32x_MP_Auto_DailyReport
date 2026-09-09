#!/usr/bin/env python3
"""Drop cached controller day-listings so the next build fetches them again.

WHY THIS EXISTS
A finished day's run list cannot change, so pega.py caches it and never asks
again. That is what keeps a build off the network — and it is also how a bad
answer becomes permanent. Two ways it happened:

* A listing fetched while its day was still running was written as though the
  day had ended. e6f4dfc marks those `.partial` now, but the entries already on
  disk carry no marker and are trusted for ever.
* A host that timed out was written off for the whole build, so every day of
  that run was served from whatever the cache already held. On the dashboard
  host, with a relayed 5-12s connect against an 8s timeout, that was every
  build for three weeks: the published weekly tracker sat at 2026-W32 while the
  collector reported success every hour.

Neither leaves a trace in the cache, so neither can be detected from it. The
fix is to throw the suspect range away and let it refill.

    python3 tools/pega_recache.py --from 2026-08-01 [--to 2026-09-03]
    python3 tools/pega_recache.py --from 2026-08-01 --dry-run

Only day-listings are dropped. Run *details* are immutable — a finished run's
verdict and test cases never change — so those stay, which is what keeps the
refill cheap: the listings come back from the network, the runs behind them
come back from disk.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from factory import pega                                    # noqa: E402

#: Every controller the collector reads. A day is dropped for all of them:
#: the whole point is that we cannot tell which host's copy is the bad one.
HOSTS = ("pega2", "pega3", "pega4", "pega5", "pega6", None)


def day_paths(day: str):
    """The listing URLs one day is cached under, across every page."""
    start = "{}T00:00:00.000Z".format(day)
    end = "{}T00:00:00.000Z".format(
        (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1))
        .strftime("%Y-%m-%d"))
    for page in range(1, pega.MAX_PAGES + 1):
        yield ("/api/history/data-analysis/suite-runs"
               "?start={start}&end={end}&page={page}&per_page={size}".format(
                   start=start, end=end, page=page, size=pega.PAGE_SIZE))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", required=True,
                    help="first day to drop, YYYY-MM-DD")
    ap.add_argument("--to", dest="end",
                    default=date.today().strftime("%Y-%m-%d"),
                    help="last day to drop (default: today)")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would go, remove nothing")
    args = ap.parse_args()

    first = datetime.strptime(args.start, "%Y-%m-%d").date()
    last = datetime.strptime(args.end, "%Y-%m-%d").date()
    if last < first:
        print("--to is before --from", file=sys.stderr)
        return 2

    dropped = days_touched = 0
    day = first
    while day <= last:
        stamp = day.strftime("%Y-%m-%d")
        hit = False
        for path in day_paths(stamp):
            for host in HOSTS:
                entry = pega._cache_path(path, host)
                marker = pega._partial_path(path, host)
                for target in (entry, marker):
                    if target.exists():
                        hit = True
                        dropped += 1
                        if not args.dry_run:
                            target.unlink()
        days_touched += 1 if hit else 0
        day += timedelta(days=1)

    verb = "would drop" if args.dry_run else "dropped"
    print("{} {} cached listing entries across {} days ({} to {})".format(
        verb, dropped, days_touched, args.start, args.end))
    print("cache dir: {}".format(pega.CACHE_DIR))
    if not args.dry_run and dropped:
        print("Run `make update` (or wait for the hourly tick) to refill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
