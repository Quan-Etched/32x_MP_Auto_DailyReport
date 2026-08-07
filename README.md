# factory_data_analysis

Hourly manufacturing metrics from the EOS test-log API, as a static dashboard.

Pulls test runs from `eos.core.etched.com`, normalizes them into a flat run
table, and renders throughput, yield, cycle time, failure Pareto and
station/DUT breakdowns — **bucketed by factory-local hour**.

Python 3.9+ standard library only. No pip install, no npm, no build step.

![pipeline](https://img.shields.io/badge/deps-stdlib%20only-informational)

## Quick start

No API key needed to see it working:

```sh
make demo          # generate synthetic runs + build the dashboard bundle
make serve         # http://127.0.0.1:8787/
```

Against real data:

```sh
cp .env.example .env       # then put your key in EOS_API_KEY
make inspect               # confirm the live API field names map correctly (do this once)
make collect DAYS=2        # fetch runs + suite summaries
make build                 # compile them into the dashboard bundle
make serve
```

`make report` prints the same metrics as text if you just want numbers.

## What the dashboard shows

| | |
|---|---|
| **Hero** | units started per active hour |
| **Tiles** | first-pass yield, pass rate, cycle time p50, runs, failed runs — each with a delta vs the previous equal-length period and a 12-hour sparkline |
| **Runs per hour by outcome** | stacked columns, pass / error / fail |
| **Yield by hour** | first-pass yield and pass rate |
| **Cycle time by hour** | median and p90 run duration |
| **Runs per hour by station** | stacked columns, stable per-station colors |
| **Failure Pareto** | failing tests ranked by run occurrences, with share, cumulative share, distinct DUTs and the most common error code |
| **Station detail / repeat-failure DUTs** | tables |

Filters (time range, level, station, suite) sit in one row and scope everything
below them. Every chart has a table view. Light and dark themes are both
designed, not inverted.

Definitions — including the ones with caveats — are in
[`docs/metrics.md`](docs/metrics.md).

## Layout

```
src/factory/
  config.py           paths, env, factory timezone
  eos_client.py       the 4 endpoints + retry, timeout, on-disk response cache
  parse.py            field-alias tables; normalizes runs and suite_summary.json
  collect.py          /runs → /artifacts → /artifact-content, threaded
  hourly.py           metric definitions (reference implementation)
  build_dashboard.py  compiles the run table into the browser bundle
  demo_data.py        synthetic runs, clearly labelled as such
  cli.py              levels | runs | inspect | collect | demo | build | report | serve

dashboard/
  index.html          structure
  styles.css          palette + chrome (light/dark as role tokens)
  app.js              filtering, aggregation, SVG charts, tooltips, tables
  data/metrics.js     generated bundle (gitignored)

data/raw/             cached HTTP responses (gitignored)
data/processed/       normalized runs.json (gitignored)
docs/                 api-usage.md · metrics.md · dataviz-notes.md
tests/                40 unit tests over parsing and metrics
```

## Before you trust a number

The API doc pins the four endpoints but **elides the field names inside run
objects and never specifies the schema of `suite_summary.json`**. Rather than
guess one spelling, `parse.py` resolves every field through alias tables, matches
keys case- and punctuation-insensitively, and yields `None` instead of raising.

So the first run against live data is a verification step:

```sh
make inspect
```

It prints the field names actually returned, shows how they were resolved, and
flags anything it could not map. Add missing spellings to the `*_ALIASES` tables
in `src/factory/parse.py` — that is the only place they need to change.

Two things it is built to catch:

- **No start-time field.** The collector falls back to the `_20260803_094406`
  stamp in the run ID, read as UTC. If that stamp is local wall-clock, hourly
  buckets shift by the UTC offset. A warning is logged and the count appears in
  the dashboard footer.
- **Zero tests parsed** from `suite_summary.json` — yield and Pareto go empty
  while throughput still looks healthy.

## Security

`EOS_API_KEY` is read from the environment (or a gitignored `.env`) by the Python
ETL only. It is never written to disk, never embedded in the dashboard bundle,
and the browser never talks to the EOS API. `data/` and the generated bundle are
gitignored, so factory data is not committed.

## Tests

```sh
make test
```

40 tests covering status normalization, timestamp and duration coercion, all
three plausible `suite_summary.json` shapes, and every metric definition.
