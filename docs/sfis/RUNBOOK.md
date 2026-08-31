# Runbook

## Normal use

```sh
make doctor                                # first thing, always
make mirror SN=268947020002 VERDICTS=1     # ~40s for a 4U node
make unit   SN=268947020002                # -> out/268947020002.yaml
```

## When a unit fails and you need its full history

```sh
make mirror SN=<the failed unit> VERDICTS=1
make unit   SN=<the failed unit>
make gaps   SN=<the failed unit>
```

Read the YAML top-down:

1. `summary` — how many parts have real test evidence at all.
2. `self.test_records` — what the unit itself passed, and when it stopped.
3. `parts.*.subtree` — which branch holds the untested or failing parts.
   `failing_parts: 1` three levels up is the fastest way to the ASIC that failed.
4. Then walk into that branch.

`findings.serialized_without_records` is the list to send to Pega: parts Pega
serialized and has no route history for.

## When `pega-sfis` is down

Rendering never touches the network:

```sh
make unit SN=268947020002       # works; the file says how stale it is
make snapshots                  # what you have to work with
```

Check `snapshot.sfis_payloads_through` in the output — that is the last payload
Pega delivered before the snapshot was taken, and it is the honest age of the
answer. If it is older than the build you care about, the parts you are looking
for were linked after the snapshot and are genuinely not there.

If the receiver itself is broken rather than unreachable, the raw payload journal
on the receiver host (`/opt/receiver/data/{linking,process}`) is the real source
of truth and can be replayed — see `ty2-receiver/ARCHITECTURE.md` §8 and
`RESTORE.md`. That is Krish's procedure, not this repo's.

## Keeping snapshots useful

A snapshot is only insurance if it was taken before the outage. Nothing schedules
this yet. The obvious home is the dashboard host that already runs the `Analysis`
hourly refresh (`chuck-dashboard.usw2.i.etched.com` — inside the network, does
not sleep):

```sh
# not installed yet — the intended shape
15 * * * * cd /opt/32x-sfis && make mirror-level LEVEL=6U  >> /var/log/sfis-mirror.log 2>&1
45 * * * * cd /opt/32x-sfis && make mirror-level LEVEL=L11 >> /var/log/sfis-mirror.log 2>&1
```

Snapshots are small (a 4U node is ~1.5 MB) but they are not pruned. Add a
retention rule before turning on an hourly sweep of every level.

## Credentials

`make doctor` prints which credential is in use.

- **SFIS**: prefers `SFIS_TOKEN` (a read-only `APP_TOKENS` entry on the receiver
  — it cannot write). Falls back to basic auth. Ask Krish for a read token before
  running this unattended; do not run an unattended job as a built-in app user.
- **EOS**: `EOS_API_KEY`, plus `EOS_CA_BUNDLE` because Etched's internal PKI is
  in no public trust store. `Analysis/certs/etched-internal-ca.pem` already has
  it; point at that file rather than copying it.
- Both live in `.env` (chmod 600, git-ignored). Never in a shell profile.

## Reading a `coverage` you did not expect

| you see | it means |
|---|---|
| `none_expected` on a part you know was tested | the test names a *different* serial. Check whether EOS files it under a barcode (`docs/JOIN.md`) |
| `inherited_only` with an empty `inherited_records` | can't happen — that combination is `none_expected` |
| `process_only` on a board with SMT rows | correct: SMT/AOI/X-ray are `kind: fabrication`, not `test` |
| `traceability_gap: true` | Pega serialized it and has no route history. Real finding, send it on |
| `result: unknown` on an EOS record | the verdict was not resolved. Re-mirror with `VERDICTS=1` |
| `not_observed` | the mirror failed to fetch that serial. Its own records are unknown; re-mirror. Never reported as a gap |
| `fixture_scope: true` | one run, eight chips. Not a per-part verdict |

## Known limits

Listed in `README.md` under "Not done yet". The two that bite soonest: fixture
verdicts are not attributed to a slot, and consumable date/lot codes are not in
the linking payload at all.
