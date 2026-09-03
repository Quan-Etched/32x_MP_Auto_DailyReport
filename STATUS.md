# Project status

**As of 2026-08-13 (updated).** Snapshot of what works, what was verified against the live
API, and what is still open. Metric definitions live in `docs/metrics.md`; the
verified API schema in `docs/api-usage.md`.

## Published

**https://32x-production.i.etched.com** — nginx serving `/var/www/32x-production`
on `chuck-dashboard.usw2.i.etched.com` (t3.medium, AlmaLinux 9), inside the
corporate network. The same host collects hourly at :05 under a systemd user
timer with linger enabled, so it publishes whether or not anyone is logged in.
Moved there 2026-08-13; the procedure is in `docs/deploy.md`.

**The hourly job does not update the code — `make deploy` does.** The timer
collects, builds and publishes whatever tree is already on the box. A fix
committed on a laptop is not on the site until somebody deploys it, and until
2026-09-03 nothing said when that had not happened: the box served `75579de`
for eight commits while three separate fixes were written, committed and
reported as done. `make deploy-status` compares the box's checkout to yours and
exits non-zero when they differ; the build stamp in each page's masthead is the
same fact, visible from a browser.

Verified end to end from the box: 1260 runs collected, all four pages and all
four data bundles served with the right sizes and MIME types, full chain in
2m07s.

Two caveats, both real:

- **No login.** Anyone on the office network or VPN can read it, and it carries
  DUT serials, failure signatures and yield. The Pages copy it replaced required
  an authenticated Etched org member, so this is a genuine loosening. Not
  routable from outside is the whole of its protection.
- **Its TLS certificate does not verify** in any browser — see *To escalate*.

**https://cuddly-enigma-pz3pz29.pages.github.io/** — the previous home, still
private (`public: false`) and still reachable, now **frozen at its last
publish**: the laptop launchd agent that fed it was uninstalled at the cutover.
A `make update` from a laptop still refreshes it. Retire it once the internal
host is blessed.

## State: working end to end on live data

The full path — fetch → normalize → hourly metrics → dashboard — runs against
production EOS. Nothing is stubbed.

```sh
make trust             # one-time: internal CA
make update            # THE full update: collect + items + rebuild + publish
make serve             # http://127.0.0.1:8787/ — same thing on an Update button
make schedule-install  # hourly at :05 — systemd timer on the host, launchd on a Mac
make status            # last fetch vs last update, per station
```

`make update`, the Update button and the hourly agent all exec
`tools/hourly_refresh.sh`. One update path, one lock, no drift.

| Check | Result |
|---|---|
| Unit tests | 335 passing (`make test`) |
| `/levels` | `l6, l10, l11, slt, module, bringup` |
| Live collect | 1062 runs over 30 days across l6 + l10 + slt + module |
| Status / duration resolved | all runs |
| Stations mapped | 9 of 11 producing data; L11 ×2 blocked (IAM) |
| Unclassified runs | **0** (was 328) |
| Pareto coverage | "Other" 10.2% (was 71% before the container + separator fixes) |
| Dashboards | both render on real data, light + dark, headless-Chrome verified |

Station counts over the 30 days to 2026-08-13: SLT 300 · MLT 196 · HTT 132 ·
Chip Screening 129 · L10 FAT 77 · L10 SFT 59 · L10 2U 14 · L10 RIN 3 ·
unclassified 332. 910 classified runs of 1242.

Around release 220 (2026-08-10) the L10 suites dropped the `6U_` infix
(`L10_6U_FAT` -> `L10_FAT`). The registry matched only the old spelling, so
every run under the new name fell to unclassified and L10 RIN — whose old-name
runs had by then aged out of the window — read as a flat zero while the line was
still running it. The patterns now accept both spellings.

