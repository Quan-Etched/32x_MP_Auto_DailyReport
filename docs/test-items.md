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

---

# The release view and the compatibility format

`dashboard/releases.html` — every base-level test item a release measures, in
both a table and a graph layer, plus a diff against the previous release.

## Item identity is the whole trick

A diff is only possible if an item has an identity that survives across
releases. That identity is **`(station, templated item name)`**. Everything else
follows from set arithmetic on it.

This is also why the templating rules matter so much in practice. PCI addresses
(`0000:1a:00.0`) originally survived templating as `<i>:1a:<i>.<i>` — the hex
segments are not decimal — so **every distinct bus address became its own item**,
inflating the catalogue and manufacturing phantom add/remove churn between
releases, because different systems enumerate devices at different addresses.
Address-shaped tokens (BDF, MAC, UUID) now collapse as a whole, before the
generic index rule. That one fix removed ~70 phantom items and cut the
`198 → 201` "removed" count from 215 to 143.

## The per-release signature

For each `(release, item)`:

| field | why it is in the diff |
|---|---|
| `vtype` (num/bool/str) | a type change breaks trending outright |
| `unit` | a unit change silently redefines every axis and threshold |
| `instances` | how many distinct measurement names — the coverage |
| `chips` | which chips it was measured on |
| `steps` | which test case reports it |
| `samples`, `duts`, `runsPresent` | weight of evidence |
| `prevalence` | fraction of the release's runs the item appeared in |
| `stats` (numeric only) | min, p25, median, p75, p99, max, sd |

## Seven change kinds, ordered by consequence

The order **is** the severity ranking used for sorting and colour:

| kind | meaning |
|---|---|
| `removed` | no longer measured; any trend on it stops here |
| `type-changed` | value type changed; breaks trending and distributions |
| `unit-changed` | unit changed; every axis and threshold now means something else |
| `added` | first measured in this release; no history to compare |
| `coverage-changed` | same item, different instance or chip count |
| `step-moved` | now reported under a different test case |
| `distribution-shift` | same item and unit, values moved |

A single item can carry several kinds at once, and each kind is its own
expandable group in the drawer, with a plain-language explanation of why it
matters.

## Distribution shift needs two measures, not one

Neither survives real data alone:

- **standardized** — median move in the previous release's σ, flagged at ≥ 3σ.
  Useless when `sd == 0`.
- **fold change** — flagged at ≥ ×3 or ≤ ÷3. Useless when the median is near
  zero, which is exactly where BER lives.

Both are computed and either can flag; both are shown. A comparison needs ≥ 30
samples on each side, otherwise it reports *insufficient samples* rather than a
verdict. This is how `Fio Read Bandwidth` was caught going from a median of
**2824 → 0.0** between releases — a collapse σ could not see.

## ⚠️ Absence of evidence is not evidence of absence

The single biggest trap. Release 203 has **one run**; release 190 has 31. A naive
diff reports ~200 removals when a single run simply did not exercise them.

Two defences, both visible in the UI:

1. **Confidence** — a release under 3 runs makes the whole comparison `low`, the
   column is drawn at reduced opacity and labelled *low conf*, the release row
   is badged *thin*, and the drawer prints the reason with the actual run counts.
2. **Prevalence** — an item present in under half of a release's runs is marked
   *unconfirmed* individually, even inside a confident release.

Nothing is hidden — a weak removal is still listed, but it can never be mistaken
for a confirmed one.

## Payload shape (why the page is fast)

~700 items × 21 release/station pairs inlined would be a 1.5 MB landing page.
Instead:

- **index** (`data/releases.js`, ~185 KB) — release table, diffs, and per-item
  numeric trends. Item and step names are **interned** into arrays and referenced
  by index; at ~40 characters each, repeating them per release dominated the
  payload. Diffs carry the *delta* only, not two full snapshots.
- **detail** (`data/releases/<station>-<release>.json`, ~57 KB each) — the full
  item signature list, fetched when a release is opened. Stale files are cleared
  on every build so a vanished release cannot be served as current.

The lazy fetch needs HTTP; opening the page straight off disk shows an explicit
message pointing at `make serve` rather than failing silently.

## The two formats, and what each is for

**Graph layer (index):** *What changed per release* — stacked added/edited/removed
with the total above each column, and *Coverage per release* — distinct items with
the run count under each tick. Three series, not seven: seven kinds stacked would
be unreadable, so the kind breakdown lives in the drawer where there is room.
Clicking either chart opens the release.

**Table layer (index):** the release list — dates, runs, DUTs, items, instances,
added/edited/removed, confidence. A row opens the drawer.

**Drawer (per release):** summary chips, change groups by kind (each expandable,
each item expandable to before → after), build hashes behind the release number,
and the full item catalogue — filterable by text, by value type, and by
"changed only" — where each item expands to its full statistics **and its median
across releases with a p25–p75 band**. That per-item graph is log-scaled when the
data is strictly positive and spans more than two decades, because a BER series
on a linear axis is a flat line on zero.

There is deliberately **no spec or limit column** anywhere: EOS does not publish
limits (see above), and an empty column implying otherwise would be worse than
no column.
