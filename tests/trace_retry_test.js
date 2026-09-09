/* dashboard/trace.js: a cached failure must not be permanent.
 *
 * THE BUG THIS EXISTS FOR
 * Both trace fetches asked for `cache: 'force-cache'`, which is right for the
 * happy path — the bundle is 736 KB and immutable for the life of a snapshot,
 * and re-downloading it on every search would be absurd. But force-cache reuses
 * a stored *error* with exactly the same enthusiasm and never revalidates, so
 * one 404 — from a moment before the trace bundle was published, or a
 * connection that dropped — pinned that reader to "HTTP 404" for ever, for a
 * file the server was returning 200 for to everybody else. Reported on
 * 2026-09-03 for 268633790001, whose file was present and identical to the 743
 * that worked; the whole cross-check of index against disk came back clean.
 *
 * Nothing on the page could clear it. Only a hard reload, which nobody guesses.
 */
var ROOT = (typeof ROOT === 'string') ? ROOT : '.';

load(ROOT + '/tests/trace_dom_harness.js');

/* A small but structurally real bundle: index, units, unitPath. */
var BUNDLE_TEXT = 'window.__FACTORY_TRACE__ = ' + JSON.stringify({
  schemaVersion: 1,
  snapshot: { id: 'TESTSNAP' },
  unitPath: 'trace/{sn}.json',
  units: [{ sn: '268633790001' }],
  index: { '268633790001': '268633790001' },
  nodeKeys: {}, stationLabels: {}, linkTemplates: {}, controllers: {},
  recordFields: [], warnings: []
}) + ';';

var UNIT_TEXT = JSON.stringify({
  nodes: { '268633790001': { u: '268633790001', k: [], t: 'UNIT', n: 'unit' } }
});

/* ------------------------------------------------------------ fetch stub */

var calls = [];            /* {url, cache} in order */
var plan = {};             /* url -> array of responses to hand out in turn */

function respond(body) {
  return {
    ok: true, status: 200,
    text: function () { return Promise.resolve(body); },
    json: function () { return Promise.resolve(JSON.parse(body)); }
  };
}
function notFound() {
  return { ok: false, status: 404,
           text: function () { return Promise.resolve(''); },
           json: function () { return Promise.resolve({}); } };
}

var fetch = function (url, opts) {
  var mode = (opts && opts.cache) || 'default';
  calls.push({ url: url, cache: mode });
  var queued = plan[url];
  var next = (queued && queued.length) ? queued.shift() : notFound();
  return Promise.resolve(next);
};

/* The page: a serial in the box, no bundle preloaded. */
ELEMENTS['dut-input'] = new El('textarea');
ELEMENTS['dut-input'].value = '268633790001';
window.location.hash = '#mode=dut&dut=268633790001';
window.__FACTORY_TRACE__ = null;

/* THE CASE: the cache holds a 404 for the bundle, the network has it. */
plan['data/trace.js'] = [notFound(), respond(BUNDLE_TEXT)];
plan['data/trace/268633790001.json'] = [notFound(), respond(UNIT_TEXT)];

load(ROOT + '/dashboard/trace.js');

/* trace.js listens for hashchange; firing it is what a search does. */
listeners.hashchange();

after(40, function () {
  var bundleCalls = calls.filter(function (c) { return c.url === 'data/trace.js'; });
  assert(bundleCalls.length === 2,
         'a failed bundle fetch is retried once (got ' + bundleCalls.length + ')');
  assert(bundleCalls[0] && bundleCalls[0].cache === 'force-cache',
         'the first attempt prefers the cache');
  assert(bundleCalls[1] && bundleCalls[1].cache === 'reload',
         'the retry bypasses it with reload, or a cached 404 would be re-read');

  assert(!!window.__FACTORY_TRACE__,
         'the bundle from the retry is adopted');
  assert(window.__FACTORY_TRACE__ &&
         (window.__FACTORY_TRACE__.snapshot || {}).id === 'TESTSNAP',
         'and it is the one the network returned');

  var unitCalls = calls.filter(function (c) {
    return c.url === 'data/trace/268633790001.json';
  });
  assert(unitCalls.length === 2,
         'the per-unit file is retried too — this is the fetch that was ' +
         'reported failing (got ' + unitCalls.length + ')');

  /* THE FAULT THAT ACTUALLY CAUSED THE REPORT. The bundle says
     `unitPath: "trace/{sn}.json"`, meaning beside data/trace.js. fetch()
     resolves against the page, so it asked for /trace/<sn>.json — a 404 —
     while /data/trace/<sn>.json returned 200 to everyone who tried it by
     hand. Every serial, every reader. */
  var wrong = calls.filter(function (c) {
    return c.url.indexOf('trace/') === 0;      /* i.e. missing the data/ */
  });
  assert(wrong.length === 0,
         'the unit file is fetched beside the bundle, not beside the page ' +
         '(asked for: ' + wrong.map(function (c) { return c.url; }).join(', ') + ')');
  assert(unitCalls[1] && unitCalls[1].cache === 'reload',
         'and its retry bypasses the cache as well');

  var text = TRACE_HOST.text();
  assert(text.indexOf('Could not load the genealogy') === -1,
         'no error is shown once the retry succeeded — got: ' +
         text.slice(0, 120));

  /* And a genuinely missing file still reports, rather than retrying for
     ever or going quiet. */
  calls.length = 0;
  plan['data/trace/268633790001.json'] = [];        /* 404 both times */
  window.__FACTORY_TRACE__.nodes = {};
  load(ROOT + '/dashboard/trace.js');
  listeners.hashchange();

  after(40, function () {
    var again = calls.filter(function (c) {
      return c.url === 'data/trace/268633790001.json';
    });
    assert(again.length <= 2,
           'a file that is really absent is tried twice, not endlessly (got ' +
           again.length + ')');
    LOG.forEach(function (line) { print(line); });
    print(LOG.failed ? 'trace-retry: FAIL' : 'trace-retry: ok');
  });
});
