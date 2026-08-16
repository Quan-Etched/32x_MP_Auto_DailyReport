# 2026-W33 — first-pass yield, 2026-08-10 to 2026-08-16 (week still running when archived)

Archived from `dashboard/data/weekly.js` on 2026-08-16. Live page: `week.html#week=2026-W33`.

Rolled first-pass across MLT x HTT: **35.6%**.

| Step | Units | Runs | First pass | After retest | Retest rate | Top failure |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| WST *(reported 2026-08-14)* | — | — | 35.3% | — | — | Sigurd, reported in #production-test-eng |
| FT *(reported 2026-08-14)* | — | — | 84.3% | — | — | Sigurd, reported in #production-test-eng |
| MLT | 228 | 279 | 65.5% | 74.6% | 19.7% | SohuPowerVirusTestCase |
| HTT | 170 | 234 | 54.3% | 68.8% | 27.6% | SohuRdqsSweepTrainingTestCase |
| L10 FAT | 2 | 15 | — | — | — | SohuHostRebootTestCase |
| L10 SFT | 1 | 6 | — | — | — | SohuLlama70bHp8ForwardIteratedTestCase |
| L10 RIN | 1 | 4 | — | — | — | RunInStress |
| L10 2U | 3 | 19 | — | — | — | BmcCheck |
| L11 Test | 2 | 16 | — | — | — | CheckSohuServerNoErrorLogTestCase |

## Sources

- Measured rows: pega2 – pega5 (ESVM). One row per unit, not one per fixture.
- Attempts numbered over 30 days of history, so a unit returning this week counts as a retest rather than a first pass.
- Reported rows are hand-entered; the source and date are on the row.
- Excluded from this view: vbb_provision.
- 573 unit-level rows kept with this week.
- Built from commit 1e2f671.
