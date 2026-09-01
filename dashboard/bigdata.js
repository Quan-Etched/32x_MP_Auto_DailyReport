/* The heavy half of the run bundle, fetched when somebody asks for it.
 *
 * WHY
 * `data/runs_pega.js` is 8.6 MB, nginx serves it uncompressed, and over the VPN
 * it arrives at about 42 KB/s — four minutes. As a plain <script src> it blocks
 * the parser for all four, so every script after it waits: the station lists,
 * the result types, the By DUT_SN switch, the nav. A page mid-load is
 * indistinguishable from a page with those features missing, and it was
 * reported as exactly that.
 *
 * So the page now loads `*_light.js` instead — the same object with `runs` and
 * `testNames` left as empty arrays, about 16 KB — and the controls draw at once.
 * This module fetches the rest on demand, with a real progress bar and a real
 * estimate, because four minutes of silence is worse than four minutes with a
 * number on it.
 *
 * THE TRICK THAT KEEPS THE CONSUMERS UNCHANGED
 * customize.js and dutsearch.js both do `var RUNS = DATA.runs || []` at load and
 * hold that reference forever. The light bundle ships a real empty array, so
 * filling it IN PLACE means both of them see the data through the reference they
 * already captured. Neither file had to learn that its data arrives in two
 * phases; each gained one call to `ensure()` in front of the button that needs it.
 *
 * WHAT WOULD MAKE THIS UNNECESSARY
 * gzip. The bundle is JSON and would compress about tenfold, taking the wait
 * from four minutes to twenty-odd seconds for every page and every visitor.
 * nginx here is ansible-managed and serves it with no Content-Encoding at all —
 * checked, not assumed. That is an infra request, not a change to this repo, and
 * it is worth more than everything in this file.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RUNS__ || {};
  var FULL = DATA.full || null;

  var state = {
    /* 'absent'  the light bundle is all there is, and a full file is named
       'loading' bytes are arriving
       'ready'   the heavy keys are filled in
       'failed'  it did not arrive; the reason is in state.error */
    phase: FULL ? 'absent' : 'ready',
    received: 0,
    total: (FULL && FULL.bytes) || 0,
    startedAt: 0,
    error: '',
    hosts: [],
    waiting: []
  };

  function bytes(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1) + ' MB';
    if (n >= 1e3) return Math.round(n / 1e3) + ' KB';
    return n + ' B';
  }

  function seconds(s) {
    if (!isFinite(s) || s < 0) return '';
    if (s < 60) return Math.max(1, Math.round(s)) + 's';
    var m = Math.floor(s / 60);
    return m + 'm ' + Math.round(s - m * 60) + 's';
  }

  function rate() {
    var elapsed = (Date.now() - state.startedAt) / 1000;
    return elapsed > 0.3 ? state.received / elapsed : 0;
  }

  function eta() {
    var r = rate();
    if (!r || !state.total || state.received >= state.total) return '';
    return seconds((state.total - state.received) / r);
  }

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'class') node.className = attrs[k];
      else if (attrs[k] !== null) node.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  /* A link, not a fetch: the browser downloads the file itself, so somebody on a
   * slow link can take the data and skip the render entirely. */
  function downloadLink(label) {
    if (!FULL) return null;
    return el('a', {
      class: 'bd-download', href: 'data/' + FULL.path, download: FULL.path,
      title: 'Download the raw bundle (' + bytes(FULL.bytes) +
             ') without waiting for the page to render it'
    }, [document.createTextNode(label || ('Download raw data · ' + bytes(FULL.bytes)))]);
  }

  function paint() {
    state.hosts.forEach(function (host) {
      host.innerHTML = '';
      if (state.phase === 'ready' || !FULL) return;

      var wrap = el('div', { class: 'bd' });

      if (state.phase === 'absent') {
        wrap.appendChild(el('p', { class: 'bd-note', text:
          'Full data (' + bytes(FULL.bytes) + ', ' +
          FULL.counts.runs.toLocaleString() + ' runs) has not been loaded yet. ' +
          'The controls above work without it; computing results needs it.' }));
      } else if (state.phase === 'loading') {
        var pct = state.total
          ? Math.min(100, Math.round(100 * state.received / state.total)) : null;
        var bar = el('div', { class: 'bd-bar' + (pct === null ? ' bd-bar-idle' : '') }, [
          el('div', { class: 'bd-fill', style: 'width:' + (pct === null ? 100 : pct) + '%' })
        ]);
        wrap.appendChild(bar);
        var left = eta();
        wrap.appendChild(el('p', { class: 'bd-note', text:
          (pct === null ? bytes(state.received) + ' downloaded'
                        : pct + '% · ' + bytes(state.received) + ' of ' + bytes(state.total)) +
          (rate() ? ' · ' + bytes(Math.round(rate())) + '/s' : '') +
          (left ? ' · about ' + left + ' left' : '') }));
      } else if (state.phase === 'failed') {
        wrap.appendChild(el('p', { class: 'bd-note bd-bad', text:
          'Could not load the full data: ' + state.error }));
      }

      var actions = el('div', { class: 'bd-actions' });
      var dl = downloadLink();
      if (dl) actions.appendChild(dl);
      if (state.phase !== 'loading') {
        var go = el('button', { type: 'button', class: 'view-toggle',
                                text: state.phase === 'failed' ? 'Try again'
                                                               : 'Load full data' });
        go.addEventListener('click', function () { ensure(function () {}); });
        actions.appendChild(go);
      }
      wrap.appendChild(actions);
      host.appendChild(wrap);
    });
  }

  /* 135,476 test names go in here. `push.apply(arr, huge)` spreads its argument
   * into the call frame and blows the stack well before that, so it is chunked —
   * a detail that only shows up at production size. */
  function fill(target, source) {
    for (var i = 0; i < source.length; i += 8192) {
      Array.prototype.push.apply(target, source.slice(i, i + 8192));
    }
  }

  function adopt(payload) {
    (FULL.keys || []).forEach(function (key) {
      var into = DATA[key];
      var from = payload[key];
      if (Array.isArray(into) && Array.isArray(from)) fill(into, from);
      else DATA[key] = from;
    });
    state.phase = 'ready';
    paint();
    var waiting = state.waiting.splice(0);
    waiting.forEach(function (fn) { try { fn(); } catch (e) { /* one bad callback
      must not strand the others */ } });
  }

  function parse(text) {
    /* The file is `window.__FACTORY_RUNS__ = {...};` — the same shape the
     * python side writes and the same strip build_trace.py does when it reads a
     * bundle off disk. */
    var open = text.indexOf('{');
    return JSON.parse(text.slice(open).replace(/;\s*$/, ''));
  }

  function ensure(done) {
    if (state.phase === 'ready' || !FULL) { if (done) done(); return; }
    if (done) state.waiting.push(done);
    if (state.phase === 'loading') return;

    state.phase = 'loading';
    state.received = 0;
    state.startedAt = Date.now();
    state.error = '';
    paint();

    fetch('data/' + FULL.path, { cache: 'force-cache' }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var declared = Number(res.headers.get('Content-Length'));
      /* Trust the header only when nothing re-encoded the body underneath us:
       * with Content-Encoding set, the length is of the compressed stream while
       * the reader hands back decompressed bytes, and the bar would sail past
       * 100%. Fall back to a byte count with no percentage, which is honest. */
      if (declared && !res.headers.get('Content-Encoding')) state.total = declared;
      else state.total = 0;

      if (!res.body || !res.body.getReader) return res.text();

      var reader = res.body.getReader();
      var chunks = [];
      var decoder = new TextDecoder();
      var out = '';
      function pump() {
        return reader.read().then(function (step) {
          if (step.done) { out += decoder.decode(); return out; }
          state.received += step.value.length;
          out += decoder.decode(step.value, { stream: true });
          paint();
          return pump();
        });
      }
      return pump();
    }).then(function (text) {
      adopt(parse(text));
    }).catch(function (err) {
      state.phase = 'failed';
      state.error = String(err && err.message ? err.message : err);
      paint();
      var waiting = state.waiting.splice(0);
      waiting.forEach(function (fn) { try { fn(); } catch (e) {} });
    });
  }

  function attach(host) {
    if (!host || state.hosts.indexOf(host) >= 0) return;
    state.hosts.push(host);
    paint();
  }

  window.FactoryBigData = {
    ensure: ensure,
    attach: attach,
    downloadLink: downloadLink,
    /* For tests and for anyone debugging a slow load in the console. */
    state: function () {
      return { phase: state.phase, received: state.received, total: state.total,
               error: state.error, rate: rate(), eta: eta() };
    },
    needed: function () { return !!FULL && state.phase !== 'ready'; }
  };

  /* Self-attach to the conventional container so a page opts in by adding one
     div, not by writing glue. */
  function mount() { attach(document.getElementById('bigdata')); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