**HTT was never absent, only unnamed.** It runs under the suite
`rdqs_sweep_training` — 132 runs, module level — and nothing in that string says
HTT. The station was recorded as unmapped on the strength of a search for the
literal token, which is evidence about a string and not about a station. The
mapping is visible only in the FAMILY column of the OCP Logs UI; EOS's `/runs`
returns seven fields and family is not one of them. A `htt_`-prefixed rename is
already being trialled (an `htt_rdqs_sweep_training` run on DUT `RENAME_TEST_0`,
2026-08-12), so the pattern accepts both spellings up front.

**A station can span levels.** From 2026-08-11 the `mlt` suite also began
arriving under the `slt` level, on 22-character `JE…` serials rather than
15-digit unit serials; 32 real MLT runs sat in the unclassified bucket because
the registry entry matched `module` alone. MLT now lists both levels. The level
is where the log landed, not what was tested — all 135 test-case names in those
runs are part of the module-level MLT vocabulary.

## The line's daily tracker (v0.2)

`dashboard/dailyexcel.html` publishes the module line's own MLT/HTT sheet —
exported to `daily/*.xlsx`, read by a stdlib .xlsx reader (`src/factory/xlsx.py`,
no openpyxl), reproduced tab for tab with the sheet's own colours and column
widths. Tabs are discovered by name (`08-11 87x`, `08-12  51x`), so new days
publish themselves.

It is the only page not derived from the API, deliberately: which unit passed
MLT, which test case failed and which Jira ticket tracks it are judgements a
person made, and no endpoint carries them.

**The coverage gap it surfaced is now explained.** Reconciling the two tabs
against EOS found three causes and no bug in either system:

- **The day boundary.** The sheet buckets by **UTC**; this dashboard buckets by
  factory-local time. DUT `268494130000018` runs at 17:30 PT on 08-11, its
  runId is stamped `20260812_003002`, and the line files it under 08-12.
  Comparing like for like lifted the MLT overlap from 4 of 13 to **10 of 13**.
- **The unit of record.** A pega3 suite run drives **eight slots at once** —
  the sheet's 87 rows for 08-11 came from 11 suite runs — while EOS records one
  run per fixture carrying one `dutSerial` and no slot number. EOS therefore
  sees roughly **one unit in eight**, which is the whole of the "138 units vs
  45 runs" gap.
- **The verdict.** Run status is the fixture's, not the unit's. See *Run yield
  vs unit yield* in `docs/metrics.md`.

Every sheet-vs-EOS disagreement ran one way — sheet `Passed`, EOS `fail`, never
the reverse — which is the signature of the third cause and of nothing else.

**Still open: the HTT version does not match.** The sheet and its pega3 links
record HTT as `htt_2026.217.0-git3940b759` on those days, while EOS records
`htt_2026.216.0-git1b767d1a` and has **no 2026.217 run anywhere** in the 30-day
window. MLT agrees exactly (`2026.220.0-git2f1c2f23`), so this is HTT-specific
and needs the HTT owner, not a code change.

**Derived tabs.** A day EOS has that the workbook does not is rebuilt in the
sheet's shape, one row per chip, labelled *Rebuilt from EOS — not the line's
sheet*. Only days after the newest real tab: a day the sheet skipped is the
line's decision; a day it has not reached yet is a gap. The DUT column says
`chip 3` because the serials genuinely are not in the API — `bom_config` is a
static BOM with every `serial_number` null, `suite_config` has none, and
`resource_config` is never fetched because it holds credentials.

## Every run is now classified

The station page had 328 unclassified runs — a quarter of everything collected.
It has none. The answer came from the ESVM controllers rather than from
guessing:

| host | drives | EOS level |
|---|---|---|
| `pega2` | VBB provisioning (`pt2_l6_vbb1`) | `l6` |
| `pega3` | MLT, HTT, chip screening, SLT (`pt2_module_station1-5`) | `module`, `slt` |
| `pega4` | L10 FAT / SFT / RIN / 2U (`pt2_l10_station6-7`) | `l10` |
| `pega5` | L11 provisioning and test (`pt2_l11_station1-2`) | `l11` |
| `pega6` | baking (`pt2_baking_station1-2`) | absent from EOS |

