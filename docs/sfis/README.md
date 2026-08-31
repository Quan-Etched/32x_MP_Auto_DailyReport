# 32x-sfis — local shopfloor topology + test-record graph

Mirror `pega-sfis` and EOS to local disk, then render **one YAML per top-level
serial**: the full part-SN tree with every part's test history attached, and an
explicit verdict on which parts can have one at all.

```sh
make sfis-doctor                          # can we reach both sources, with what credential
make sfis-mirror SN=268947020002 VERDICTS=1
make sfis-unit   SN=268947020002          # -> out/268947020002.yaml   (needs no network)
make sfis-gaps   SN=268947020002
```

Python 3.9+, standard library only. No pip install, no build step.

## Why this exists

Two problems, one artifact.

**1. When the shopfloor system is unreachable, there is no second place to ask.**
Pegatron's SFIS has no query API — asked for since April 2026, still TBD on their
roadmap as of 2026-08-25. Everything we can know about the genealogy comes
through Krish's receiver, which is one VM with one SQLite index, and it has
already been down or wrong in ways that cost real work:

- `database disk image is malformed` (SQLite WAL on NFS). Payloads were
  journalled but never indexed, so the API answered *no ASIC SN linked* for a
  board that was linked. Two days of email to establish that.
- Pega read `status: "ok"` with `db.ingested: false` as success and did not
  resend, so payloads were silently absent from the index.
- The VBB flashing station was blocked on 2026-08-03 because SFIS was
  unreachable (`ETCH-36858`).

`snapshots/` is the answer to all three. Rendering reads **only** the snapshot,
so the file still comes out with both hosts down and says on its face how old it
is.

**2. When a system fails, the question is never "what is its serial".** It is
*which parts are in it, what did each one pass, and what else shipped with the
same lot.* That answer is spread across three systems that share no key —
[`docs/JOIN.md`](docs/JOIN.md) is the map, and it is worth reading before this
file.

## What the output looks like

Real output, trimmed. A Sohu module in slot 3 of a 4U node, down to the ASIC
carrier and its MLT record:

```yaml
unit: '268947020002'
summary: {parts: 52, tested: 22, inherited_only: 16, process_only: 12, none_expected: 2}
parts:
  GPUM_3:
    sn: '268862090001'
    type: GPUM
    name: PACER/SOHU MOD/ET
    location: '3'
    linked_at: '2026-08-28T05:26:08.495843Z'
    coverage: tested
    subtree: {inherited_only: 2, process_only: 1, tested: 1}
    test_records:
      - {ts: '2026-08-26T00:58:34Z', station: TIM Dispensing, result: pass, source: sfis, kind: assembly}
      - {ts: '2026-08-26T02:00:07Z', station: TIM Baking,     result: pass, source: sfis, kind: test}
      - {ts: '2026-08-27T07:43:10Z', station: Sohu Module Test, result: pass, source: sfis, kind: test}
    parts:
      Cold_Plate_0:
        sn: SW5VBJ
        mpn: 900-02401
        coverage: inherited_only        # nothing tests a cold plate by serial
        test_records: []
        inherited_records:
          - {ts: '2026-08-27T07:43:10Z', station: Sohu Module Test, result: pass,
             on: '268862090001', via: installed_in}
      DUB_0:
        sn: '268862110000005'           # the PV1
        coverage: process_only
        subtree: {tested: 1}
        test_records:
          - {ts: '2026-08-24T03:56:11Z', station: SMT AOI1, result: pass, kind: fabrication}
        parts:
          BO_0:
            sn: JE60702845202602090204  # the interposer — and the EOS DUT serial
            name: INTERPOSER BOARD SOHU CHIP
            coverage: tested
            test_records:
              - {ts: '2026-08-15T21:46:03Z', station: MLT, result: pass, source: eos,
                 suite: mlt, release: 2026.220.0-git2f1c2f23, level: slt,
                 run_id: mlt_2026.220.0-git2f1c2f23_20260815_214603}
```

Parts are keyed by **slot**, not serial. The receiver enforces one active
component per (parent, slot) — its load-bearing invariant — while the same vendor
barcode can legitimately appear under two parents. Slot-keyed also means a
replacement diffs as *"`RMS1` serial changed"* rather than one key vanishing and
another appearing.

