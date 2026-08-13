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

## Station views (`dashboard/stations.html`)

A **station** is a test stage on the line — MLT, L10 FAT, SFT, RIN, SLT, chip
screening — identified by an EOS `level` plus a `suite` match. The registry is
`src/factory/stations.py`; it lists every station the line runs, including ones
with no data, so the page can say *why* a station is empty. Debug suites
(`L10_6U_FAT_krish`) are deliberately excluded from production yield.

**Release** is the middle component of the version string:
`2026.207.0-git…` → `207`.

### Drilling into a number (`dashboard/runs.html`)

Every count on the station page links to the runs behind it. The link carries a
filter in the URL hash, and those filters are defined here, not re-invented:

| Filter | Means |
| --- | --- |
| `status=abort` | `status == "error"` — the line says abort, EOS says error |
| `status=graded` | the pass / fail / error triple; never `skip` or `unknown` |
| `attempt=first` | `attempt == 1`, the FPY population |
| `day=` | the factory-local calendar day, same bucket as the day chart |
| `release=` | the release number, same derivation as the release chart |

So the FPY tile links to `attempt=first&status=graded` — its own denominator —
and the row count on the run table equals the number that was clicked. If those
two ever disagree one of them is wrong; `tests/test_build_runs.py` pins the
populations against `daily.py`.

The **First fail** column reports the first failing *leaf* test, skipping
container entries (`rootcause.is_container`) for the same reason the Pareto
does: a nest fails whenever anything under it fails, so `chip1` is true but
useless where `chip1_sa_sort_rampup_hbm` is the signature.

### (a) Yield vs daily

One row per local calendar day that has runs. Stacked pass / fail / **abort**
(`error` is called abort here, matching the line's vocabulary), plus FPY.
Zero-run days are omitted rather than drawn as a gap — a day the line did not
run has no yield.

### (b) Yield vs release

Same measures grouped by release instead of day, each labelled with the **date
range** that release was on the line. Without the range you cannot tell a bad
release from a bad week. One release can carry several build hashes; all are
kept in the row.

### Thin samples

Any rate over fewer than **5 graded first attempts** is marked thin and drawn
with a hollow marker. `1/1 = 100%` is a coin toss, not a yield, and must not
read the same as `40/40`.

### (c) Top yield hits

Failure Pareto bucketed by root-cause area, with a cumulative-% line and the 80%
rule. Two counting modes:

- **All failures** — every failing test occurrence; a run failing three areas
  hits three.
- **First failure only** — one area per failing run, the failure that stopped
  the unit.

Two corrections were needed to make this meaningful on EOS data, taking the
unclassified bucket from **71% to 10%**:

1. Rules were written against CamelCase class names, so matching also runs
   against a separator-stripped copy (`update_bmc_bios` → `updatebmcbios`).
2. **Nested containers are excluded.** EOS emits an entry per parent node
   (`SltModuleNestedTestCase`, `ServerNestedTestCase`) beside the real leaf
   tests. A container "fails" only because a child did, so counting both
   double-counts every failure. `parent_id` is null on every entry observed, so
   the class-name suffix is the only available marker.

This is the one place the dashboard uses a second y-axis. A Pareto's cumulative
line is derived from the same counts as the bars and is anchored (100% = the
total), so it cannot imply a relationship that is not in the data.

### (d) Retest

A retest is **the same DUT serial run more than once at the same station**
within the collected window. Two distinct questions:

| Metric | Question |
|---|---|
| **Retest rate** | of units that entered, how many went round again? (flow / capacity) |
| **Recovery rate** | of units that failed first time and were retried, how many ended up passing? (was the failure real) |

A high recovery rate means the station is failing good units. `Still failing`
counts units whose last attempt was not a pass. The depth histogram buckets
units by attempt count, capped at `5+`.

Window-relative, exactly like FPY: a unit first tested before the window looks
like a first attempt.

## What is not measured

- **Anything per station.** No station identity exists in the API (above).
- **Station utilization / idle time.** Would need station state, which the API
  does not expose; occupancy cannot be distinguished from "no work queued".
- **Rework and scrap outcomes.** Not present in test logs.
- **Test-level durations per hour.** Collected from the event stream per run, but
  not currently rolled up into an hourly view.