**VBB Provisioning — 289 runs, the largest single group EOS returns.** It sat
unclassified because nothing in `VbbCec173xProvisioningInternal` says which
station runs them, and the standing note asked for the OCP FAMILY column to
settle it. pega2 settles it instead: a dedicated station, a dedicated part
number (`PN-VBB`) and production-prefixed suites (`PROD_01_vbb_provisioning`).
Counting it as unclassified was hiding the busiest stage on the line. 74.7% pass
rate over 83 units.

**Engineering — 39 runs**, in a bucket of its own rather than mixed into
unclassified: debug builds, `_krish` variants, repros, smoke tests, suites named
after a ticket. Both are kept out of line-wide yield, but only one of them is an
open question for somebody.

**The dashboard host reaches the controllers directly as of 2026-08-14.**
Tailscale was already installed and only needed authenticating. The carried
cache is no longer load-bearing, and the pipeline has no manual step left.

**pega5 may be a way round the L11 block.** It returns 40 L11 runs over 30 days
for the two stations EOS 502s on. Recorded on the feature-request page rather
than built: it means a second source for one station's data.

Registry changes now take effect at **build** time, not collect. The station a
run belongs to, and the registry snapshot the page renders, are both derived
from code and re-derived when `runs.json` is read — before this, editing
`stations.py` and running `make build` changed nothing until the next collect,
which looked exactly like the edit not working.

## New builds vs retests

`dashboard/builds.html` marks every run as a new build — the unit's first time
through that station in the window — or a retest, and a retest carries what the
unit failed last time.

It was built for a question that had no answer: when `mlt_2026.225` was
validated, 24 units went through it, 8 of them the debug set the fix was
developed on, and nothing could separate those from the other 16. The
**previously failed** filter does exactly that — `LlamaForwardIterated` returns
42 units that failed it and have since been retested, which is the list needed
to validate a fix on boards it was not written against.

Line-wide the split is worth knowing on its own: **new builds pass 63.7%,
retests after a failure 27.4%, retests after a pass 73.0%.**

History is per station and is walked across the whole collected window before
the tail is published, so a unit whose earlier failure fell outside the
published days is still shown as a retest — presenting it as a new build is the
error that would make a fix look better than it is.

## Two station pages, and why they disagree

The daily yield on the station page has never quite matched the line's own
numbers, and the cause is upstream of any chart: **EOS records one run per
fixture, a controller records one result per unit.** Every metric built on the
first answers a slightly different question.

So there are now two pages with the same layout and different sources, each
saying which it is in a **Data source** cell beside Last fetch:

| | `index.html` | `direct.html` |
|---|---|---|
| Source | OCP Logs / EOS API | pega2 – pega5 |
| A run is | one fixture | one unit |
| MLT pass rate | ~28% | ~55% |
| L11 | HTTP 502 | **has data** |

`pega_collect.py` emits the same payload shape `collect.read_runs()` does, so
`daily.py` and `build_stations.py` are reused untouched — the second page is a
different collector, not a second dashboard. A module fixture run becomes eight
records, one per slot, each carrying that chip's tests and that chip's verdict.

The landing page carries the reconciliation at its very bottom, computed from
both bundles on every build. It is there to be pointed at: a paragraph
explaining the difference is only as good as the day someone wrote it, and the
first question anyone asks about a yield number is whether it is right.

It also admits what each page is missing rather than only what they disagree
about. L11 is empty on the EOS side (HTTP 502); Chip Screening and SLT are empty
on the direct side, because no controller we read reports them under those
names. Those rows are marked.

The strongest line in it is the cross-check: rebuilding 2026-08-12 from the
controllers reproduced the line's hand-kept tracker exactly — 51 of 51 units, 92
verdicts, no disagreement, from the same 14 suite runs the sheet cites. The
derived unit-yield figure on the EOS page (57.2%) also agrees with the direct
page rather than with the run-level number above it, which is two independent
routes to the same answer.

