# Which system knows what, and how the three are joined

Written down because the join is not obvious, took a day to establish, and every
number in the rendered YAML depends on it. Verified live on 2026-08-31; re-check
before relying on a claim marked *observed*.

## The three sources

| | `pega-sfis` (TY2 receiver) | EOS test-log API | ESVM controllers |
|---|---|---|---|
| Repo | `etched-ai/ty2-receiver` | — | `~/project/esvm` |
| Owner | Krish Sahdeo | EOS team | test SW |
| Holds | parent↔component graph; route/station events | test runs, per-test results, measurements | slot→unit inside a fixture run |
| Keyed by | serial (`unit_sn`, `parent_sn`, `component_sn`) | `dutSerial` | `suite_run_id` |
| Verdict granularity | `PASS`/`FAIL` per station visit | per test case, per measurement | per unit in a fixture |
| Reachable at | `https://pega-sfis` (Tailnet) | `eos.core.etched.com` (VPN) | `http://pega{2..6}:3000` |
| Auth | bearer read token, basic, or session | `Bearer $EOS_API_KEY` | none on `/api` |

Pegatron's own SFIS has **no query API**. Asked for since April 2026; as of
2026-08-25 it is item 4 on Pegatron's roadmap, TBD. So the receiver is not one
option among several — it is the only way to ask the genealogy a question.

## The join that makes part-level test records possible

*Observed.* EOS files Sohu module tests under the **interposer board barcode**:

```
EOS   level=slt  suite=mlt  dutSerial=JE60702845202602090204
SFIS  parent 268862110000005 (DUB/PV1)  slot BO_0  componenttype BO
      componentname "INTERPOSER BOARD SOHU CHIP"
      componentserialnumber JE60702845202602090204
```

Same string. So the DUT EOS tests **is a part SN in the genealogy**, and the
deepest interesting part in the product gets a first-class test record with a
timestamp, station, software release and verdict. This is what makes the whole
tool work; without it, part-level test history would only ever be inherited.

Cross-check over August 2026, EOS `slt` level against `/api/pairs`:

| | count |
|---|---|
| distinct SLT/MLT DUT serials | 282 |
| present in SFIS genealogy | 233 |
| **absent from SFIS genealogy** | **49** |
| SFIS-linked boards with no August EOS test | 920 of 1153 |

Those 49 are the "no ASIC SN linked in SFIS" class that has been chased by email
one serial at a time since June. `make gaps` produces the list.

## Who carries process events — the rule that shapes the output

*Observed across a live L11 rack and a live 6U.* SFIS `process_events` exist
**only for serials Pega itself issued**. Every vendor barcode returns zero:

| serial | shape | process events |
|---|---|---|
| `268862070001` (rack) | 12 digits, `26…` | 4 (`Assy1`–`Assy4`) |
| `268947020002` (4U node) | 12 digits, `26…` | 7 |
| `268862110000005` (PV1) | 15 digits, `26…` | 12 (SMT, SPI, AOI, X-ray, DIP) |
| `JCS0R8001057` (RMS) | vendor | **0** |
| `JPN2539P58R` (ToR switch) | vendor | **0** |
| `3546300006` (PDU) | vendor | **0** |
| `BR80J1013800059` (converter board) | vendor | **0** |
| `SW5VBJ` (cold plate) | vendor | **0** |

This is not missing data. Pega routes assemblies it serialized; vendor parts are
scanned *in* and never tested by serial. Every rack-level part in the screenshot
that started this work is in the second class — which is why `coverage:
none_expected` had to be a stated verdict and not an empty list.

`graph.is_etched_serial()` encodes the shape: all digits, 12 or 15 characters,
prefix `26`. Widen it there if Etched ever issues a serial outside it.

## Station vocabulary

Three systems, three names for one stage. `stations.py` reconciles them, and the
(level, suite) → station half is **imported from
`Analysis/src/factory/stations.py`** rather than copied — it is verified against
a 30-day live window and already absorbs the renames (`L10_6U_FAT` → `L10_FAT`
at release 220; HTT running under `rdqs_sweep_training`; MLT appearing under
both `module` and `slt`).

`kind` on each record comes from Pega's own `section` field (SMT / DIP / ASSY /
TEST / QC / PACK), not from the station name, because `section` is a small closed
vocabulary Pega controls and station names are free text it renames often —
`Sohu Module Test` and `FBT Sanity Test` are both tests and neither matches a
pattern you would have guessed.

**Known imperfection, left visible on purpose.** Pega files some non-tests under
`section: TEST` — `Replenish PG25` is thermal-paste replenishment on the TIM
cell. `stations.STATION_DEMOTE` lists the ones we have decided about; anything
else stays as Pega sent it, with the station name on every record so a reader can
see. Over-fitting a rule here would quietly reclassify a real gate the next time
the line adds a station.

## What EOS will not tell you

* **No status on `/runs`.** Seven fields, and status is not among them. The
  verdict is only in the `event_stream` artifact (`testRunEnd.status` +
  `.result`) — two extra calls per run, hence `--verdicts` and a permanent
  cache. A record whose verdict was not fetched says `result: unknown`, never a
  guessed `pass`.
* **No station or fixture field at any level.** Station is derived.
* **One run per fixture, eight modules.** An MLT `fail` means at least one of
  eight chips failed. Records inherited from a module-level run therefore carry
  `fixture_scope: true`. Attributing a fixture verdict to a slot needs the ESVM
  controller (`Analysis/src/factory/pega.py` reads
  `GET /api/test_suite_run/<id>` → `participating[{dut_sn, slot_number, status}]`).
* **Never fetch `resource_config`.** Cleartext DUT SSH and BMC credentials, and
  no station identity — nothing to gain, a secret to leak. `eos.NEVER_FETCH`.

## Requirement this serves

`SOH32 Genealogy Data Capturing Requirement` (Doc 1188783 Rev A, Thien Nguyen,
2026-08-19; Jira `PEGA-154`) specifies, for BOM levels 0–5, which of SN / MPN /
Value / Date-Lot must be captured per part, plus quantity and ID/Location. The
rendered YAML is the as-built readback of that spec for one unit: `sn`, `mpn`,
`epn`, `location`, `macs` per part, and `coverage` for the "Value" rows the spec
wants captured against the parent SN.

Not yet covered: **Date/Lot for consumables** (TIM, thermal pads) — the spec
requires it, and the linking payload has no field carrying it. Worth raising with
Verna alongside the `pegapartnumber` addition that shipped 2026-09-01.
