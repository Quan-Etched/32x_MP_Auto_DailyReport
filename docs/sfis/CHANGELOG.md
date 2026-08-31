# Changelog

## 2026-09-01 — merged into factory_data_analysis

Moved from `etched-ai/32x-sfis` into this repository as `src/shopfloor`, with
history preserved (`git merge --allow-unrelated-histories` onto a branch whose
paths were already the destination paths).

Why this direction: all the history, the deployment and the published dashboard
were on the `factory_data_analysis` side (126 commits, a `gh-pages` branch, an
hourly job, `/var/www/32x-production`), and `tools/publish.sh` reads the remote
at publish time — so nesting this repo the other way would have moved the
dashboard's `gh-pages` target onto a different repo and changed its URL. The
dependency also runs one way: `shopfloor` imports `factory`, never the reverse.

What the merge deleted, which was the point:

- The `sys.path` shim into a second checkout, its `FALLBACK` station table, and
  `registry_source()`. `shopfloor.stations` now does
  `from factory.stations import classify, label_of`. The import cannot
  half-work, so there is nothing to fall back to and nothing to report.
- A second CA-bundle notion. `shopfloor.config.eos_ca_bundle()` delegates to
  `factory.config.ca_bundle()`, so one `make trust` fixes TLS for both tools.
- A second `.env` holding a second copy of `EOS_API_KEY`.
- A second `Makefile` and `.gitignore`.

Also fixed in the move: **the shopfloor tests were invisible to the repo test
runner.** They were plain functions, and `unittest discover` reported
`Ran 0 tests ... OK` — green, testing nothing. Converted to `TestCase`; the
suite now collects 773 tests including 14 shopfloor ones.

Make targets are `sfis-` prefixed (`sfis-doctor`, `sfis-mirror`, `sfis-unit`,
`sfis-level`, `sfis-units`, `sfis-gaps`, `sfis-snapshots`) — `help`, `test` and
`clean` were the only three names that collided, and `unit`/`units` were too
generic to keep in a repo where "unit" already means several things.

## 2026-08-31 — initial

First working version. Mirrors `pega-sfis` + EOS to a local snapshot and renders
one YAML per top-level serial: the part-SN tree with each part's test history and
an explicit verdict on which parts can have one.

### Verified against live systems on 2026-08-31

Everything below was observed, not assumed. Re-check before relying on a number.

- **The join that makes part-level test records possible.** EOS files Sohu module
  tests under the interposer barcode — `level=slt suite=mlt
  dutSerial=JE60702845202602090204` — which is the same string SFIS stores as a
  `BO` component under the PV1 (`DUB`). Cross-checked over August: of 282 distinct
  SLT-level DUTs, **233 are present in SFIS genealogy and 49 are not**.
- **Only Etched-numbered serials carry SFIS process events.** All 21 rack-level
  parts of `268862070001` return zero; the `ND` node returns 7, the PV1 12
  (SMT/SPI/AOI/X-ray/DIP). Vendor barcodes are scanned in, never tested by SN.
- **Rendered end to end**: 4U node `268947020002` → 52 parts, 22 tested, 16
  inherited, 12 process-only, 2 none_expected, 0 gaps. Rack `268862070001` → 21
  parts, all `none_expected`.
- **Offline rendering** confirmed with both upstreams pointed at a dead host.
- **EOS levels**: `l6`, `l10`, `module`, `slt` readable; `l11` and `bringup`
  return HTTP 424 — the API key cannot read those buckets. Matches the `blocked`
  levels documented in `Analysis/src/factory/stations.py`.
- **Station registry** imported from `factory.stations`, not copied.

### Bugs found and fixed while building

Each one is a case where the tool was quietly wrong rather than loudly broken,
which is the failure mode that matters here. All four have regression coverage.

1. **Serials containing spaces broke the URL.** The Sohu stiffener is recorded as
   `1006470-H 202606260068`; `urllib` refuses a raw space, so five parts per 4U
   node arrived with no attributes at all. Path segments are now percent-encoded
   (`sfis._segment`). Mirrored serial count went 73 → 75.
2. **An unretried timeout silently degraded a snapshot.** One 30-second timeout on
   the EOS `slt` sweep dropped every MLT record; the rendered file lost 8 of its
   22 tested parts and looked healthy apart from one manifest line. Sweeps and
   lookups now retry twice on transient faults with a 180s sweep budget, and
   anything still degraded is listed in `warnings:` at the top of the document
   and echoed to the terminal.
3. **`traceability_gap` was folded into `coverage`.** A serialized part with no
   route history came out `inherited_only` whenever its parent happened to be
   tested — i.e. the cases worth finding read as fine. Now a separate flag.
4. **A failed lookup was reported as a traceability escape.** A part we never
   fetched is indistinguishable from a part with no records, so the tool would
   have sent Pega false positives. `traceability_gap` now requires that we
   actually looked, and unfetched parts render `coverage: not_observed`.

### Known limits

See "Not done yet" in `README.md`. The two that bite soonest:

- **Fixture verdicts are not attributed to a slot.** An MLT run covers eight
  chips; the slot→unit mapping is on pega3. Inherited module-level records carry
  `fixture_scope: true` and nothing pretends to be per-chip.
- **Consumable date/lot codes are absent.** `SOH32 Genealogy Data Capturing
  Requirement` (Doc 1188783, `PEGA-154`) requires date and lot capture for TIM and
  thermal pads. The linking payload has no field carrying it — needs a request to
  Verna, alongside the `pegapartnumber` addition due 2026-09-01.

Also open: no read-only token yet (authenticates with basic auth — ask Krish for
an `APP_TOKENS` entry), nothing schedules the mirror, and snapshots are not pruned.
