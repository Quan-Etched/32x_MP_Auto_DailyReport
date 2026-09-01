/* bigdata.js under the DOM stub: the two-phase load, and the promises it makes.
 *
 * ROOT is set by the driver tests/test_bigdata_js.py writes.
 */
var ROOT = (typeof ROOT === 'string') ? ROOT : '.';
load(ROOT + '/tests/trace_dom_harness.js');

/* --- a light bundle, exactly the shape build_runs.write_light_bundle emits -- */
var HEAVY_RUNS = [];
var HEAVY_NAMES = [];
for (var i = 0; i < 40000; i++) {           // enough to blow an unchunked push
  if (i < 500) HEAVY_RUNS.push({ i: 'run' + i, d: 'SN' + i, k: 'mlt', s: 'pass' });
  HEAVY_NAMES.push('test_name_' + i);
}
var FULL_TEXT = 'window.__FACTORY_RUNS__ = ' +
  JSON.stringify({ runs: HEAVY_RUNS, testNames: HEAVY_NAMES }) + ';\n';

window.__FACTORY_RUNS__ = {
  stationLabels: { mlt: 'MLT' }, stationOrder: ['mlt'],
  runs: [], testNames: [],
  full: { path: 'runs_pega.js', bytes: FULL_TEXT.length,
          counts: { runs: 500, testNames: 40000 }, keys: ['runs', 'testNames'] }
};

/* The consumers capture their reference at load and never look again. That is
 * the whole reason the fill has to be in place. */
var CONSUMER_RUNS = window.__FACTORY_RUNS__.runs;
var CONSUMER_NAMES = window.__FACTORY_RUNS__.testNames;

/* --- a fetch that streams, so the progress path is the one under test ------ */
var fetchCalls = 0;
var HEADERS = { 'Content-Length': String(FULL_TEXT.length) };
function makeResponse() {
  var sent = false;
  return {
    ok: true, status: 200,
    headers: { get: function (k) { return HEADERS[k] || null; } },
    body: { getReader: function () {
      return { read: function () {
        if (sent) return Promise.resolve({ done: true });
        sent = true;
        var bytes = [];
        for (var i = 0; i < FULL_TEXT.length; i++) bytes.push(FULL_TEXT.charCodeAt(i));
        return Promise.resolve({ done: false, value: bytes });
      } };
    } },
    text: function () { return Promise.resolve(FULL_TEXT); }
  };
}
var fetchUrl = '';
function fetch(url) { fetchCalls++; fetchUrl = url; return Promise.resolve(makeResponse()); }
function TextDecoder() {
  this.decode = function (chunk) {
    if (!chunk) return '';
    var out = '';
    for (var i = 0; i < chunk.length; i++) out += String.fromCharCode(chunk[i]);
    return out;
  };
}

load(ROOT + '/dashboard/bigdata.js');
var BD = window.FactoryBigData;

assert(BD.needed(), 'reports the heavy half is not loaded yet');
assert(BD.state().phase === 'absent', 'starts absent, not loading');
assert(BD.state().total === FULL_TEXT.length, 'knows the size before fetching');

var link = BD.downloadLink();
assert(link && link.attrs.href === 'data/runs_pega.js', 'download link points at the raw file');
assert(link.attrs.download === 'runs_pega.js', 'download link is a download, not a navigation');

var done = 0, alsoDone = 0;
BD.ensure(function () { done++; });
BD.ensure(function () { alsoDone++; });   // a second caller must not refetch

after(40, function () {
  assert(fetchCalls === 1, 'one fetch for two callers, got ' + fetchCalls);
  assert(fetchUrl === 'data/runs_pega.js', 'fetched the path the light bundle named');
  assert(done === 1 && alsoDone === 1, 'every waiting caller was told');
  assert(BD.state().phase === 'ready', 'ends ready, got ' + BD.state().phase);
  assert(!BD.needed(), 'no longer needed once loaded');

  /* The load-bearing assertion: the arrays the consumers captured are the arrays
   * that got filled. */
  assert(CONSUMER_RUNS.length === 500,
         'runs filled in place: ' + CONSUMER_RUNS.length);
  assert(CONSUMER_NAMES.length === 40000,
         'testNames filled in place (chunked, no stack blowup): ' + CONSUMER_NAMES.length);
  assert(CONSUMER_RUNS === window.__FACTORY_RUNS__.runs,
         'and it is still the same array object, not a replacement');
  assert(CONSUMER_NAMES[39999] === 'test_name_39999', 'last chunk landed intact');

  /* --- a re-encoded body must not produce a bar that sails past 100% ------ */
  HEADERS['Content-Encoding'] = 'gzip';
  window.__FACTORY_RUNS__ = {
    runs: [], testNames: [],
    full: { path: 'runs_pega.js', bytes: 999, counts: { runs: 0, testNames: 0 },
            keys: ['runs', 'testNames'] }
  };
  load(ROOT + '/dashboard/bigdata.js');
  window.FactoryBigData.ensure(function () {});
  return after(40, function () {
    assert(window.FactoryBigData.state().total === 0,
           'no percentage claimed when the body was re-encoded under us');
    print(LOG.join('\n'));
    print(LOG.failed ? 'bigdata.js: FAILURES' : 'bigdata.js: ok (' + LOG.length + ' assertions)');
  });
});