The direct page is the one to make default once it has been read against the
line's numbers for a few days; `index.html` stays reachable from it either way.

## The L10 tracker

`dashboard/l10.html` gives the chassis line the same daily view the module line
has: one row per chassis per day across FAT, SFT, RIN and 2U, from pega4.

It reuses the module tracker's renderer unchanged — same columns-and-rows
bundle, same page chrome — so the two read alike without a second
implementation to keep in step. What differs is forced by the subject: an L10
run tests one chassis rather than eight slots (`participating` is `null`), so a
unit's failures are every failing test in its run; there is no hand-kept sheet,
so every tab is derived; and there is no Jira column, because those keys come
from the module line's spreadsheet.

pega4's suite names needed accommodating. FAT has run as `L10_FAT`,
`L10_6U_FAT` and `L10_6U_FAT_195` through `_207` — the trailing number is a
release, not a stage — alongside `_out_dir`, `_SAM`, `DRY_RUN_` and `_krish`
variants that are not stages at all. `L10_2U_tests` is treated as the 2U stage:
EOS calls the same thing `L10_2U`, and pega4's runs carry the production part
number `81S15V000050` and the same chassis serials FAT uses.

The pega client is multi-host now, with the cache and the unreachable flag keyed
by host — pega3 and pega4 answer the same paths with different data, and one
line's runs must never be served to the other.

**L11 is the same shape of work.** pega5 drives `pt2_l11_station1` and `2` and
returns 40 runs over 30 days for the two stations EOS 502s on.

## Cross-check: the tracker sheet against what we fetch

Both hand-kept days were compared cell by cell against the same days rebuilt
from pega3.

| | 2026-08-11 | 2026-08-12 |
|---|---|---|
| Units in the sheet | 87 | 51 |
| Present in the fetch | **87 of 87** | **51 of 51** |
| MLT verdicts agreeing | **87 of 87** | **51 of 51** |
| HTT verdicts agreeing | **64 of 64** | **41 of 41** |
| FI test links agreeing | **all** | **all** |
| Rows whose failure list contains the line's name | **39 of 40** | **24 of 24** |
| Failures the sheet never recorded | +47 | +26 |

Those failures are no longer only in the derived days: the sheet's own tabs are
filled in from pega3, so 08-11 and 08-12 list every failure on a unit exactly
as 08-13 does. Only the two failure columns are touched — the verdicts, links
and Jira keys stay the line's, and a name the line typed that pega3 lacks is
kept alongside rather than overwritten.

Every page also carries the build that made it (`v0.4 · 0ac933d · repo`), since
a published copy is rsynced by hand and otherwise drifts from `main` silently.

**The sheet is pega3 minus serial lot `26849410`.** On 08-11 the sheet holds
lots 26849411 (71) and 26849413 (16); pega3 has those same 87 plus 25 units
from lot 26849410 and nothing else. On 08-12 no lot-10 units ran, which is why
that day matched exactly. That is very likely the curation rule nobody could
name — it needs one sentence of confirmation from the line.

The failure column now lists **every** test case that failed on the unit, not
the first — a unit that fails eight tests has eight things wrong with it. That
turns the column into a superset of the line's: 63 of 64 rows contain the name
a person typed, and 61 further failures appear that the sheet never recorded.

The single row that does not contain it is instructive. On 08-11 the sheet
names `RunAllAttnTestsSingleChipTestCase` for DUT 268494110000091. That unit
sat in slot 7 of run 4d1531d6 and had no such failure; the `RunAllAttn…`
failure in that fixture belongs to **slot 1**, DUT 268494110000060, and is
spelled `RunAllAttnHbmBypassTestsSingleChipTestCase`. It is a neighbouring
slot's failure written on the wrong row — which is the kind of error that stops
happening when the column is derived rather than transcribed.

