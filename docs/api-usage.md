# EOS External API — test-logs

Transcribed from `API/API Usage.docx` (the source of truth for this repo's ETL).
Requires EOS External API **v1.5.0+**.

Base URL:

```
https://eos.core.etched.com/api/external/v1/test-logs
```

Auth: `Authorization: Bearer $EOS_API_KEY` on every request.

Network: the host resolves to a **private address** — corporate network or VPN
required — and uses Etched's **internal PKI**, whose root is in no public trust
store and is not sent by the server. Run `make trust` once; see the TLS section
of the README for why the chain is broken and how the bootstrap is authenticated.

Call flow:

```
/levels  →  /runs  →  /artifacts  →  /artifact-content
```

## Date/time format

- Date only: `YYYY-MM-DD` — e.g. `2026-08-03`
- Date + time: ISO 8601 — e.g. `2026-08-03T07:00:00Z`
- **`from` and `to` are both inclusive.**

A local factory day is expressed as the UTC instants that bracket it. For
`2026-08-03` in `America/Los_Angeles`:

```
from=2026-08-03T07:00:00Z   to=2026-08-04T06:59:59Z
```

## GET /levels

Input: nothing. Output: the allowed levels.

```json
{ "levels": ["l6", "l10", "l11", "slt", "module", "bringup"] }
```

## GET /runs

Input: `level`; optional `dutSerial`, `from`, `to`, `suite`, `version`, station.
Output: run IDs.

```json
{ "runs": [
    { "runId": "L10_tests_2026.214.0-gita7f2fadc_20260803_094406",
      "dutSerial": "267694410001", "...": "..." }
] }
```

> The doc elides the rest of the run object with `...`, so the exact field names
> for start time, station and status are **not pinned by the spec**. See
> "Unverified schema" below.

## GET /artifacts

Input: `level`, `dutSerial`, `runId`; optional `role`. Output: the files in one run.

```json
{ "artifacts": [ { "relPath": "...", "role": "subtest_log", "size": 12174 } ],
  "totalBytes": 530989 }
```

Two roles matter for metrics:

| role | file | contents |
|---|---|---|
| `suite_summary` | `suite_summary.json` | every test in the run, with status and code trace |
| `suite_config` | `suite_config.yaml` | each test's configuration |

Each `suite_summary` entry should include a **`log_file`**; pass that value as
`relPath` to `/artifact-content` to fetch the test's full trace.

## GET /artifact-content

Input: `level`, `dutSerial`, `runId`, exact `relPath`. Output: the file bytes.

## Verified schema (observed 2026-08-06, levels l10 / slt / module)

The doc elides these, so they were confirmed against live data with
`make inspect`. Re-run it if EOS changes; `parse.py`'s `*_ALIASES` tables are the
single place to adjust.

### `/runs` entry — 7 fields, and three notable absences

```json
{
  "runId":     "L10_tests_2026.214.0-gita7f2fadc_20260804_070308",
  "level":     "l10",
  "dutSerial": "267694410001",
  "suite":     "L10_tests",
  "version":   "2026.214.0-gita7f2fadc",
  "startedAt": "2026-08-04T07:03:08Z",
  "prefix":    "s3://etched-mfg-prod-l10-raw/ocp-tests/l10/…"
}
```

**There is no `status`, no end time, no duration, and no station/fixture field** —
identical across all three levels. Run status and cycle time therefore come from
the `event_stream` artifact, and station is simply unavailable (see below).

### Artifact roles on a run

`upload_marker`, `subtest_log` (one per test), `bom_config`, `harness_log`,
`event_stream`, `resource_config`, `suite_config`, `suite_summary`.

The `suite_summary` file is named **`test_summary.json`**, not
`suite_summary.json`.

### `suite_summary` → `test_summary.json`

A bare JSON list; every entry has exactly these five keys:

```json
{ "test_name": "CheckBiosBootOrder", "unique_id": "CHK_BIOS_BOOT_ORDER",
  "status": "FAILED",
  "log_file": "artifacts/CHK_BIOS_BOOT_ORDER/iteration_1/chk_bios_boot_order.log",
  "parent_id": null }
```

`unique_id` is the stable grouping key (it also matches the `log_file` path);
`test_name` is the class name and is what the event stream keys its steps by, so
both are kept. `parent_id` was null on every entry observed — no subtest
hierarchy to de-duplicate yet. **There is no per-test duration here.**

Status vocabulary, complete as observed:

| value | mapped to | note |
|---|---|---|
| `PASSED` | pass | |
| `FAILED` | fail | |
| `ERROR` | error | |
| `TIMEOUT` | error | |
| `SKIPPED` | skip | |
| `INTERRUPTED` | **skip** | the suite aborted and the test never ran — the majority of entries on any aborted run |
| `EXITED` | **error** | terminated abnormally; **assumption**, worth confirming with the EOS team (~0.5% of entries) |

### `event_stream` → `log.jsonl`

OCP TestRun format, one JSON object per line. This is the **only** source of run
timing and verdict:

- `testRunStart` / `testRunEnd` timestamps → run duration
- `testRunEnd.status` (`COMPLETE` / `ERROR` / `SKIP`) + `.result`
  (`PASS` / `FAIL` / `NOT_APPLICABLE`) → the run verdict
- `testStepStart` / `testStepEnd` per step → per-test durations

Only steps that actually executed appear, which is why a run can list 88 tests in
`test_summary.json` and 9 steps here.

### ⚠️ `resource_config` — never fetched

It contains **plaintext credentials** for the DUT's SSH and BMC connections
(`username` / `password` in cleartext). It also holds only DUT network addresses,
not any station identity, so there is nothing to gain by reading it. The
collector never requests this role (`config.ROLE_NEVER_FETCH`).

### Station / fixture: not available

No station field exists on `/runs` at any level, `dutInfo.platformInfos` in the
event stream is empty, and `resource_config` describes the DUT rather than the
rig. The dashboard therefore offers **suite / version / level** as grouping
dimensions and hides the station control. The code path is retained for when EOS
adds the field.
