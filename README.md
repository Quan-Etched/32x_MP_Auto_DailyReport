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

## Three dashboards and a drill-down

**`dashboard/index.html` — station yield (the landing page).** Per-station daily yield, yield by
software release, failure Pareto by root-cause area, and retest. Stations are
test stages (MLT, HTT, L10 FAT / SFT / RIN / 2U, SLT, chip screening), defined
in `src/factory/stations.py`. Suite names do not always say which station they
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

The **Source** column links out to OCP Logs. It has no confirmed per-run URL
yet, so today it opens the search page and offers the run ID to copy; set
`FACTORY_OCP_RUN_URL` to turn it into direct per-run links
(`src/factory/links.py`). pega4 cannot be linked at all — its suite-run IDs are
minted locally and appear nowhere in the EOS payload.

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
  control.py          the /api routes behind the Update button
  cli.py              trust | levels | runs | inspect | collect | demo
                      | build | refresh | status | report | items | serve

dashboard/
  styles.css          palette + chrome (light/dark as role tokens)
  index.html + stations.js + stations.css   station yield (landing)
  hourly.html + app.js                      hourly rates
  releases.html + releases.js + releases.css  test items by release
  runs.html + runtable.js + runs.css        raw run table (the drill-down)
  update.js           the Update button, shared by every page
  data/*.js           generated bundles (gitignored)

tools/hourly_refresh.sh    THE update path: lock, collect, items, build, publish
tools/publish.sh           publish dashboard/: copy to FACTORY_WEB_ROOT, else
                           orphan force-push to gh-pages
deploy/launchd/            the hourly agent plist (macOS)
deploy/systemd/            the hourly user service + timer (Linux)
certs/                     fetched CA bundle (gitignored; `make trust`)
data/raw/                  cached HTTP responses (gitignored)
data/processed/            runs.json + fetch_state.json (gitignored)
docs/                      api-usage.md · metrics.md · dataviz-notes.md
                           deploy.md (the dashboard host)
tests/                     175 unit tests over parsing, metrics, fetch state,
                           items, releases, the run bundle and the control
                           endpoint
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

175 tests covering status normalization, timestamp and duration coercion, all
three plausible `suite_summary.json` shapes, station classification, the run
bundle's filter populations, and every metric definition.