Serials are always quoted. Several are digit strings with leading zeros
(`0905260051`, `0701260010`); unquoted, a YAML reader returns `905260051` — a
serial matching nothing, silently, in the one file whose job is to record which
serial was where. [`yamlout.py`](src/shopfloor/yamlout.py) exists for that
reason and is tested for it.

## The three tiers, and why a part gets the tier it gets

This is the part worth understanding; everything else is plumbing.
[`graph.py`](src/shopfloor/graph.py) is the module.

| `coverage` | meaning |
|---|---|
| `tested` | a test record's own DUT/unit serial **is** this part SN |
| `process_only` | SFIS route or assembly events only — installed, not tested |
| `inherited_only` | no record names it; an **ancestor** was tested while this part was installed, bounded by the edge window `[valid_from, valid_to)` |
| `none_expected` | a vendor part that no station tests by serial, whose ancestors have no tests in the window either |
| `not_observed` | this snapshot never fetched the part, so its own records are **unknown, not empty**. Any `inherited_records` on it are still real. Re-mirror |

`none_expected` is a stated verdict, never an empty list. *Nothing tested this*
and *we failed to look* are different facts, and conflating them costs a day of
a failure investigation. Every rack-level part — RMS, ToR, PDU, manifold — is in
that class; `docs/JOIN.md` has the measurement.

Inheritance is **window-bounded** on purpose. Unbounded, a swapped-out DIMM
would collect the tests that ran after it was removed: a wrong answer that looks
thorough. Only records whose `kind` is `test` are inherited — a parent's assembly
scan says nothing about its child.

`not_observed` exists because a failed lookup and an untested part look
identical, and conflating them made the tool report a traceability escape for a
serial it had merely failed to fetch. Sending Pega a false escape costs their
time and the report's credibility, which is the only thing that makes it useful —
so `traceability_gap` now requires that we actually looked
(`tests/test_graph.py::test_a_failed_lookup_is_not_reported_as_a_traceability_escape`).

`traceability_gap: true` is a **separate flag**, not another coverage value. An
Etched-serialized part with no route history of its own is an escape whether or
not its parent happened to be tested while it was installed. Folding the two
together hid exactly the cases worth finding; there is a regression test for it
(`tests/test_graph.py::test_serialized_part_with_no_route_history_is_flagged_even_when_covered`).

## Two phases, deliberately separate

```
make sfis-mirror  ──► snapshots/<UTC id>/           immutable, never rewritten
                   manifest.json               what answered, how fresh, what scope
                   sfis/serial/<sn>.json       one /api/serial per node in the tree
                   sfis/pairs.json  levels.json  recent.json
                   eos/by_dut.json  levels.json  verdicts.json

make sfis-unit    ──► out/<sn>.yaml                 reads the snapshot ONLY
make sfis-gaps    ──► findings                      reads the snapshot ONLY
```

The split is borrowed from the receiver itself, which separates an immutable
payload journal from a rebuildable SQLite index and says so as its first design
property. This is the same bet one layer out: a bug in `graph.py` is fixable
after the fact against data we already have, and only a snapshot never taken is
unrecoverable.

`make sfis-mirror` fetches `/api/serial/{sn}` for **every node** in the tree, not just
the root. MPN, EPN, MAC and slot confidence are only exposed for a serial's
direct children, so a walk without this yields a tree of bare serials. ~100 calls
per 6U, about 30 seconds, and it is the difference between an inventory and an
attribute graph.

## When a source misbehaves

Sweeps and per-serial lookups retry twice on a timeout, DNS blip or 5xx; a 401 or
404 is retried never, because the answer will not change. This is not
belt-and-braces — an unretried 30-second timeout on the EOS `slt` sweep dropped
every MLT record from a snapshot, and the file lost 8 of its 22 tested parts while
looking entirely healthy apart from one line in its manifest. That is the exact
failure this repo exists to prevent, produced by the repo itself.

Retrying is not enough on its own, so anything still degraded goes in a
`warnings:` list at the top of the document and is echoed to the terminal:

```
! EOS: level(s) bringup, l11 did not answer — test records from those levels
  are missing, not absent
! scope: roots only, no level sweep — cross-source gap checks are limited
```

`bringup` and `l11` return HTTP 424 permanently: the API key cannot read those
buckets. That is a key-permission ask, not a flake, and `Analysis` documents the
same two as `blocked`. Until it is fixed, L11 test records are genuinely
unavailable — and the file says so rather than implying none exist.

