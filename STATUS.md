# Project status

**As of 2026-08-07.** Snapshot of what works, what was verified against the live
API, and what is still open. Metric definitions live in `docs/metrics.md`; the
verified API schema in `docs/api-usage.md`.

## State: working end to end on live data

The full path — fetch → normalize → hourly metrics → dashboard — runs against
production EOS. Nothing is stubbed.

```sh
make trust                                    # one-time: internal CA
make collect LEVEL=l10 DAYS=3 && make build   # or: make demo (no API key)
make serve                                    # http://127.0.0.1:8787/
```

| Check | Result |
|---|---|
| Unit tests | 48 passing (`make test`) |
| `/levels` | `l6, l10, l11, slt, module, bringup` |
| Live collect | 123 runs across l10 + slt + module, 3 days, no errors |
| Status resolved | 123/123 |
| Duration resolved | 123/123 |
| Dashboard | renders on real data, light + dark, verified in headless Chrome |

Last full validation run (3 days to 2026-08-06, `America/Los_Angeles`):
123 runs · 35 units · 36 active hours · 1.0 units/h · pass rate 19.7% ·
FPY 17.1% · cycle p50 10m41s / p90 21m57s.

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

- **Station / fixture breakdown.** No station field exists anywhere: not on
  `/runs` at any level, not in the event stream (`dutInfo.platformInfos` is
  empty), and `resource_config` describes the DUT's own addresses. The volume
  chart groups by a selectable dimension (suite / version / level) instead, and
  the station code path is retained for if EOS adds the field.
- **Station utilization / idle time.** Needs station state the API does not
  expose.

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
- Automated refresh — collection is manual. A cron or CI job writing the bundle
  to a static host is the obvious next step.
- No CI. Tests run locally via `make test`.
- The reference palette's colorblind validator has never been run here (it needs
  Node, which is not installed). Values are used exactly as documented, which is
  the condition their validation holds under.

## Layout

```
src/factory/   eos_client · parse · collect · hourly · build_dashboard
               demo_data · trust · cli · config
dashboard/     index.html · styles.css · app.js  (+ generated data/metrics.js)
docs/          api-usage.md · metrics.md · dataviz-notes.md
tests/         48 tests over parsing and metric definitions
```

Gitignored and never committed: `.env`, `certs/`, `data/`,
`dashboard/data/metrics.js`.
