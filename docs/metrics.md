# Metric definitions

These are the numbers the dashboard shows. The reference implementation is
`src/factory/hourly.py`, pinned by `tests/test_hourly.py`; `dashboard/app.js`
mirrors it so the browser can re-aggregate when you change a filter. **Change a
definition in all three places.**

## The bucket

An hour bucket is a **local** hour in the factory timezone (`FACTORY_TZ`,
default `America/Los_Angeles`), labelled `YYYY-MM-DDTHH`. Timestamps are stored
as UTC epoch seconds and bucketed at read time, so "the 09:00 hour" means what
the floor means by it, and DST is handled by the zone database.

A run is counted in **the hour it started**, not the hour it finished. Throughput
therefore reads as "units the line put into test during that hour".

A run with no resolvable start time cannot be placed on a timeline. Those runs
are **excluded from every hourly metric and counted separately** — `summary()`
reports `runsWithoutTimestamp` and the dashboard footer shows it. They are never
silently bucketed into "now".

## Where each field actually comes from

`/runs` carries only `runId`, `level`, `dutSerial`, `suite`, `version`,
`startedAt`, `prefix`. Everything else is reconstructed:

| Field | Source |
|---|---|
| start time | `/runs.startedAt` (what the query window filters on) |
| end time, duration | `event_stream` (`log.jsonl`) — `testRunEnd` − `testRunStart` |
| run status | `event_stream` `testRunEnd.status` + `.result`; else derived from the tests |
| test list + status | `suite_summary` (`test_summary.json`) |
| per-test duration | `event_stream` step start/end pairs |

**Cycle time depends entirely on the event stream.** Collect with
`--no-summaries` and duration is `None` everywhere, so the cycle-time chart goes
empty while throughput still looks fine.

## Run status

Statuses normalize to `pass` / `fail` / `error` / `skip` / `unknown`.

- `error` (abort, crash, timeout) is kept **distinct from** `fail`, because an
  infrastructure abort is not a unit defect — but it counts against yield, and
  the outcome chart shows it as its own segment.
- `skip` and `unknown` are **excluded from rate denominators** rather than
  assumed to be passes. An hour with no verdicts reports `—`, not `0%`.
- When the API supplies a run status it wins. Only when it does not is the status
  derived from the tests: any failing test fails the run.

## Rates

| Metric | Definition |
|---|---|
| **Runs** | count of runs started in the hour |
| **Units** | count of **distinct** `dutSerial` values started in the hour — three retries of one board is one unit |
| **Units/hour** (hero) | distinct units ÷ **active hours** |
| **Runs/hour** | runs ÷ active hours |

**Active hours** = hours that contain at least one run. Dividing by elapsed hours
instead would drag every rate down across a night shift the line was not running;
dividing by active hours answers "how fast does it go when it is going".

Note the consequence: an hour with a single run counts as a whole active hour. On
very sparse data the rate reads low.

## Yield

| Metric | Numerator | Denominator |
|---|---|---|
| **Pass rate** | runs with status `pass` | runs with a verdict (`pass`+`fail`+`error`) |
| **First-pass yield (FPY)** | first-attempt runs that passed | first-attempt runs |

`attempt` is assigned in `collect._mark_attempts`: each DUT's runs at a level are
numbered in time order, so `attempt == 1` is that unit's first pass through the
level.

⚠️ **FPY is window-relative.** Attempts are numbered *within the collected
window*. If a board first ran on Monday and you collect only Tuesday, Tuesday's
run is numbered attempt 1 and counts as a first pass. Widen the window and the
same run becomes attempt 2. For a trustworthy FPY, collect a window at least as
long as a unit's full retry cycle.

## Cycle time

Per-run wall-clock duration in seconds, taken from the API's duration field, else
`end − start`, else the sum of the run's test durations.

Reported as **median (p50)** and **p90** per hour, linearly interpolated. Medians,
not means: a single 3-hour hung run should not move the number the line reads.

## Failure Pareto

Failing tests ranked by **run occurrences**: a test that fails in three runs
scores three. `share` is that test's fraction of all failure occurrences in the
selection; `cumulativeShare` accumulates down the ranking. `duts` is the count of
distinct units affected — the column that separates "one bad board" from "a real
process problem".

The Pareto is computed over the **whole selection**, not per hour, because an
hourly Pareto on a 10-run hour is noise.

There is deliberately **no cumulative-percentage line** on the chart. A classic
Pareto puts counts and cumulative % on two y-scales; a dual-axis plot invents
relationships that are not in the data, so the cumulative figure lives in the
tooltip and the table instead.

## Grouping dimension (station is unavailable)

**EOS exposes no station or fixture field** — not on `/runs` at any level, not in
the event stream (`dutInfo.platformInfos` is empty), and `resource_config`
describes the DUT's own addresses rather than the rig it sat in.

The volume chart and its detail table therefore group by a **selectable
dimension** — suite, version, or level — and the group-by control offers only
dimensions that actually split the data. Station appears automatically if EOS
ever adds it. Version grouping is the useful one for manufacturing: it shows a
build rolling across the line.

Group rows are per-value totals across the selection: runs, distinct units, pass
rate, median cycle time.

The DUT table lists units with **more than one failing run** in the selection —
the repeat offenders — ranked by failure count, showing their last result and
every station they touched. A unit failing across several stations points at the
unit; a unit failing only on one points at the station.

## What is not measured

- **Anything per station.** No station identity exists in the API (above).
- **Station utilization / idle time.** Would need station state, which the API
  does not expose; occupancy cannot be distinguished from "no work queued".
- **Rework and scrap outcomes.** Not present in test logs.
- **Test-level durations per hour.** Collected from the event stream per run, but
  not currently rolled up into an hourly view.
