/* dutsearch.js under the DOM stub: a serial's history across the join.
 *
 * The page reads two files. The runs bundle starts at the line's reporting
 * horizon, and everything before it comes from data/unit_history.js — thinner
 * rows, no duration and no per-test detail. What has to hold:
 *
 *   - the earlier attempts appear at all, in order, ahead of the August ones;
 *   - attempt numbers count from the unit's first ever run, not from the
 *     window (the September run of a bonepile board is not attempt 1);
 *   - the station outcome reads the whole sequence, so a pass after July
 *     failures is a retest pass rather than a clean pass;
 *   - an earlier row says what it cannot tell you, instead of showing a blank
 *     failure list that reads as "it failed nothing";
 *   - and with the second file absent the page is exactly what it was.
 *
 * ROOT is set by the driver tests/test_dutsearch_js.py writes.
 */
var ROOT = (typeof ROOT === 'string') ? ROOT : '.';
load(ROOT + '/tests/trace_dom_harness.js');

/* The module reads the bare global, the way a browser provides it. */
var location = { hash: '' };

['dut-input', 'dut-run', 'dut-results', 'dut-output', 'dut-sub',
 'dut-download'].forEach(function (id) { ELEMENTS[id] = new El('div'); });

var DUT = '268086800000021';
var LINKS = {
  pega: {
    urlTemplate: 'http://{host}:3000/suite_run/{run}?slot_number={slot}',
    runTemplateNoSlot: 'http://{host}:3000/suite_run/{run}',
    hosts: { mlt: 'pega3', htt: 'pega3' }
  }
};

/* The collected window: one MLT run on 09-07, which is all the runs bundle
 * has for this board — measured against the published bundle on 2026-09-08. */
function bundle() {
  return {
    stationLabels: { mlt: 'MLT', htt: 'HTT' },
    stationOrder: ['mlt', 'htt'],
    links: LINKS,
    testNames: [], testStatuses: [],
    runs: [{ d: DUT, k: 'mlt', s: 'pass', t: 1788789600, a: 1,
             i: 'mlt_2026.247.0-gitfeb532ed_run_4aa09def#slot2',
             su: 'mlt_2026.247.0-gitfeb532ed', u: 4200, day: '2026-09-07' }]
  };
}

/* Before it: two MLT failures on 07-24 and a pass on 07-28, plus one HTT pass
 * — the shape build_unit_history emits, arrays and all. */
function earlier() {
  return {
    historyFrom: '2026-05-21',
    window: { from: '2026-08-01' },
    stationLabels: { mlt: 'MLT', htt: 'HTT' },
    controllers: { mlt: 'pega3', htt: 'pega3' },
    units: {
      '268086800000021': {
        mlt: [
          ['2026-07-24', 1784906725, 'fail',
           'mlt_2026.205.0-gitaca812f4_run_80db8ef7', 3,
           'mlt_2026.205.0-gitaca812f4'],
          ['2026-07-24', 1784910638, 'fail',
           'mlt_2026.205.0-gitaca812f4_run_5cfd56da', 3,
           'mlt_2026.205.0-gitaca812f4'],
          ['2026-07-28', 1785210365, 'pass',
           'mlt_2026.205.0-gitaca812f4_run_a7c5f1f8', 6,
           'mlt_2026.205.0-gitaca812f4']
        ],
        htt: [
          ['2026-07-28', 1785216836, 'pass', 'htt_20260724_run_ef7ddc2f', 1,
           'htt_20260724']
        ]
      }
    }
  };
}

/* Driven through the shareable link the page already supports — `#dut=SN`
 * sets the serials and runs the search in init(). No test-only hook, and it
 * exercises the path somebody uses when they paste a serial URL to a
 * colleague, which is most of why this view exists. */
El.prototype.removeAttribute = function (key) { delete this.attrs[key]; };
El.prototype.hasAttribute = function (key) {
  return Object.prototype.hasOwnProperty.call(this.attrs, key);
};

