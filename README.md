# factory_data_analysis

Hourly manufacturing metrics from the EOS test-log API, as a static dashboard.

Pulls test runs from `eos.core.etched.com`, normalizes them into a flat run
table, and renders two views: **per-station yield** (daily, by software release,
failure Pareto, retest) and **hourly rates** (throughput, yield, cycle time).
Refreshes hourly.

Python 3.9+ standard library only. No pip install, no npm, no build step.

Working end to end against production EOS — see [`STATUS.md`](STATUS.md) for the
current state, validation results and open items.

![pipeline](https://img.shields.io/badge/deps-stdlib%20only-informational)

## Quick start

No API key needed to see it working:

```sh
make demo          # generate synthetic runs + build the dashboard bundle
make serve         # http://127.0.0.1:8787/  (station yield)
```

Against real data:

```sh
make trust                 # one-time: install Etched's internal CA (see TLS below)
cp .env.example .env       # then put your key in EOS_API_KEY
chmod 600 .env
make levels                # smoke test: should print the allowed levels
make inspect               # confirm the live API field names map correctly (do this once)
make collect DAYS=2        # fetch runs + suite summaries
make build                 # compile them into the dashboard bundle
make serve
```

You must be on the corporate network or VPN — the EOS host resolves to a private
address.

`make report` prints the same metrics as text if you just want numbers.

## Live site

**https://32x-production.i.etched.com**

Served by nginx from `/var/www/32x-production` on
`chuck-dashboard.usw2.i.etched.com` — a t3.medium running AlmaLinux 9, inside
the corporate network. That same host runs the collection hourly and
unattended, which is the point of it: it can reach EOS (a GitHub runner cannot)
and it does not sleep (a laptop does). The move is written up in
[`docs/deploy.md`](docs/deploy.md).

**Access posture is weaker than the Pages copy it replaced.** There is no login
on this site — anyone on the office network or VPN can read it, and it carries
real factory data (DUT serials, failure signatures, yield). It is not routable
from outside, which is the whole of its protection. If that is not enough,
restricting it is an infra request, not a change here.

```sh
make update           # THE FULL UPDATE: collect + items + rebuild + publish
make publish          # publish the current dashboard/, nothing else
```

`make publish` has two targets and chooses by environment: with
`FACTORY_WEB_ROOT` set — on the dashboard host, via `.env` — it copies into that
directory; without it, on a laptop, it force-pushes to `gh-pages`. Everything
upstream calls the one script either way.

### The GitHub Pages copy

**https://cuddly-enigma-pz3pz29.pages.github.io/** — the previous home, and
still private (`public: false`): an unguessable URL, and an anonymous request is
redirected to a GitHub login, so only authenticated Etched org members can open
it. It is **frozen at its last publish**, because the laptop agent that fed it
has been uninstalled.

A `make update` from a laptop still refreshes it, which is worth knowing before
you run one; `FACTORY_PUBLISH=0 make update` rebuilds locally and publishes
nowhere. Retire it once the internal host has been blessed.

### The Update button

Pages is stale until something publishes to it. `make serve` puts an **Update**
button in the dashboard header that runs the whole chain and streams each stage
back to the page:

```sh
make serve            # http://127.0.0.1:8787/ — the button is in the header
```

One click = `make update` = what the hourly agent runs. All three shell out to
`tools/hourly_refresh.sh`, so there is one update path and it cannot drift. The
script holds a lock, so a click during an hourly tick backs off rather than
running two collections at once.

Expect ~3–4 minutes: a 30-day collect dominates, and the item ingest is
incremental (only runs it has not seen before cost API calls).

**The button is only live on a locally served copy.** On any published copy it
renders as a `Snapshot · Nh ago` chip instead, because nothing there answers
`/api/ping`. A button that could not do what it says would be worse than no
button.

On the dashboard host that is a wiring gap rather than a law: nginx already
proxies `https://32x-production.i.etched.com/api/` to `127.0.0.1:8765`, which is
exactly what `factory.control` wants. Two things stand in the way — the control
server binds 8787 and its POST guard requires a loopback `Host` header, which an
nginx proxy will not send. See [`docs/deploy.md`](docs/deploy.md).

Each publish is a **single orphan commit that replaces the branch**. The bundles
are ~650 KB and rebuild hourly; committing them onto a branch with history would
grow the repository by that much every hour forever. `main` keeps all the code
and none of the data.

> CI cannot do the collection: EOS resolves to a private address, so a GitHub
> runner cannot reach it. The dashboard host, being inside the network, both
> fetches and serves.

## The pages

**`dashboard/index.html` — station yield (the landing page).** Per-station daily yield, yield by
software release, failure Pareto by root-cause area, and retest. Stations are
test stages (VBB provisioning, MLT, HTT, chip screening, SLT,
L10 FAT / SFT / RIN / 2U, L11 x2), defined in `src/factory/stations.py`, each
recording the ESVM controller that drives it — pega2 provisions VBB boards,
pega3 runs the module stations, pega4 L10, pega5 L11. That is more than
bookkeeping: the controller is the authority on what a station *is*, and pega2
is what settled a 289-run group that had been unclassified for a week. Suite names do not always say which station they
belong to — HTT runs under `rdqs_sweep_training` — so check the FAMILY column in
OCP Logs before concluding a station has no data. Format follows the existing daily dashboard
(`go/test-dashboard`) so the two read alike.

**`dashboard/hourly.html` — hourly rates.** Throughput, yield, cycle time and
failure Pareto bucketed by hour.

**`dashboard/runs.html` — the raw run table.** Every number on the station page
is a count of runs, and every one of them links here, to the rows behind it.
Underlined figures are the ones you can drill into; charts drill from the bar.
One row per run, expandable to its test cases.

The filter lives in the URL hash, so a view is a link someone can paste:

```
runs.html#station=l10_rin                          one station
runs.html#station=mlt&release=220                  a release
runs.html#station=mlt&day=2026-08-11&status=fail   a day's failures
runs.html#station=slt&attempt=first&status=graded  the FPY denominator
```

Filter keys: `station`, `day`, `release`, `status` (`pass` / `fail` / `abort` /
`graded`), `attempt` (`first` / `retest`), `dut`, `suite`, `level` — with the
same meanings `daily.py` gives them, so the row count always reconciles with the
number that was clicked. `abort` means EOS's `error`; see
`src/factory/build_runs.py`.

**`dashboard/builds.html` — new builds and retests.** Whether a unit was seeing
a station for the first time or coming back, and if it is back, what it failed
last time. Colour-coded, but the word is there too — the page is meant to be
screenshotted into a thread.

```sh
make builds            # also runs inside `make build`
```

It exists because "the new suite passes" is only evidence if the units it passed
on are not the units the fix was written against. The **previously failed**
filter is the point rather than a convenience: typing `LlamaForwardIterated`
gives the units that failed it before and have since been retested — 42 of them
across MLT and HTT at the time of writing — which is the list needed to validate
a fix on boards it was *not* developed on.

Line-wide the split is stark: **new builds pass 63.7%, retests of failed units
27.4%**.

*"New" is relative to the collected window* — widen it and some of today's new
builds become retests, the same caveat first-pass yield carries. A retest's
history is not relative in the same way: if a unit failed here before, it failed.
The page prints its window.

**`dashboard/direct.html` — station yield, straight from the controllers.** The
same page as the landing one, computed from pega2–pega5 instead of from EOS.
Each page says which it is, in a **Data source** cell beside Last fetch.

```sh
make pega-stations     # also runs inside `make build`
```

**The landing page carries the proof at its very bottom.** A section called
*Why this page and the direct page disagree* gives a station-by-station table of
what each source says, computed from both bundles on every build rather than
written down once — so it is still true tomorrow and can be pointed at when a
number is challenged. Rows where one source has nothing are marked, because each
page is missing something.

They disagree, and the disagreement is the reason both exist. EOS records **one
run per fixture**; a controller records **one result per unit**. So MLT reads
about 28% on the OCP-sourced page and about 55% here, and the second is the
number the line means. The direct page also has **L11 data** — the two stations
EOS returns HTTP 502 for.

Nothing downstream is duplicated: `pega_collect.py` emits the same payload shape
`collect.read_runs()` does, so `daily.py` computes the same metrics and
`build_stations.py` compiles the same bundle. The only difference is where a run
came from.

**`dashboard/l10.html` — the L10 daily tracker.** The same format as the module
tracker, for the chassis line: one row per chassis per day across **FAT, SFT,
RIN and 2U**, built entirely from **pega4** (stations `pt2_l10_station6` and
`7`).

```sh
make l10               # also runs inside `make build`
```

Three things differ from the module tracker, all forced by the subject rather
than chosen. An L10 run tests **one chassis, not eight slots** — pega4 returns
`participating: null` — so a unit's failures are every failing test in its run,
and the slot filtering the module tracker must do would here drop everything.
There is **no hand-kept sheet** for L10, so every tab is derived and none is the
line's own record. And there is **no Jira column**, because those keys come from
the module line's spreadsheet.

pega4's suite names carry a release suffix — FAT has run as `L10_FAT`,
`L10_6U_FAT` and `L10_6U_FAT_195` through `_207` — so the patterns accept every
spelling. A pattern matching only today's name silently zeroes a station the
next time the line renames one, which has already happened here once.

**`dashboard/requests.html` — what we need from other systems.** A route, a
certificate, an IAM grant, a field in someone else's API, a decision that is not
ours. Only asks that need *someone else* — work we can do ourselves stays in
STATUS.md.

The checkable ones **check themselves on every build**: pega3 reachability, how
many certificates the site serves, whether the l11 502 is still coming back,
whether a Jira or OCP URL is configured. So an entry reads
`blocked · checked 4 minutes ago` rather than making a claim of unknown age, and
an ask someone quietly fixed turns green on the next hourly build with nobody
editing the registry.

Two things it is careful about, both learned the hard way. A probe is only true
where it ran — "pega3 is reachable" from a laptop says nothing about the
dashboard host — so the answer carries the hostname and the page prints it. And
the TLS probe counts the certificates nginx *serves* rather than asking whether
this machine can verify: import the missing intermediate locally, which is the
documented workaround, and a verification-based check would go green while every
other reader still gets a warning.

```sh
make requests          # re-check now; also runs inside `make build`
```

**`dashboard/dailyexcel.html` — the line's daily MLT/HTT tracker.** The one page
here that is *not* derived from the API. The module line keeps a Google Sheet of
which units passed MLT and HTT each day, which test case failed and which Jira
ticket tracks it — judgements no endpoint exposes, because a person made them.
Export it to `daily/` and it is published as a faithful copy of the tab, colours
and column widths included:

```sh
make dailyexcel        # also runs inside `make build`
```

Tabs are found by name, so `08-11 87x` and `08-12  51x` publish themselves and
tomorrow's `08-13 62x` will too, with no code change. The **FI Test Link**
columns keep the sheet's own hyperlinks, which point at
`pega3:3000/suite_run/…` — pega3 asks for an ESVM login before it will show a
run.

The **failure column lists every test case that failed on that unit**, oldest
first, one per line — not just the first. On a day the workbook already covers,
the sheet's own column is *filled in* from pega3 rather than replaced: the
verdicts, links and Jira keys stay the line's, and a name the line typed that
pega3 does not have is kept alongside. That recovered 47 failures on 08-11 and
26 on 08-12 that the sheet had dropped. A unit that fails eight tests has
eight things wrong with it, and the one that ran first is rarely the
interesting one. Nest rows are left out (`chip5` fails because a leaf under it
did, and `ServerNestedTestCase` would otherwise appear twice in one cell); set
`FACTORY_DAILY_CONTAINERS=1` for the literal list pega3's UI shows.

A **DUT serial becomes a link into `runs.html`** when — and only when — the
collected run table actually holds that serial. On the first build 32 of 138
did, and the page says so: for these two days the sheet records 138 units while
EOS returns 45 MLT/HTT runs per day. That gap is a finding about the two
sources, so it is printed rather than papered over with 138 links, three
quarters of which would land on an empty table.

The **Source** column links out to OCP Logs, which **has no per-run URL** —
confirmed in a logged-in browser: selecting three different runs left the
address bar at `https://ocplogs.core.etched.com` every time, because the RUNS
tab keeps its filter and selection in memory. So the column opens the tool and
offers the identifier to copy, and that is the most there is. `FACTORY_OCP_RUN_URL`
remains as an override if OCP ever grows real routes (`src/factory/links.py`).

Worth knowing: OCP's RUN ID column is our `runId` character for character, so
OCP Logs is a second reader of the same records — **`runs.html` is the per-run
permalink OCP cannot give you.** Its only run-identifying filter is DUT SERIAL,
so serial + date is what to hand someone who needs to open it by hand.

pega4 cannot be linked at all — its suite-run IDs are minted locally and appear
nowhere in the EOS payload.

## Hourly refresh

```sh
make refresh            # one tick: collect + record state + rebuild
make update             # the same, plus items and a publish
make status             # last fetch vs last update, per station
make schedule-install   # hourly job at :05  <- REQUIRED for the live site to
                        #   stay current on its own
make schedule-status    # is it loaded, and what did the last tick do
```

`schedule-install` dispatches on `uname`: a launchd agent on macOS, a systemd
**user** timer on Linux (`deploy/systemd/`). User units need no root, which
suits a host whose only sudo permission is `dnf install`. On Linux it also
enables linger — without it a user timer stops at logout, which would reintroduce
the very failure the always-on host exists to remove — and says so loudly if
polkit refuses.

Without `make schedule-install` nothing updates the live site on its own and it
freezes at the last manual publish. `make schedule-status` says so when that is
the case.

The scheduler tracks **two different timestamps**, because conflating them is
how a dashboard lies:

- **Last fetch** — the pipeline ran and the API answered.
- **Last update** — the data actually changed.

A tick that returns identical data advances only *last fetch*; the content is
hashed, so *last update* stays put and the page says "unchanged for N
consecutive fetches". Both are tracked per station too, so one busy station
cannot mask nine quiet ones. A failed fetch advances neither.

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
  trust.py            bootstraps trust for Etched's internal CA, safely
  stations.py         station registry: stage -> EOS level + suite
  rootcause.py        failure signature -> root-cause area (shared with test-daily)
  daily.py            daily yield, release yield, Pareto, retest
  fetchstate.py       last-fetch vs last-update bookkeeping
  build_stations.py   compiles the per-station views
  items.py            flattens test cases to numeric test items (SQLite)
  releases.py         per-release item views and compatibility diffs
  xlsx.py             a minimal .xlsx reader (stdlib: zip + XML)
  pega.py             read-only client for the ESVM controllers (pega2..pega5)
  build_l10.py        the L10 tracker: FAT/SFT/RIN/2U from pega4
  pega_collect.py     the run table built from the controllers, not from EOS
  compare.py          measures the gap between the two, at build time
  build_history.py    new build or retest, and what a unit failed last time
  version.py          which build made a page: release, commit, repo
  build_release_source.py  what each release contains, from the sw tree at the
                      commit its suite name carries
  suite_map.py        which suite YAML each station runs, and how we know:
                      BUILD's deploy_suite entries, the paths release scripts
                      pin, each file's own suite_name / run_name, then the
                      station registry — read at origin/master, not at the
                      builder's checkout
  chips.py            per-chip verdicts inside a fixture run
  requests.py         what we need from other systems, and probes for it
  build_dailyexcel.py compiles the line's tracker tabs from daily/*.xlsx
  control.py          the /api routes behind the Update button
  cli.py              trust | levels | runs | inspect | collect | demo
                      | build | refresh | status | report | items
                      | dailyexcel | release-source | suite-map | serve

dashboard/
  styles.css          palette + chrome (light/dark as role tokens)
  index.html + stations.js + stations.css   station yield (landing)
  hourly.html + app.js                      hourly rates
  releases.html + releases.js + releases.css  test items by release
  releasesrc.js       what each release contains, read from source
  suitemap.js         which suite YAML each station runs, with the evidence
  runs.html + runtable.js + runs.css        raw run table (the drill-down)
  dailyexcel.html + dailysheet.js + dailyexcel.css   the line's daily tracker
  requests.html + requests.js + requests.css   asks against other systems
  l10.html            the L10 tracker (same renderer as the module one)
  direct.html         station yield from the controllers (same renderer again)
  builds.html + builds.js + builds.css   new builds vs retests
  update.js           the Update button, shared by every page
  data/*.js           generated bundles (gitignored)

tools/hourly_refresh.sh    THE update path: lock, collect, items, build, publish
tools/publish.sh           publish dashboard/: copy to FACTORY_WEB_ROOT, else
                           orphan force-push to gh-pages
deploy/launchd/            the hourly agent plist (macOS)
deploy/systemd/            the hourly user service + timer (Linux)
daily/                     the tracker export (.xlsx) the daily page reads
certs/                     fetched CA bundle (gitignored; `make trust`)
data/raw/                  cached HTTP responses (gitignored)
data/processed/            runs.json + fetch_state.json (gitignored)
docs/                      api-usage.md · metrics.md · dataviz-notes.md
                           deploy.md (the dashboard host)
tests/                     196 unit tests over parsing, metrics, fetch state,
                           items, releases, the run bundle, the .xlsx reader
                           and the control endpoint
```

## Before you trust a number

The API doc pins the four endpoints but elides the field names inside run objects
and never specifies the `suite_summary.json` schema, so `parse.py` resolves every
field through alias tables. The live schema **has** been verified against l10,
slt and module data (2026-08-06) and is written up in
[`docs/api-usage.md`](docs/api-usage.md). Three findings shape the whole ETL:

- **`/runs` has no status, no end time, no duration.** All three come from the
  `event_stream` (`log.jsonl`) artifact, which is the sole source of cycle time
  and of a run-level verdict.
- **`INTERRUPTED` is the most common test status** on any aborted run. It means
  "never executed", so it maps to `skip` and leaves the yield denominator —
  treating it as a failure would tank yield on every aborted run.
- **No station *fixture* field exists anywhere.** The line's "stations" are test
  stages, mapped from level + suite in `src/factory/stations.py`; the hourly
  page's volume chart groups by a selectable dimension (suite / version / level).
- **Nested container test cases must be excluded from the Pareto.** EOS emits a
  parent entry beside the real leaf tests, and counting both double-counts every
  failure — it put 71% of failures in "Other".

Re-run the check whenever EOS changes:

```sh
make inspect
```

It prints the field names actually returned, shows how they resolved, and flags
anything it could not map. Failure modes it is built to catch: no start-time
field (the collector falls back to the `_20260803_094406` stamp in the run ID,
read as UTC — a warning is logged and the count appears in the dashboard footer),
and zero tests parsed, which empties yield and Pareto while throughput still
looks healthy.

### One security note

`resource_config` artifacts contain **plaintext SSH and BMC credentials** for the
DUT. This repo never fetches that role. Worth raising with whoever owns EOS —
anyone with an API key can read them.

## TLS: `CERTIFICATE_VERIFY_FAILED`

```
[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate
```

This is not a Python problem — `curl` fails the same way. `eos.core.etched.com`
serves a leaf issued by `ca.core.etched.com`, which is signed by the FreeIPA root
`O=IDM.ETCHED.COM, CN=Certificate Authority`. That root is in no public trust
store, **and the server does not send it**: the third certificate in the chain it
does serve (`Etched RSA Corporate Root CA`) is not the issuer of the second, so
nothing can complete the path.

```sh
make trust
```

fetches FreeIPA's published bundle, writes it to `certs/etched-internal-ca.pem`,
and the client adds it to — never replaces — the system trust store, so public
URLs keep verifying normally. Override the location with `EOS_CA_BUNDLE`.

**How the bootstrap is made safe.** The missing root is published over HTTPS on a
host with the same untrusted PKI, so that one fetch cannot be verified. Instead
of shrugging, `trust.py` authenticates the download out of band: the bundle must
contain the `Etched RSA Corporate Root CA` whose SHA-256 matches the copy MDM
already installed in this machine's keychain. A mismatch is treated as possible
interception and refuses to install. Off macOS, pass
`--fingerprint <sha256>` obtained from IT over a trusted channel — the check is
never skipped silently, and certificate verification is never disabled for real
API traffic.

**The real fix is server-side.** Whoever runs EOS should serve the IPA CA as the
intermediate instead of the unrelated corporate root; then no client needs this
step. Worth filing.

**The dashboard site has the same disease.**
`32x-production.i.etched.com` serves its leaf and nothing else — one certificate,
no intermediate — so a browser cannot build a path either, and every reader gets
a warning. Its issuer, `O=IDM.ETCHED.COM, CN=Certificate Authority`, is signed by
`Etched RSA Corporate Root CA`, which MDM already installs everywhere; serving
the fullchain would make it verify with no client changes at all. Until then, a
reader can supply the missing link locally without trusting anything new:

```sh
security import certs/etched-internal-ca.pem -k ~/Library/Keychains/login.keychain-db
```

The certificate still validates up to the MDM-installed root — this only hands
macOS the intermediate the server omits.

## Security

`EOS_API_KEY` is read from the environment (or a gitignored `.env`) by the Python
ETL only. It is never written to disk, never embedded in the dashboard bundle,
and the browser never talks to the EOS API. `data/` and the generated bundle are
gitignored, so factory data is not committed.

## Tests

```sh
make test
```

196 tests covering status normalization, timestamp and duration coercion, all
three plausible `suite_summary.json` shapes, station classification, the run
bundle's filter populations, the .xlsx reader, and every metric definition.
