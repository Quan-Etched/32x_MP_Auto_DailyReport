# errors/knowledge/ — the error-code knowledge base

One file per failure mode: what we have established about it, what we did, and who
owns it. Committed, reviewed, and read by the build. `SCHEMA.md` is authoritative for
the prose rules; `_schema.json` is the same contract in the form the validator reads.

## Why one file per code

A change of opinion should be a one-file diff with an author. `errors/annotations.json`
works as a single file today only because it is empty; the moment three people are
recording root causes in it, every edit conflicts. Splitting by code also means a
reviewer can be asked about `TH-HBM-0006` and nothing else.

There is no index file. The build globs the directory, so there is nothing to keep in
sync and no way for the index to disagree with what is on disk.

## File naming

| Case | Filename |
|---|---|
| A failure mode with an allocated code | `<CODE>.json`, e.g. `TH-HBM-0006.json` |
| A failure mode with no code yet | `case-<TestCaseName>.json`, e.g. `case-PcieSetupTestCase.json` |
| Not data | anything starting with `_` — never loaded |

The second row is not an edge case. In the first MLT/HTT incident window, 4 of 11
failing test cases had no allocated code, and production names failures by test case
rather than by code. A knowledge base that could only describe coded failures would be
unable to record most of what the line actually hits.

`<CODE>` is the **base** form — `TH-<BLOCK>-<NNNN>` with any `-S<x>Q<y>` severity and
quick-action suffix stripped, the same key `32x-error-code`'s `base_and_flags()` uses.
The filename must match the `code` field.

## Shape

    {
      "_comment":     [str],        optional, the repo's idiom for in-file notes
      "schemaVersion": 1,           required
      "code":          str | null,  required key; null when no code is allocated
      "appliesTo": {
        "cases":     [str],         required, at least one
        "stations":  [str]          optional, station keys as in factory.stations
      },
      "owner":         str,         optional
      "rootCauses":   [rootCause],  required, may be empty
      "updatedAt":     str,         required, ISO 8601
      "updatedBy":     str          required
    }

    rootCause {
      "id":                str,     required, unique in file, kebab-case
      "team":              enum,    required — Test | Infra | Firmware | Platform
      "confidence":        enum,    required — suspected | confirmed
      "statement":         str,     required, non-empty
      "firstSeen":         str,     optional, YYYY-MM-DD
      "evidence":         [ev],     required, at least one
      "correctiveActions":[ca]      required, may be empty
    }

    correctiveAction {
      "id":        str,             required, unique in file
      "action":    str,             required
      "kind":      enum,            required — process|rework|firmware|fixture|software|none
      "state":     enum,            required — proposed | applied | reverted
      "appliedAt": str | null,      required key; ISO 8601 or null
      "scope":     {"kind": enum, "value": str},
                                    required — fleet|station|build|dut
      "owner":     str,             optional
      "ref":       str,             optional, Jira key
      "evidence":  [ev]             optional
    }

    ev {
      "source": enum,               required — slack|jira|fi|drive|log|run|doc
      "url":    str,                required
      "who":    str,                optional
      "at":     str,                optional, ISO 8601
      "quote":  str                 optional
    }

## The enums, and why they are short

**`team`** is exactly four values, and there is no `Unknown`.

| Value | Means |
|---|---|
| `Test` | the test caused it — seating, a mis-trained step, a part not powered, a harness expectation that does not match the unit |
| `Infra` | the surrounding systems — network, IP setup, a proxy that never came up, a service unreachable |
| `Firmware` | a firmware defect |
| `Platform` | an EE / hardware defect |

`team` sits on the **root cause**, not on the code. A code reading `Test` on one
occasion and `Firmware` on another means there are two root causes, which is two
entries in `rootCauses`. There is no `Unknown` for the same reason `established.json`
has exactly two values for its own `rootCause`: a fifth value immediately becomes
somewhere to park uncertainty. If you cannot name the team, you do not yet have a root
cause — leave `rootCauses` empty and record the evidence.

**`confidence`** is `suspected` or `confirmed`, because things get written down as soon
as somebody can articulate them, which is before they are proven. Two values, so
"mostly sure" has nowhere to hide.

**`scope`** decides which occurrences count toward Post-CA. Without it, a fixture fix at
MLT looks ineffective because HTT keeps failing. `{"kind": "fleet", "value": ""}` is
the everything case.

## Rules

1. **Post-CA is never in this file.** It is derived at build time from `appliedAt`
   against the run stream. A stored effectiveness field would be typed once and then be
   wrong for six months. This is the single most important rule here.

2. **`appliedAt` may be `null`, and that is honest.** A corrective action nobody has
   dated yields the verdict `not-evaluable`, which is a true statement. Omitting the key
   entirely is a validation error; setting it to `null` is not.

3. **Fidelity of evidence.** `quote` records what a human actually wrote at the source —
   it quotes or paraphrases, it does not infer. A field that was not stated at the source
   is omitted rather than guessed, including `who` and `at`. Record a permalink only when
   you actually captured one. This rule is carried over from `32x-error-code`'s
   `incidents.yaml`, and it is what makes the page checkable against its sources.

4. **Every serial is a JSON string, never a number.** Serials in this product are digit
   strings and several carry leading zeros — `0905260051` read as an integer comes back
   as `905260051`, a serial that matches nothing, silently. Same rule, and same reason,
   as `src/shopfloor/yamlout.py`.

5. **A malformed file is named and refused, never skipped.** The loader reports the file
   and the field. A knowledge base that quietly dropped the file it could not parse would
   report the line as having no known root causes, which is the failure mode this whole
   repo is built to avoid.

6. **JSON, not YAML.** This repo is stdlib-only so it runs unattended on a factory host
   with no package install. `_comment` arrays are how notes live in a data file here —
   see `errors/established.json`.

## How Post-CA is computed

For each corrective action with an `appliedAt`, over the window the reader selected:

- **Rate, not count.** Occurrences ÷ runs in scope. Raw counts fall whenever the line
  slows down, which would score every fix as effective during a quiet week.
- **Before** is the 14 days ending at `appliedAt`. **After** is `appliedAt` to the end of
  the selected window.
- **Exposure gate.** Below the minimum in-scope runs after the date, the verdict is
  `insufficient` — never `effective`. A fix nobody has tested is not a fix that worked.

| Verdict | Condition |
|---|---|
| `not-evaluable` | no `appliedAt`, or `state` is `proposed` |
| `insufficient` | fewer than `MIN_RUNS_AFTER` in-scope runs since |
| `ineffective` | after-rate > 60% of before-rate |
| `partial` | after-rate between 20% and 60% of before-rate |
| `effective` | after-rate ≤ 20% of before-rate |

Thresholds live in one constant block in `src/factory/postca.py` and are printed on the
page, so a reader can disagree with them without reading the source.

## Resolving a failure to a knowledge file

Production records a test case; this base is keyed on codes. The lookup order:

1. The occurrence carries a uniquely pinned code → that code's file.
2. Otherwise, every file whose `appliesTo.cases` contains the test case. Several may
   match, and they are shown as **candidates** — never auto-picked. 125 of 177 test cases
   in the catalogue map to more than one code, because the code says *how* a case failed
   and the tracker records only that it did.
3. Nothing matches → the occurrence lands in the `unresolved` bucket, which stays visible
   on the page. It is the more interesting finding.
