# Test items — getting past the boolean

How to flatten the suite/case nesting down to the numeric layer, what the data
actually supports, and the one thing that blocks a definitive "why".

Everything below was measured against live EOS data on 2026-08-07, not inferred.

## The resolution problem

Today the pipeline stops here:

```
run ──> test case ──> PASSED | FAILED
```

One bit per test case. It can tell you *that* `C2cIntegrityTestCase` failed; it
cannot tell you the BER was 4e-5 against a population median of 5e-9, that only
lane 17 of chip 3 was bad, or that the unit which "passed" was 28σ from normal.

## The data is already being downloaded and discarded

The `event_stream` artifact (OCP `log.jsonl`) — fetched for every run already, to
get run timing and verdict — carries one `measurement` event per test item:

```json
{"testStepArtifact": {"testStepId": "7", "measurement": {
   "name": "ber_0_0_1", "value": 2.0269150366843607e-10, "validators": [],
   "metadata": {"device_index": 0, "phy_idx": 0, "lane_idx": 1}}}}
```

`parse_event_stream` reads the step timings out of these files and throws the
measurements away. **Extracting them costs zero additional API calls.**

Measured volume:

| Station | measurements / run |
|---|---|
| L10 SFT | **~7,500** |
| L10 RIN | ~48 |
| L10 FAT | ~14 |
| MLT, SLT, Chip Screening | **0** |

In one SFT run: 4,299 int, 1,196 float, 864 bool, 1,122 str — **74% numeric**,
with real units (`Hz`, `uC`, `degrees C`, `GB`, `RPM`, `IOPS`, `MiB/s`).

## The flattening

```
run ──> step (= the test case you already see)
          ──> item        (name template)
                ──> instance   (dims: device / phy / lane)
                      ──> value  (float | int | bool | str)
```

### Name templating is what makes it usable

A single SFT run emits **7,472 distinct measurement names** but only **1,195
distinct templated items**. `ber_0_0_1`, `ber_0_0_2` … `ber_2_7_127` are not 3,072
different items — they are one item, `ber`, measured on 3,072 lanes.

Without templating you get thousands of one-sample "items" and no distribution
exists. With it, `ber_<i>_<i>_<i>` has 55,296 samples across 9 DUTs.

`items.template_name()` replaces index runs with `<i>`; `derive_chip()` recovers
per-chip attribution from the `chipN` prefix, falling back to
`metadata.device_index` (`hardwareInfoId` is populated on ~0.1% of measurements,
so it is not usable).

### The fact table

One row per measurement, fully denormalized so any slice is one query:

```
run_id · dut · station · level · suite · release · start_ts
step · step_status          <- the bridge back to today's boolean
item · item_raw · chip · dims · unit
vtype (num|bool|str) · num · txt
limits                      <- OCP validators, see below
```

Stored in **SQLite** (`data/processed/items.sqlite`, stdlib `sqlite3`). At ~7,500
rows per SFT run and ~99 SFT runs per 30 days this is ~750k rows — two orders of
magnitude past what belongs in a browser bundle, and far past what re-parsing
JSON per query can serve. A real indexed store is the right tool and costs no new
dependency.

```sh
python -m factory.cli items --station l10_sft                     # ingest + catalog
python -m factory.cli items --show 'ber_<i>_<i>_<i>'              # one item's distribution
```

## ⚠️ Limits are not published — this is the blocker

`validators` is the OCP field where limits belong. It is **empty on every one of
the ~30,000 measurements sampled**, across every station and release.

The other candidates were checked and ruled out:

| Source | Contains | Limits? |
|---|---|---|
| `measurement.validators` | `[]` on 100% of samples | **no** |
| `measurement.metadata` | `device_index`, `phy_idx`, `lane_idx`, `pattern` | no — dimensions, useful |
| `suite_config.yaml` | test configuration; 2 limit-ish keys in 17 KB (`max_reboot_cycles`, `expected_service_timeout`) | effectively no |
| `bom_config.yaml` | expected part numbers, manufacturers, firmware versions | only for identity/version checks |
| `diagnosis.verdict` | prose: *"Memory verification failed: 32 errors found"* | sometimes a count, never a threshold |

