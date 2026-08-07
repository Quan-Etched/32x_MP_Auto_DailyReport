# EOS External API — test-logs

Transcribed from `API/API Usage.docx` (the source of truth for this repo's ETL).
Requires EOS External API **v1.5.0+**.

Base URL:

```
https://eos.core.etched.com/api/external/v1/test-logs
```

Auth: `Authorization: Bearer $EOS_API_KEY` on every request.

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

## Unverified schema — read this before trusting a number

The endpoints above are specified; the **field names inside** run objects and
inside `suite_summary.json` are not. This repo therefore resolves every field
through alias tables in `src/factory/parse.py`, matching keys
case- and punctuation-insensitively, and returns `None` rather than raising when
a field is absent.

The first time you point the ETL at live data, run:

```sh
make inspect            # or: python -m factory.cli inspect --level l10 --days 1
```

It prints the field names actually present, shows how `parse.py` resolved them,
and flags anything unresolved. Add any missing spelling to the `*_ALIASES`
tables — that is the only place it needs to change.

Two failure modes it is designed to catch:

- **No start-time field resolved.** The collector falls back to the
  `..._20260803_094406` stamp in the run ID, read as UTC. If the stamp is really
  local wall-clock, hourly buckets will be shifted by the UTC offset. The
  collector logs a warning and the dashboard footer reports the count.
- **Zero tests parsed from `suite_summary.json`.** Yield and Pareto go empty
  while throughput still looks fine.
