# Project status

**As of 2026-08-07 (updated).** Snapshot of what works, what was verified against the live
API, and what is still open. Metric definitions live in `docs/metrics.md`; the
verified API schema in `docs/api-usage.md`.

## Published

**https://cuddly-enigma-pz3pz29.pages.github.io/** — private GitHub Pages
(`public: false`), Etched org login required; an anonymous fetch gets the login
page and no data. Served from the `gh-pages` branch, replaced by a single orphan
commit on each publish so the hourly bundles never accumulate in history.

## State: working end to end on live data

The full path — fetch → normalize → hourly metrics → dashboard — runs against
production EOS. Nothing is stubbed.

```sh
make trust             # one-time: internal CA
make refresh           # collect 30 days + rebuild both dashboards
make schedule-install  # hourly launchd agent, :05 past the hour
make publish           # push to the private Pages site
make serve             # http://127.0.0.1:8787/  (station yield)
```

| Check | Result |
|---|---|
| Unit tests | 83 passing (`make test`) |
| `/levels` | `l6, l10, l11, slt, module, bringup` |
| Live collect | 1062 runs over 30 days across l6 + l10 + slt + module |
| Status / duration resolved | all runs |
| Stations mapped | 6 of 9 producing data; HTT unmapped, L11 ×2 blocked |
| Pareto coverage | "Other" 10.2% (was 71% before the container + separator fixes) |
| Dashboards | both render on real data, light + dark, headless-Chrome verified |

Station counts over the 30 days to 2026-08-07: SLT 296 · Chip Screening 206 ·
MLT 198 · L10 FAT 102 · L10 SFT 99 · L10 RIN 9 · unclassified 152.
Line-wide: 910 classified runs, 420 units, FPY 58.2%, pass rate 40.2%.

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

- **HTT station.** No suite matching HTT exists in EOS at any level (searched
  suite, version, runId and prefix over 30 days). It is in the registry as
  `unmapped` and renders an explicit card; give it a suite name and it works.
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

- **`EXITED` → `error` is an assumption.** It could equally mean a clean early
  exit. ~0.5% of entries, so low impact, but it should be confirmed with the EOS
  team rather than left as a guess.
- **First-pass yield is window-relative.** Attempts are numbered within the
  collected window, so a short window inflates FPY. The last run showed 123 runs
  across only 35 units — mostly retries — so hours with no first attempts report
  `—`. Decide the standard collection window before FPY is used as a KPI.

### To escalate

- **`resource_config` artifacts contain plaintext SSH and BMC credentials** for
  the DUT (`username` / `password` in cleartext). Anyone with an API key can read
  them. This repo never fetches that role, but the exposure is real.
- **The EOS TLS chain should be fixed server-side** — serve the IPA CA as the
  intermediate instead of the unrelated corporate root, and no client needs
  `make trust`.

## Not done yet

- Drill-down from the Failure Pareto into a test's `log_file` trace. The paths
  are already collected and stored per failure; nothing is wired to open them.
- Hourly roll-up of per-test durations (collected per run, not aggregated).
- **The publisher is one Mac.** The hourly agent both collects and publishes, so
  the site goes stale whenever that machine is asleep or off the VPN. CI cannot
  take over — EOS is on a private address a GitHub runner cannot reach. A
  always-on host inside the network would fix it. The page's "last fetch" panel
  is what makes the staleness visible rather than silent.
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
dashboard/     index.html (station yield) · hourly.html (rates) · styles.css
tools/         hourly_refresh.sh · publish.sh   deploy/launchd/  hourly agent
docs/          api-usage.md · metrics.md · dataviz-notes.md
tests/         83 tests over parsing, metrics, stations and fetch state
```

Gitignored and never committed: `.env`, `certs/`, `data/`, `dashboard/data/`.
