# 2026-W35 — first-pass yield, 2026-08-24 to 2026-08-30

Archived from `dashboard/data/weekly.js` on 2026-09-05. Live page: `week.html#week=2026-W35`.

Rolled first-pass across MLT x HTT: **20.8%**.

| Step | Units | Runs | First pass | After retest | Retest rate | Top failure |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| WST *(reported 2026-08-21)* | — | — | 32.5% | — | — | Annas Javed, Slack — 2 lots completed |
| FT *(reported 2026-08-14)* | — | — | 84.3% | — | — | Sigurd, reported in #production-test-eng |
| TIM | 23 | 36 | 4.3% | 56.5% | 56.5% | validate_coldplate_temperature |
| MLT | 69 | 91 | 65.2% | 68.1% | 23.2% | SohuPowerVirusTestCase |
| HTT | 47 | 55 | 31.9% | 40.4% | 17.0% | SohuLlamaForwardIteratedTestCase |
| L11 Provision | 2 | 22 | 0.0% | 100.0% | 100.0% | ProvisionComputeServer |
| L11 Test | 1 | 4 | 0.0% | 0.0% | 100.0% | L10TestCase |

Excluded from the rolled figure — fewer than 20 first-time units, which is too few to read a yield from: L11 Provision (2 units), L11 Test (1 unit).

## Sources

- Measured rows: pega2, pega6, pega3, pega4, pega5 (ESVM). One row per unit, not one per fixture.
- Attempts numbered over 90 days of history, so a unit returning this week counts as a retest rather than a first pass.
- Reported rows are hand-entered; the source and date are on the row.
- Excluded from this view: vbb_provision.
- 208 unit-level rows kept with this week.
- Built from commit e26c4ff.