So EOS publishes the **values** but not the **thresholds**. The pass/fail
decision is made inside the harness and only the boolean escapes.

### Consequence 1 — the upstream ask (highest leverage by far)

**Populate `validators`.** The harness already emits the field, empty. Filling it
turns every measurement self-describing forever, and makes "failed because
4.6e-5 > 1e-6 limit" a fact rather than an inference. One change upstream beats
any amount of cleverness here.

### Consequence 2 — until then, limits are empirical

Describe the *passing* population for the same `(item, station, release)`, then
judge a suspect value against it:

```
ber_<i>_<i>_<i>   n=55,296   median 4.7e-9   p75 8.7e-8   p99 7.7e-6   max 5.3e-5
```

`items.margin()` returns the distance in σ. This is a **relative** statement —
"28σ outside the passing population" — and must never be rendered as "out of
spec", because the spec is not published. It is also exactly how process
capability works, so it is not a workaround so much as the other half of the job.

### Consequence 3 — prose is extracted, never trusted

Failure verdicts sometimes state a number (*"32 errors found"*, *"0/8 chips
passed"*). Worth extracting into a clearly-labelled field; never ground truth.

## What this immediately exposes

Real result, `ber` across 9 DUTs and 93 SFT runs — **every one of these runs
passed its boolean test case**:

| DUT | release | worst-lane BER | vs population |
|---|---|---|---|
| 267693950002 | 198 | 5.3e-5 | +28.3σ |
| 267694410002 | 207 | 4.8e-5 | +25.3σ |
| 267694410001 | 207 | 4.6e-5 | +24.5σ |
| … | | | |
| 267342870004 | 190 | 1.6e-6 | +0.6σ |

The boolean says PASS for all of them, yet the worst lane on one unit is ~30,000×
worse than another. Those are the marginal units that pass here and fail at the
customer, or fail on the next retest. **This is the resolution the boolean was
hiding**, and it is available today with no upstream change.

## Two aggregation levels (easy to get wrong)

A per-lane item has thousands of values per unit. A cross-DUT distribution needs
**two** reductions:

1. **Within the unit** — worst lane (`MAX`), or count over threshold. This is the
   unit's score.
2. **Across units** — the distribution of those scores.

Skipping step 1 plots *lanes*, not units: 55,296 points that say nothing about
which board is bad. `items.per_dut()` does both.

## Retest, at item level

This is where the deep dive pays off. For a unit that failed then passed on
retest, plot the **same item across its attempts**:

- value barely moved, verdict flipped → **marginal unit or a flaky limit**; the
  retest is masking, not fixing.
- value moved materially → a real repair.

That directly answers the question the station-level retest view can only raise:
L10 FAT currently shows 9 of 10 units retested and 38% recovery, and today there
is no way to tell which kind of recovery that is.

## Not covered

- **MLT, SLT and Chip Screening emit no measurements** (5 runs sampled each).
  Their numeric data, if it exists, is inside `subtest_log` text files. The
  deep dive is L10-only until that is confirmed with the harness team.
- **`telemetry` artifacts are Parquet** — `chip0_dts_sensor`,
  `chip0_hbm_telemetry`, `chip0_ethernet_lane_telemetry`, `bmc_sdr_lightweight`,
  one file per step per sensor: **427 files, 39 MB in a single run**. This is the
  richest tier (time-series, in-test), and it is unreachable from a stdlib-only
  pipeline — Parquet needs `pyarrow`. At ~39 MB/run it also must never enter the
  hourly loop. Treat as an opt-in, per-investigation tool.
- Published limits, per above.
