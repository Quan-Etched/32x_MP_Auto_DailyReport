/* weeklysummary.js under the DOM stub: what a cell claims its yield is over.
 *
 * The page is one row per week and the argument it settles is 2026-W36, where
 * MLT published 40% over "90 u" and the rolled column was a dash. Both were
 * right and together they were unreadable: the 40% is over the ten units that
 * were new to MLT that week, and the dash was there because ten and HTT's
 * nineteen are under the twenty-unit floor.
 *
 * The dash is now a number. Asked for on 2026-09-08: a thin step's own yield
 * has published-and-marked for weeks, and withholding their product was read
 * as "the week was not measured" rather than as caution. So the assertions
 * here are about the denominator a cell shows, the mark the product carries,
 * and the one case that is still a dash — a week with only one half.
 *
 * ROOT is set by the driver tests/test_weeklysummary_js.py writes.
 */
var ROOT = (typeof ROOT === 'string') ? ROOT : '.';
load(ROOT + '/tests/trace_dom_harness.js');

['head', 'body', 'caption', 'meta', 'build', 'sources'].forEach(function (id) {
  ELEMENTS[id] = new El(id === 'body' ? 'tbody' : 'div');
});

/* 2026-W36 as the builder emitted it, and W35 beside it for contrast: the same
 * two stages, a week when the units arriving were new. */
window.__FACTORY_WEEKLY__ = {
  minCohort: 20,
  source: { label: 'pega2 – pega5 (ESVM)' },
  build: { commit: 'abc1234' },
  weeks: [
    { week: '2026-W36', from: '2026-08-31', endsOn: '2026-09-06',
      partial: false, hasDetail: true, units: new Array(383),
      rows: [
        { key: 'mlt', label: 'MLT', fpy: 0.4, units: 90, newUnits: 10,
          readable: false, thinCohort: false, countsOnly: false },
        { key: 'htt', label: 'HTT', fpy: 0.7894736842105263, units: 67,
          newUnits: 19, readable: false, thinCohort: false, countsOnly: false },
        { key: 'tim', label: 'TIM', fpy: 0.9090909090909091, units: 11,
          newUnits: 11, readable: false, thinCohort: true, countsOnly: false },
        { key: 'l11_provision', label: 'L11 Provision', fpy: null, units: 3,
          newUnits: 0, readable: false, thinCohort: true, countsOnly: false }
      ],
      totals: { rolledFpy: 0.4 * 0.7894736842105263,
                rolledOver: ['MLT', 'HTT'], minCohort: 20,
                rolledThin: [{ label: 'MLT', newUnits: 10, units: 90 },
                             { label: 'HTT', newUnits: 19, units: 67 }],
                rolledMissing: [] } },
    { week: '2026-W35', from: '2026-08-24', endsOn: '2026-08-30',
      partial: false, hasDetail: true, units: new Array(281),
      rows: [
        { key: 'mlt', label: 'MLT', fpy: 0.6515151515151515, units: 69,
          newUnits: 66, readable: true, thinCohort: false, countsOnly: false },
        { key: 'htt', label: 'HTT', fpy: 0.3191489361702128, units: 47,
          newUnits: 47, readable: true, thinCohort: false, countsOnly: false }
      ],
      totals: { rolledFpy: 0.2079303675048356, rolledOver: ['MLT', 'HTT'],
                minCohort: 20, rolledThin: [], rolledMissing: [] } },
    /* 2026-W31: MLT ran before HTT existed. One station is not a product of
     * two, so this one stays a dash — and says which half is missing. */
    { week: '2026-W31', from: '2026-07-27', endsOn: '2026-08-02',
      partial: false, hasDetail: false, units: [],
      rows: [
        { key: 'mlt', label: 'MLT', fpy: 0.5454545454545454, units: 11,
          newUnits: 11, readable: false, thinCohort: true, countsOnly: false }
      ],
      totals: { rolledFpy: null, rolledOver: [], minCohort: 20,
                rolledThin: [{ label: 'MLT', newUnits: 11, units: 11 }],
                rolledMissing: ['HTT'] } }
  ]
};

load(ROOT + '/dashboard/weeklysummary.js');

var rows = ELEMENTS.body.children;
assert(rows.length === 3, 'a row per week, got ' + rows.length);

/* Cells: week, rolled, then one per step in the order the data introduced
 * them, then the unit-run count. */
var W36 = rows[0].children, W35 = rows[1].children, W31 = rows[2].children;
var rolled36 = W36[1], mlt36 = W36[2], htt36 = W36[3], l11_36 = W36[5];
var rolled35 = W35[1], mlt35 = W35[2];

/* --- the product, published thin ---------------------------------------- */

assert(rolled36.text().indexOf('31.6%') !== -1,
       'W36 publishes 40% x 78.9%: ' + rolled36.text());
assert(rolled36.className.indexOf('thin') !== -1,
       'marked thin, because both its terms are: ' + rolled36.className);
var rolledMark = rolled36.children.filter(function (kid) {
  return kid.attrs['class'] === 'thin-mark';
})[0];
assert(rolledMark, 'the product carries the same star a thin step does');
assert(/10 first-time units/.test(rolledMark.attrs.title || ''),
       'and the star names the cohorts: ' + (rolledMark || {}).attrs);
