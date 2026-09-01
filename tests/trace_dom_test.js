/* ROOT and BUNDLE are set by the driver tests/test_trace_js.py writes, so this
 * runs against a bundle built for the test rather than only against whatever
 * `make sfis-dashboard` last produced. */
var ROOT = (typeof ROOT === 'string') ? ROOT : '.';
var BUNDLE = (typeof BUNDLE === 'string') ? BUNDLE : ROOT + '/dashboard/data/trace.js';

load(ROOT + '/tests/trace_dom_harness.js');

/* The bundle the page would have loaded, shaped by build_trace.py. */
var raw = readFile(BUNDLE);
eval(raw.replace(/^[^{]*window\.__FACTORY_TRACE__\s*=\s*/, 'var TRACE = ').replace(/;\s*$/, ''));

/* The bundle on disk is the INDEX: nodes live in trace/<unit>.json and the page
 * fetches the one unit it is showing. jsc has no fetch, so the loaded state is
 * assembled here -- index plus that unit's nodes merged in, which is exactly
 * what the page holds once ensureUnit resolves. */
TRACE.nodes = TRACE.nodes || {};
(TRACE.units || []).forEach(function (u) {
  var dir = BUNDLE.replace(/\/[^\/]+$/, '') + '/trace/' + u.sn + '.json';
  var payload = JSON.parse(readFile(dir));
  Object.keys(payload.nodes).forEach(function (sn) { TRACE.nodes[sn] = payload.nodes[sn]; });
});
window.__FACTORY_TRACE__ = TRACE;

var UNIT = TRACE.units[0].sn;
var pv1 = null, sohu = null;
Object.keys(TRACE.nodes).forEach(function (sn) {
  var n = TRACE.nodes[sn];
  if (n.t === 'DUB' && !pv1) pv1 = sn;
  if (n.t === 'BO' && n.n && n.n.indexOf('INTERPOSER') === 0 && !sohu) sohu = sn;
});

/* --- renders before the run bundle has arrived -------------------------- */
/* customize.html loads this module BEFORE data/runs_pega.js (9.5 MB, blocking,
 * minutes on the VPN), so the first render must stand on the trace bundle
 * alone -- and must say the controller rows are still coming rather than let
 * their absence read as "there are none". */
window.__FACTORY_RUNS__ = {};
load(ROOT + '/dashboard/trace.js');
var firstUnit = TRACE.units[0].sn;
window.location.hash = 'trace=' + firstUnit;
listeners.hashchange();
var early = TRACE_HOST.text();
assert(early.indexOf('Traceability') >= 0, 'renders with no run bundle loaded');
assert(early.indexOf('Still loading the controller run bundle') >= 0,
       'says the controller rows are still coming');

/* Controller runs, as customize.html has them in memory. Injected against the
 * node actually under test rather than a hardcoded serial -- pinning a serial
 * here made the assertion pass or fail on bundle key order, which is not what
 * it is meant to be testing. Encoded the way pega_collect encodes unit N of a
 * fixture, because turning that back into a slot_number query is the thing
 * being checked. */
window.__FACTORY_RUNS__ = {
  stationLabels: { mlt: 'MLT', tim: 'TIM' },
  runs: [{ d: pv1, k: 'mlt', s: 'fail', t: 1787000000,
           i: 'mlt_validation_2026.243.0-git1e4d1b5f_run_9d9abf93#slot5',
           v: '2026.243.0' }]
};

/* --- a unit renders its path and its parts ------------------------------- */
window.location.hash = 'mode=dut&trace=' + UNIT;
listeners.hashchange();
var text = TRACE_HOST.text();
assert(text.indexOf('Traceability') >= 0, 'renders the card');
assert(text.indexOf(UNIT) >= 0, 'names the unit');
assert(text.indexOf('Parts under it') >= 0, 'lists children');

/* --- a mid-tree part shows the chain UP to the unit ---------------------- */
window.location.hash = 'mode=dut&trace=' + pv1;
listeners.hashchange();
text = TRACE_HOST.text();
var hrefs = TRACE_HOST.hrefs().join(' ');
assert(text.indexOf(pv1) >= 0, 'names the searched part');
assert(text.indexOf(TRACE.nodes[pv1].u) >= 0, 'path climbs to the top-level unit');
assert(text.indexOf('Test records') >= 0, 'shows a record table');

/* The controller join, which the bundle cannot do: a run loaded by the page,
 * turned into the one per-run deep link that exists. */
assert(text.indexOf('controller') >= 0, 'controller records joined from the page bundle');
assert(hrefs.indexOf('pega3:3000/suite_run/mlt_validation_2026.243.0-git1e4d1b5f_run_9d9abf93') >= 0,
       'suite_run deep link built from stationKey -> controller');
assert(hrefs.indexOf('slot_number=5') >= 0, '#slot suffix becomes the slot_number query');
assert(hrefs.indexOf('pega-sfis/lookup?sn=' + pv1) >= 0, 'by-serial SFIS link');
assert(hrefs.indexOf('splm.i.etched.com/tests/runs?q=' + pv1) >= 0, 'by-serial SPLM link');

/* --- the interposer: EOS files MLT under this barcode ------------------- */
if (sohu) {
  window.location.hash = 'mode=dut&trace=' + sohu;
  listeners.hashchange();
  text = TRACE_HOST.text();
  assert(text.indexOf('INTERPOSER') >= 0, 'interposer named');
  assert(text.indexOf('eos') >= 0, 'EOS record shown on the part SN it names');
}

/* --- a serial that was never mirrored ----------------------------------- */
window.location.hash = 'mode=dut&trace=ZZ_NOT_MIRRORED_1';
listeners.hashchange();
text = TRACE_HOST.text();
hrefs = TRACE_HOST.hrefs().join(' ');
assert(text.indexOf('not in the traceability snapshot') >= 0,
       'unmirrored serial says so instead of rendering an empty tree');
assert(hrefs.indexOf('pega-sfis/lookup?sn=ZZ_NOT_MIRRORED_1') >= 0,
       'and still offers the searches, which resolve regardless');

/* --- falls back to the serial dutsearch is showing ---------------------- */
window.location.hash = 'mode=dut&dut=' + pv1;
listeners.hashchange();
assert(TRACE_HOST.text().indexOf(pv1) >= 0, 'picks up #dut= with no #trace=');

/* --- and the case that actually happens: the serial is only in the box ----
 * dutsearch READS `dut=` from the hash but never writes it, so typing a serial
 * and pressing SEARCH leaves the address bar at `#mode=dut`. Reading the hash
 * alone meant the card silently never appeared for the normal way of using the
 * page -- which is exactly how it was reported. */
var box = new El('textarea');
box.value = UNIT + '\n';
ELEMENTS['dut-input'] = box;
window.location.hash = 'mode=dut';
listeners.hashchange();
var boxText = TRACE_HOST.text();
assert(boxText.indexOf(UNIT) >= 0,
       'reads the serial out of #dut-input when the hash has none');
assert(boxText.indexOf('Parts under it') >= 0, 'and renders its tree');

/* An explicit #trace= must still win over whatever is in the box. */
window.location.hash = 'mode=dut&trace=' + pv1;
listeners.hashchange();
assert(TRACE_HOST.text().indexOf(pv1) >= 0, 'an explicit #trace= wins over the box');

/* Nothing anywhere: no card, and no crash. */
box.value = '';
window.location.hash = 'mode=dut';
listeners.hashchange();
assert(TRACE_HOST.text().trim() === '', 'no serial anywhere renders nothing');

print(LOG.join('\n'));
print(LOG.failed ? 'trace.js: FAILURES' : 'trace.js: ok (' + LOG.length + ' assertions)');