## Provenance, on every file

```yaml
sources:
  eos:
    ok: true
    levels: {slt: {ok: true, runs: 1740}, l11: {error: HTTP 424, ok: false}, …}
    window: ['2026-05-03T09:22:42Z', '2026-08-31T09:22:42Z']
  sfis: {base: 'https://pega-sfis', ok: true, serials: 67}
snapshot:
  taken_at: '2026-08-31T09:23:31Z'
  sfis_payloads_through: '2026-08-31T08:26:06.457284Z'
```

Not decoration. The only time anyone opens one of these files is six weeks later
during a failure analysis, and a file that cannot say which sources answered and
how current they were cannot be trusted then. Note `l11: HTTP 424` above — the
key cannot read that bucket, so L11 test records are genuinely absent rather than
nonexistent, and the file says which.

`sfis_scope` records whether a level was swept wholesale. `make sfis-gaps` refuses the
checks its snapshot cannot support: "EOS tested a serial SFIS has never heard of"
is only sound against a complete view of SFIS, and against two mirrored racks it
would "find" that SFIS is missing every serial in the factory.

## `make sfis-gaps`

```
Sohu boards tested by EOS but never linked in SFIS: 328 of 1040 tested
  JE53818840202509170215      1 run(s)  first 2026-06-09T15:05:35Z  slt/Sohu_SLT
  …
Non-production DUTs excluded from the counts above: 7  e.g. 1234, 12345, RENAME_TEST_0
```

`/api/pairs` is a complete view of Sohu boards regardless of what was mirrored,
so this check is sound from any snapshot. It is the "no ASIC SN linked in SFIS"
class in bulk instead of one email at a time. Two caveats before quoting the
number: the older `JE538…`/`JE544…` date codes largely predate the linking
integration, and the count is per the snapshot's EOS window.

## Relationship to the rest of this repo

`src/factory` is the yield and throughput dashboard over EOS: *how is the line
doing*. `src/shopfloor` is this tool: *what is inside this unit, and what
happened to each part of it*. They share the EOS API, the station registry, one
`.env`, and one `make trust`.

That sharing is the reason they live together. Before the merge, `shopfloor`
reached `factory.stations` through a `sys.path` insert into a separate checkout,
with a coarse fallback table for when the checkout was missing. All of it is
gone — the import cannot half-work now:

- **`factory.stations.classify()` / `label_of()`** — the verified (level, suite)
  → station map. One copy, so a suite rename cannot leave a stale second one.
- **`factory.config.ca_bundle()`** — one `make trust` fixes TLS for both tools.
- **`EOS_API_KEY`** — one key in one `.env`, one place to rotate it.

Also worth reading rather than duplicating: `docs/api-usage.md` for the EOS
field-level schema, including the three absences (`/runs` has no status, no
station, no duration) that shape `src/shopfloor/eos.py`; and
`src/factory/pega.py`, the ESVM client, for when fixture verdicts need
attributing to a slot.

## Not done yet

- **Slot attribution for fixture verdicts.** An MLT run covers eight chips; the
  slot→unit mapping is on pega3 (`/api/test_suite_run/<id>` → `participating`).
  Until it is wired, inherited module-level records carry `fixture_scope: true`
  and nothing pretends to be per-chip.
- **Date/lot for consumables.** `SOH32 Genealogy Data Capturing Requirement`
  (Doc 1188783, `PEGA-154`) requires date and lot code for TIM and thermal pads.
  The linking payload has no field carrying it. Needs a request to Verna.
- **SPLM / SiVal** for wafer sort and final test. `Analysis/src/factory/chip_collect.py`
  documents the state: SPLM wants a bearer token we do not have, SiVal prod
  refuses connections. Until one opens, per-die history stops at MLT.
- **A read-only token.** This repo currently authenticates with basic auth. A
  dedicated `APP_TOKENS` entry on the receiver cannot write; ask Krish.
- **Scheduling.** Nothing runs this on a timer yet. A snapshot is only insurance
  if it is taken before the outage. Now that both tools share a repo the obvious
  home is `deploy/` — the same launchd/systemd units that already run
  `make refresh` hourly on the dashboard host, with an `sfis-level` tick beside
  it. That was awkward across two checkouts and is a small change here.