assert(rolled36.text().indexOf('MLT 10 · HTT 19 new') !== -1,
       'with both denominators under the number: ' + rolled36.text());
assert(/90 unit/.test(rolled36.title) && /10 of them new/.test(rolled36.title),
       'the hover spells out 10 new of 90: ' + rolled36.title);
assert(rolled36.title.indexOf('not measured') === -1,
       'never that nothing was measured — 157 units ran');

assert(rolled35.text().indexOf('20.8%') !== -1,
       'W35 publishes its product: ' + rolled35.text());
assert(rolled35.text().indexOf('new') === -1,
       'and carries no thin line: ' + rolled35.text());
assert(rolled35.className.indexOf('thin') === -1, 'nor a thin class');
assert(/MLT × HTT/.test(rolled35.title),
       'the hover names the scope: ' + rolled35.title);

/* --- the one case that is still a dash ----------------------------------- */

var rolled31 = W31[1];
assert(rolled31.text().indexOf('—') !== -1,
       'W31 has no HTT, so there is no product: ' + rolled31.text());
assert(rolled31.text().indexOf('no HTT') !== -1,
       'and the cell says which half is missing: ' + rolled31.text());
assert(/one station is not a product of two/.test(rolled31.title),
       'with the reason on hover: ' + rolled31.title);
assert(rolled31.text().indexOf('54.5%') === -1,
       'MLT alone is never published under a heading that says MLT x HTT');

/* --- a cell says what its own yield is over ------------------------------ */

assert(mlt36.text().indexOf('40%') !== -1, 'MLT W36 is 40%: ' + mlt36.text());
assert(mlt36.text().indexOf('10 new of 90 u') !== -1,
       'over ten new units of ninety run, said on the cell: ' + mlt36.text());
assert(mlt36.className.indexOf('thin') !== -1,
       'and marked thin, because ten is under the floor: ' + mlt36.className);
var mark = mlt36.children.filter(function (kid) {
  return kid.attrs['class'] === 'thin-mark';
})[0];
assert(mark && /fewer than 20 first-time units/.test(mark.attrs.title),
       'the star explains itself in first-time units');
assert(mark && /stays out of the rolled figure/.test(mark.attrs.title),
       'and connects itself to the dash in the rolled column');

assert(htt36.text().indexOf('19 new of 67 u') !== -1,
       'HTT W36 likewise: ' + htt36.text());
assert(htt36.className.indexOf('thin') !== -1,
       'nineteen misses the floor by one, and says so');

/* W35's MLT is a thick cohort with a couple of returning units in the window:
 * the denominator is still worth printing, and there must be no thin mark. */
assert(mlt35.text().indexOf('66 new of 69 u') !== -1,
       'W35 MLT prints its denominator too: ' + mlt35.text());
assert(mlt35.className.indexOf('thin') === -1,
       'but is not marked thin: ' + mlt35.className);
assert(mlt35.text().indexOf('*') === -1, 'and carries no star');

/* --- a step with nothing on a first run ---------------------------------- */

assert(l11_36.text().indexOf('3 u') !== -1,
       'a step with no first-pass cohort shows its count: ' + l11_36.text());
assert(/No unit was new to this step/.test(l11_36.title),
       'and says that is why there is no yield: ' + l11_36.title);

/* --- the caption teaches the column -------------------------------------- */

var caption = ELEMENTS.caption.textContent;
assert(/first ever run at that step/.test(caption),
       'the caption defines the denominator: ' + caption);
assert(/10 new of 90 u/.test(caption), 'and reads the cell format out');
assert(/fewer than 20 first-time units/.test(caption),
       'and says what the star means');

/* --- a bundle from before the reason was recorded ------------------------ */

/* The page has to keep working against a weekly.js built by the old builder,
 * and — the point — must not turn "I was not told why" into "nothing ran this
 * week", which is the one claim W36 proves false. */
var w36totals = window.__FACTORY_WEEKLY__.weeks[0].totals;
delete w36totals.rolledThin;
delete w36totals.rolledMissing;
ELEMENTS.body.innerHTML = '';
ELEMENTS.head.innerHTML = '';
load(ROOT + '/dashboard/weeklysummary.js');

var old36 = ELEMENTS.body.children[0].children[1];
assert(old36.text().indexOf('31.6%') !== -1,
       'the product still publishes: ' + old36.text());
assert(old36.className.indexOf('thin') === -1,
       'unmarked, because an older bundle never said it was thin');
assert(old36.text().indexOf('new') === -1,
       'and with no counts, because none were published: ' + old36.text());

var old31 = ELEMENTS.body.children[2].children[1];
assert(old31.text().indexOf('—') !== -1, 'still a dash: ' + old31.text());
assert(!/ran this week/.test(old31.title),
       'and never a claim about what ran, with nothing to base it on: '
       + old31.title);

print(LOG.join('\n'));
print(LOG.failed ? 'weeklysummary.js: FAILURES'
                 : 'weeklysummary.js: ok (' + LOG.length + ' assertions)');