function search(withEarlier) {
  window.__FACTORY_RUNS__ = bundle();
  window.__FACTORY_UNIT_HISTORY__ = withEarlier ? earlier() : undefined;
  window.FactoryBigData = { ensure: function (fn) { fn(); } };
  window.FactoryCsv = {
    attach: function (host, options) { window.FactoryCsv.opts = options; },
    toCsv: function (rows) { return rows; },
    download: function () {}
  };
  location.hash = '#dut=' + DUT;
  ELEMENTS['dut-results'].innerHTML = '';
  ELEMENTS['dut-input'] = new El('textarea');
  load(ROOT + '/dashboard/dutsearch.js');
  return ELEMENTS['dut-results'];
}

/* --- with both halves ---------------------------------------------------- */

var host = search(true);
var card = host.children[0];
assert(card, 'a card for the serial');

var text = card.text();
assert(text.indexOf('2026-07-24') !== -1,
       'the July attempts reach the page: ' + text.slice(0, 200));
assert(text.indexOf('4 attempts before 2026-08-01') !== -1,
       'and the head counts them, across stations: ' + text.slice(0, 200));

/* The table body: four MLT rows and one HTT row, oldest first. */
var table = card.children.filter(function (kid) {
  return kid.tagName === 'div' && kid.text().indexOf('Station') !== -1;
})[0];
var body = null;
(function find(node) {
  if (node.tagName === 'tbody') { body = node; return; }
  node.children.forEach(find);
})(card);
assert(body && body.children.length === 5,
       'five attempts in one timeline, got ' + (body ? body.children.length : 0));

var days = body.children.map(function (tr) { return tr.children[4].textContent; });
assert(days[0].indexOf('2026-07-24') === 0 && days[4].indexOf('2026-09-07') === 0,
       'oldest first, across the join: ' + days.join(' | '));

/* Attempt numbers, per station, counted from the first ever run. */
var attempts = body.children.map(function (tr) {
  return tr.children[0].textContent + ':' + tr.children[3].textContent;
});
assert(attempts[4] === '5:4',
       'the September MLT run is that unit’s fourth attempt at MLT, not '
       + 'its first: got ' + attempts.join(' | '));

/* The row from the thinner source says so, rather than showing an empty
   failure list that reads as a clean run. */
var early = body.children[0];
assert((early.className || '').indexOf('dut-early') !== -1,
       'the earlier row is marked: ' + early.className);
assert(early.text().indexOf('not collected') !== -1,
       'and says its per-test detail is not collected: ' + early.text());
var last = body.children[4];
assert((last.className || '').indexOf('dut-early') === -1,
       'the in-window row is not marked');

/* Links work from either side — same template, same host map. */
var hrefs = card.hrefs();
assert(hrefs.filter(function (u) {
  return u.indexOf('run_80db8ef7?slot_number=3') !== -1;
}).length === 1, 'the July run links to its slot: ' + hrefs.join(' '));

/* The station chip reads the whole sequence now. */
assert(text.indexOf('Retest Pass') !== -1,
       'a pass after July failures is a retest pass, not a clean one: '
       + text.slice(0, 300));

/* One sentence per card, carrying the dates rather than a vague caveat. */
assert(text.indexOf('the day the collected window starts') !== -1,
       'the card explains the join');
assert(text.indexOf('2026-05-21') !== -1, 'and how far back it reaches');

/* The CSV says which side a row came from — it is the thing people forward. */
var lines = window.FactoryCsv.opts.rows();
assert(lines[0][lines[0].length - 1] === 'Source',
       'a Source column: ' + lines[0].join(','));
assert(/run index/.test(lines[1][lines[1].length - 1]),
       'the July row names the run index: ' + lines[1].join(','));
assert(lines[5][lines[5].length - 1] === 'runs bundle',
       'the September row names the runs bundle: ' + lines[5].join(','));
assert(lines[1][9] === '', 'and carries no duration it does not have');

/* --- with the second file absent ----------------------------------------- */

var host2 = search(false);
var only = host2.children[0];
var body2 = null;
(function find(node) {
  if (node.tagName === 'tbody') { body2 = node; return; }
  node.children.forEach(find);
})(only);
assert(body2 && body2.children.length === 1,
       'without the file, the page is what it always was: '
       + (body2 ? body2.children.length : 0) + ' row');
assert(only.text().indexOf('before 2026-08-01') === -1,
       'and claims nothing about a history it cannot see');

print(LOG.join('\n'));
print(LOG.failed ? 'dutsearch.js: FAILURES'
                 : 'dutsearch.js: ok (' + LOG.length + ' assertions)');