Two bugs in the fetch were found by this comparison and fixed: the run-level
`first_failed_test_case` was being attributed to every failed unit in a fixture
(it is usually a container or another chip's failure), and a unit tested twice
in a day kept whichever attempt pega3 happened to return last rather than the
latest one.

## What was verified, and what it changed

`make inspect` was run against l10, slt and module. Three findings materially
changed the ETL — each would have left the dashboard looking fine while being
wrong.

**1. `/runs` has no status, end time or duration.** It returns only `runId`,
`level`, `dutSerial`, `suite`, `version`, `startedAt`, `prefix` — identical at
every level. Every run initially parsed as `unknown` with no cycle time, emptying
two of the four metric groups. Both now come from the `event_stream`
(`log.jsonl`) artifact, which is the only source of run timing and verdict.

**2. `INTERRUPTED` was 556 of 1006 test entries** and fell through to `unknown`.
It means the suite aborted and the test never ran, so it maps to `skip` and
leaves the yield denominator. Mapping it to `fail` would tank yield on every
aborted run. Full observed vocabulary is now handled: `PASSED`, `FAILED`,
`ERROR`, `TIMEOUT`, `SKIPPED`, `INTERRUPTED`, `EXITED`.

**3. TLS to the EOS host fails for every client**, `curl` included. The host uses
Etched's internal PKI and serves a chain that cannot be completed — the
intermediate that signed it (`IDM.ETCHED.COM`) is never sent, and the root that
is sent is unrelated. `make trust` fetches the real anchor and authenticates it
against the MDM-installed root in the system keychain.

## Open items

### Blocked by the API — cannot be fixed here

- **L11 Provision / L11 Test.** EOS returns HTTP 502: the API key's IAM role is
  denied `s3:ListBucket` on `etched-mfg-prod-l11-raw`. Both are in the registry
  as `blocked`, render the real error, and need no code change once access is
  granted — only confirmation of their suite names, which are currently
  unverified guesses.
- **Physical fixture identity.** Distinct from the line's "stations" (which are
  test stages and *are* mapped): no fixture field exists on `/runs`,
  `dutInfo.platformInfos` is empty, and `resource_config` holds DUT addresses.
- **Station utilization / idle time.** Needs state the API does not expose.

### Needs a decision from someone else

- **290 `Vbb*` provisioning runs at level `l6` are unclassified** —
  `VbbCec173xProvisioning{Internal,External,…}`, `VbbFlashAndLockBootloader`,
  `VbbValidateProductionProvisioning` and five more, 07-14 to 08-12, 79 DUTs,
  215 pass / 64 error / 11 fail. They look like a real provisioning stage rather
  than engineering runs, but no station on the line has been named for them.
  Check the FAMILY column in OCP Logs (the only place that mapping is visible)
  and they can be registered the way HTT was.
- **23 runs are on placeholder DUT serials** — `DRY_RUN_*` (21), `TEST`,
  `RENAME_TEST_0` — spread across MLT, SLT, chip screening and HTT, and 20 of
  them fail or error. They currently count toward those stations' yield. If the
  line agrees they are not units, the registry should exclude them the same way
  it excludes the `_krish` debug suites.
- **No Jira URL yet.** The tracker's notes column holds real keys
  (`ETCH-38567`) but none renders as a link, because no URL carrying one has
  been observed from here. It is one environment variable away
  (`FACTORY_JIRA_BASE`) once someone pastes a real one. Until then the keys stay
  plain text: a column of dead links is worse than a column of keys.
- **`EXITED` → `error` is an assumption.** It could equally mean a clean early
  exit. ~0.5% of entries, so low impact, but it should be confirmed with the EOS
  team rather than left as a guess.
- **First-pass yield is window-relative.** Attempts are numbered within the
  collected window, so a short window inflates FPY. The last run showed 123 runs
  across only 35 units — mostly retries — so hours with no first attempts report
  `—`. Decide the standard collection window before FPY is used as a KPI.

### Settled — do not re-investigate

