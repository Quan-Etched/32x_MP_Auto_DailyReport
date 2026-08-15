# First-pass yield, 2026-08-09 to 2026-08-15

Archived from `dashboard/data/fpy.js` on 2026-08-15.

Rolled first-pass across VBB Provisioning x MLT x HTT: **28.1%**.

| Step | Units | Runs | First pass | After retest | Retest load | Top failure |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| WST *(reported 2026-08-14)* | — | — | 35.3% | — | — | Sigurd, reported in #production-test-eng |
| FT *(reported 2026-08-14)* | — | — | 84.3% | — | — | Sigurd, reported in #production-test-eng |
| VBB Provisioning | 25 | 68 | 79.2% | 100.0% | — | LcusDisable |
| MLT | 228 | 279 | 65.5% | 74.6% | 19.7% | SohuPowerVirusTestCase |
| HTT | 170 | 234 | 54.3% | 68.8% | 27.6% | SohuRdqsSweepTrainingTestCase |
| L10 FAT | 2 | 15 | 0.0% | 50.0% | 100.0% | SohuHostRebootTestCase |
| L10 SFT | 1 | 6 | — | 0.0% | 100.0% | SohuLlama70bHp8ForwardIteratedTestCase |
| L10 RIN | 1 | 4 | 100.0% | 100.0% | 100.0% | RunInStress |
| L10 2U | 3 | 19 | 0.0% | 33.3% | 66.7% | BmcCheck |
| L11 Test | 2 | 16 | 0.0% | 50.0% | 100.0% | CheckSohuServerNoErrorLogTestCase |

Excluded from the rolled figure — fewer than 20 first-time units, which is too few to read a yield from: L10 FAT (2 units), L10 SFT (1 unit), L10 RIN (1 unit), L10 2U (3 units), L11 Test (2 units).

## Sources

- Measured rows: pega2 – pega5 (ESVM). One row per unit, not one per fixture.
- Attempts numbered over 30 days of history, so a unit returning this week counts as a retest rather than a first pass.
- Reported rows are hand-entered; the source and date are on the row.
- Built from commit a1ce804.
