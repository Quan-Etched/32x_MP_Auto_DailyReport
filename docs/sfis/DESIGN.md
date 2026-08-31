# Design notes

Decisions that were not obvious, with the reason. Read `README.md` first for what
the tool does and `JOIN.md` for how the three sources relate.

## Why two phases instead of one command

`mirror` writes an immutable snapshot; `unit` and `gaps` read only the snapshot.
It would be one fewer step to fetch and render in one pass.

Rejected because the tool's reason for existing is the case where fetching does
not work. A one-pass design produces nothing during an outage, which is the exact
moment the answer is needed. It also makes every rendering bug unfixable
retroactively: with a snapshot, a wrong `coverage` rule is re-run against data
already on disk; without one, the data is gone.

The receiver makes the same split internally — immutable payload journal,
rebuildable SQLite index — and states it as its first design property. Matching
it means the two systems fail the same way, which is one failure mode for
somebody to learn instead of two.

## Why parts are keyed by slot and not by serial

Serial looks like the natural key and is wrong three ways:

- **Not unique in the file.** The same vendor barcode can legitimately appear
  under two parents.
- **Not stable.** Replace a part and the serial changes; the slot does not. A
  slot-keyed file diffs into *"`RMS1` serial changed"*, a serial-keyed one into
  *"one key vanished, another appeared"* — the same fact, one of them legible.
- **Not what anyone says.** The line says "RMS1", the receiver enforces one
  active component per (parent, slot) as its load-bearing invariant, and the
  screenshot that started this work is a list of slots.

`part_index` was considered for serial→slot lookup and dropped: `grep` on the
serial already finds the line, and a second index is a second thing to keep
correct.

## Why `coverage` is a stated verdict and not an empty list

Every rack-level part — RMS, ToR, MSW, PDU, manifold, leak sensor, the rack
itself — has zero test records, because Pega tests what it serialized and those
are vendor barcodes. A file that shows `test_records: []` for all 21 of them is
indistinguishable from a file produced by a broken collector, and the difference
costs a day.

So `coverage: none_expected` says *nothing tests this by serial, and that is
correct*. `inherited_only` says *nothing tests it, but here is what it was inside
when that was tested*. The reader never has to guess which they are looking at.

## Why `traceability_gap` is a separate flag

It began as a fifth `coverage` value and that was a bug. An Etched-serialized
part with no route history is an escape **whether or not** its parent happened to
be tested while it was installed — and when the parent was, the part came out
`inherited_only` and read as fine. Coverage answers *what evidence exists*; the
flag answers *should there have been more*. Different questions, different
fields. `tests/test_graph.py::test_serialized_part_with_no_route_history_is_flagged_even_when_covered`
is the regression.

## Why inheritance is bounded by the edge window

A cold plate has no test of its own; the useful evidence is what its module
passed while the plate was in it. Unbounded, that becomes "every test the module
ever ran", including the ones after the plate was swapped out — a wrong answer
that looks thorough, which is worse than no answer. So inheritance is bounded by
`[valid_from, valid_to)` from the genealogy edge, and only records whose `kind` is
`test` are inherited at all: a parent's assembly scan says nothing about its
child.

## Why `kind` comes from Pega's `section`, not the station name

`section` is a small closed vocabulary Pega controls (SMT, DIP, ASSY, TEST, QC,
PACK). Station names are free text it renames often, and the two real test
stations on the module line — `Sohu Module Test` and `FBT Sanity Test` — match no
pattern anyone would have guessed in advance.

Pega does file some non-tests under `section: TEST`: `Replenish PG25` is
thermal-paste replenishment. Those live in `stations.STATION_DEMOTE`, a short
explicit list, rather than in a cleverer rule — because the only honest way to
know is to read the station name and decide, and a reader should be able to see
every such decision at once. Anything not on the list stays as Pega sent it, with
the station name on every record.

## Why the station registry is imported from `Analysis` and not copied

The (EOS level, suite) → station mapping is verified against a 30-day live window
and already absorbs three renames. A second copy is stale the first time the line
renames a suite, and nobody would know which copy was right. `make doctor` prints
which registry is live; `stations.FALLBACK` is coarse and exists only so this repo
runs on a box without `Analysis`.

## Why a hand-written YAML emitter

PyYAML is installed here and still the wrong choice, because **serials must never
be emitted unquoted**. Several are digit strings with leading zeros —
`0905260051` (manifold), `0701260010` — and unquoted a YAML reader returns
`905260051`: a serial matching nothing, silently, in the file whose only job is
to record which serial was where. A default dumper cannot be trusted field by
field, so `yamlout.py` quotes every scalar that could be re-read as a number and
guesses nowhere. `tests/test_yamlout.py` round-trips through PyYAML to prove it.

The emitter also gives deterministic insertion order and no anchors, so two
snapshots of the same unit diff cleanly.

## Why transient faults are retried and hard ones are not

A single 30-second timeout on the EOS `slt` sweep dropped every MLT record from a
snapshot: the rendered file lost 8 of 22 tested parts and looked entirely healthy
apart from one line in its manifest. That is the failure this repo is supposed to
prevent, reproduced by the repo itself.

So sweeps and per-serial lookups retry twice on a timeout, DNS blip or 5xx, and
the sweep gets its own 180-second budget because it is a far bigger query than a
lookup. A 401 or 404 is retried never — the answer will not change and a retry
only doubles the time to find out.

And retrying is not enough on its own, so `warnings` puts every degraded source
at the top of the document and echoes it to the terminal. A file that is quietly
incomplete is worse than one that refuses to render.

## Why every failure is a return value, not an exception

`http.get` returns a `Response` with `ok` and `error` and raises for nothing. If a
broken source raised, the tool would die exactly when it is most needed. A graph
that says *"EOS: unavailable"* is usable; a traceback is not.

## What was considered and left out

- **A SQLite index over snapshots.** Would make cross-unit queries ("every unit
  containing a NIC from lot X") fast. Not built: at 155 live units the YAML plus
  `grep` is enough, and an index is a second schema to migrate. Revisit when
  someone actually asks a cross-unit question twice.
- **Rendering the whole factory into one file.** Rejected — the unit is the thing
  people investigate, and one file per unit is what fits in a Slack thread.
- **Deriving 6U/4U/2U here.** The receiver already classifies structurally and
  has a documented history of getting it subtly wrong in ways that took live data
  to find (see its `ARCHITECTURE.md` §6). Taking its answer via `/api/units`
  means one classifier, not two that disagree eventually.
- **Fetching EOS measurements.** `Analysis/src/factory/items.py` already
  extracts ~7,500 measurements per L10 run and documents why limits are not
  available. Duplicating that here would add megabytes per unit to answer a
  question `Analysis` answers better.