- **OCP Logs has no per-run URL.** Confirmed 2026-08-13 by selecting three runs
  in a logged-in browser: the address bar stayed `https://ocplogs.core.etched.com`
  for all three while the detail pane changed. The RUNS tab keeps its filter and
  its selection in memory, so neither a run permalink nor a pre-filtered search
  link exists to be constructed. The Source column therefore opens the tool and
  offers the identifier, which is the most that can be done.

  The investigation established two better things. OCP's RUN ID column is our
  `runId` character for character, so OCP Logs is a second reader of the records
  this ETL already collects — `runs.html` is the per-run permalink OCP itself
  cannot offer. And OCP's only run-identifying filter is DUT SERIAL, so the
  useful thing to hand a reader is the serial and the date.

### Tracked on the feature-request page

`dashboard/requests.html` now carries every ask against a system we do not own,
with a probe where the answer can be checked rather than asserted. It is built
hourly, so the status there is never older than the page. The escalations below are
mirrored into it; this list stays as the written record.

### To escalate

- **`resource_config` artifacts contain plaintext SSH and BMC credentials** for
  the DUT (`username` / `password` in cleartext). Anyone with an API key can read
  them. This repo never fetches that role, but the exposure is real.
- **The EOS TLS chain should be fixed server-side** — serve the IPA CA as the
  intermediate instead of the unrelated corporate root, and no client needs
  `make trust`.
- **`32x-production.i.etched.com` serves its leaf certificate and nothing
  else** — `openssl s_client -showcerts` returns exactly one cert — so no client
  can build a path and every reader gets a browser warning. The issuer,
  `O=IDM.ETCHED.COM, CN=Certificate Authority`, is signed by `Etched RSA
  Corporate Root CA`, which MDM already installs on every managed Mac: pointing
  `ssl_certificate` at the fullchain fixes it for everyone with no client
  change. Same omission as EOS, one host up. Confirmed 2026-08-13: plain `curl`
  fails, `curl --cacert certs/etched-internal-ca.pem` returns 200.
- **Whether the site should be readable by anyone on the VPN** is a decision
  nobody has actually made — it was a side effect of moving off Pages.

## Not done yet

- Drill-down from the Failure Pareto into a test's `log_file` trace. The paths
  are already collected and stored per failure; nothing is wired to open them.
- Hourly roll-up of per-test durations (collected per run, not aggregated).
- **The Update button is not wired up on the dashboard host.** nginx already
  proxies `/api/` there to `127.0.0.1:8765`, which is exactly what
  `factory.control` wants, so the published page could carry a working button
  instead of a `Snapshot` chip. Two things block it: the control server binds
  8787, and its POST guard requires a loopback `Host` header that an nginx proxy
  will not send. Relaxing that guard means thinking about who can reach the
  route once it is no longer loopback-only — the box is inside the network, but
  so is everyone. `docs/deploy.md` has the detail.
- The seven root-cause rules added for EOS signatures should be **ported back to
  `test-daily/tools/build_dashboard.py`**, or the two dashboards will bucket the
  same failure differently.
- No CI. Tests run locally via `make test`.
- The reference palette's colorblind validator has never been run here (it needs
  Node, which is not installed). Values are used exactly as documented, which is
  the condition their validation holds under.

## Layout

```
src/factory/   eos_client · parse · collect · hourly · build_dashboard
               stations · rootcause · daily · fetchstate · build_stations
               demo_data · trust · cli · config
               items · releases · control
               xlsx · build_dailyexcel · links · chips
dashboard/     index.html (station yield) · hourly.html (rates)
               releases.html (test items by release) · runs.html (drill-down)
               dailyexcel.html (the line's tracker) · update.js · styles.css
tools/         hourly_refresh.sh · publish.sh (web root | gh-pages)
deploy/        launchd/ (macOS agent) · systemd/ (Linux user timer)
docs/          api-usage.md · metrics.md · dataviz-notes.md · deploy.md
daily/         the tracker export the daily page reads
tests/         196 tests over parsing, metrics, stations, fetch state, items,
               releases, the run bundle, the .xlsx reader and the control
               endpoint
```

Gitignored and never committed: `.env`, `certs/`, `data/`, `dashboard/data/`.
