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
| Unit tests | 175 passing (`make test`) |
| `/levels` | `l6, l10, l11, slt, module, bringup` |
| Live collect | 1062 runs over 30 days across l6 + l10 + slt + module |
| Status / duration resolved | all runs |
| Stations mapped | 8 of 10 producing data; L11 ×2 blocked (IAM) |
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
dashboard/     index.html (station yield) · hourly.html (rates)
               releases.html (test items by release) · update.js · styles.css
tools/         hourly_refresh.sh · publish.sh (web root | gh-pages)
deploy/        launchd/ (macOS agent) · systemd/ (Linux user timer)
docs/          api-usage.md · metrics.md · dataviz-notes.md · deploy.md
tests/         156 tests over parsing, metrics, stations, fetch state, items,
               releases and the control endpoint
```

Gitignored and never committed: `.env`, `certs/`, `data/`, `dashboard/data/`.
