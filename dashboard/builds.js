/* New builds and retests.
 *
 * The page exists to answer one question: when a suite is released to fix
 * something and the units pass, were those the units the fix was written on?
 * So every row says whether the unit was new to this station or coming back,
 * and a returning unit carries what it failed last time.
 *
 * The "previously failed" filter is the point of the page rather than a
 * convenience — it is how you get from "225 passes" to "225 passes on units
 * that failed LlamaForwardIterated and were not in the debug set".
 *
 * Plain ES5, no build step, works over file://.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_BUILDS__ || {};
  var ROWS = DATA.rows || [];
  var LIMIT = 400;

  var KIND = {
    'new':          { label: 'New build',   cls: 'k-new' },
    'retest-fail':  { label: 'Retest',      cls: 'k-fail' },
    'retest-pass':  { label: 'Retest',      cls: 'k-pass' }
  };

  var state = { station: null, prior: '', onlyRetest: false };

  /* The filter lives in the URL, as it does on runs.html and the trackers.
   * This page exists to be pasted into a thread — "the units that previously
   * failed LlamaForwardIterated" is the useful thing to send someone, and it
   * is not sendable if it only exists as typing in a text box. */
  function readHash() {
    var hash = (location.hash || '').replace(/^#/, '');
    if (!hash) return;
    hash.split('&').forEach(function (pair) {
      var key = pair.split('=')[0];
      var value = decodeURIComponent(pair.slice(key.length + 1) || '');
      if (key === 'prior') state.prior = value;
      else if (key === 'station') state.station = value || null;
      else if (key === 'retest') state.onlyRetest = value === '1';
    });
  }

  function writeHash() {
    var parts = [];
    if (state.station) parts.push('station=' + encodeURIComponent(state.station));
    if (state.prior) parts.push('prior=' + encodeURIComponent(state.prior));
    if (state.onlyRetest) parts.push('retest=1');
    var next = parts.length ? '#' + parts.join('&') : '';
    if (next !== (location.hash || '')) {
      // replaceState so typing a filter does not fill the back button with a
      // keystroke-by-keystroke history.
      history.replaceState(null, '', location.pathname + location.search + next);
    }
  }

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function pct(value) {
    return (value === null || value === undefined) ? '—'
      : (Math.round(value * 1000) / 10) + '%';
  }

  /* ------------------------------------------------------------ filtering */

  function matches(row) {
    if (state.station && row.station !== state.station) return false;
    if (state.onlyRetest && row.kind !== 'retest-fail') return false;
    if (state.prior) {
      var needle = state.prior.toLowerCase();
      var hay = (row.priorFailures || []).join(' ').toLowerCase();
      if (hay.indexOf(needle) === -1) return false;
    }
    return true;
  }

  /* --------------------------------------------------------------- tiles */

  function renderTiles() {
    var c = DATA.counts || {};
    var host = byId('tiles');
    host.innerHTML = '';
    [
      ['New builds', c['new'], 'k-new',
       'first time through this station in the window'],
      ['Retests after a failure', c.retestAfterFail, 'k-fail',
       'the unit failed here last time'],
      ['Retests after a pass', c.retestAfterPass, 'k-pass',
       'back for another reason']
    ].forEach(function (spec) {
      var entry = spec[1] || {};
      host.appendChild(h('div', { class: 'bld-tile ' + spec[2] }, [
        h('span', { class: 'k', text: spec[0] }),
        h('strong', { class: 'v', text: String(entry.runs || 0) }),
        h('span', { class: 's', text: 'pass rate ' + pct(entry.rate) }),
        h('span', { class: 's dim', text: spec[3] })
      ]));
    });
  }

  /* -------------------------------------------------------------- station */

  function renderStations() {
    var bar = byId('stationbar');
    bar.innerHTML = '';
    function chip(label, key, count) {
      var active = state.station === key;
      var button = h('button', {
        type: 'button', 'aria-pressed': active ? 'true' : 'false'
      }, [document.createTextNode(label), h('span', { class: 'n', text: String(count) })]);
      button.addEventListener('click', function () {
        state.station = active ? null : key;
        writeHash();
        render();
      });
      return button;
    }
    bar.appendChild(chip('All stations', null, ROWS.length));
    (DATA.stations || []).forEach(function (s) {
      bar.appendChild(chip(s.label, s.key, s.runs));
    });
  }

  /* ---------------------------------------------------------------- table */

  function render() {
    renderStations();
    var rows = ROWS.filter(matches);
    var body = byId('body');
    body.innerHTML = '';

    rows.slice(0, LIMIT).forEach(function (row) {
      var kind = KIND[row.kind] || KIND['new'];
      var tr = h('tr', {});
      tr.appendChild(h('td', { class: 'day', text: row.day || '' }));
      tr.appendChild(h('td', { class: 'dut ' + kind.cls, text: row.dut }));
      tr.appendChild(h('td', { text: row.stationLabel }));

      /* The classification, in words and in colour — colour alone would not
       * survive a screenshot in a thread, or a reader who cannot see it. */
      tr.appendChild(h('td', { class: 'kind ' + kind.cls }, [
        h('span', { class: 'dot' }),
        document.createTextNode(kind.label +
          (row.kind === 'new' ? '' : ' #' + row.attempt))
      ]));

      tr.appendChild(h('td', { class: 'res r-' + row.status, text: row.status }));
      tr.appendChild(failCell(row.failures, ''));
      tr.appendChild(failCell(row.priorFailures, ' prior'));

      tr.appendChild(h('td', {}, [
        row.url ? h('a', { href: row.url, target: '_blank', rel: 'noopener noreferrer',
                           class: 'runlink', text: 'run ↗' })
                : document.createTextNode('—')
      ]));
      body.appendChild(tr);
    });

    byId('caption').textContent = rows.length + ' of ' + ROWS.length +
      ' runs' + (state.prior ? ' — previously failed “' + state.prior + '”' : '');
    var more = byId('more');
    more.hidden = rows.length <= LIMIT;
    more.textContent = rows.length > LIMIT
      ? 'Showing the ' + LIMIT + ' most recent of ' + rows.length +
        '. Narrow with a station or a failure name.'
      : '';
  }

  /* A unit can fail seventeen tests; the first few identify it and the rest
   * push every other row off the screen. The full list is in the copied TSV. */
  var SHOWN = 5;

  function failCell(names, extra) {
    names = names || [];
    var td = h('td', { class: 'fails' + extra });
    td.appendChild(document.createTextNode(names.slice(0, SHOWN).join('\n')));
    if (names.length > SHOWN) {
      td.appendChild(h('span', { class: 'more',
        text: '+' + (names.length - SHOWN) + ' more' }));
      td.setAttribute('title', names.join('\n'));
    }
    return td;
  }

  /* ------------------------------------------------------------------ tsv */

  function copyTsv() {
    var rows = ROWS.filter(matches);
    var head = ['date', 'dut', 'station', 'kind', 'attempt', 'result',
                'failed_now', 'failed_last'];
    var lines = [head.join('\t')].concat(rows.map(function (r) {
      return [r.day, r.dut, r.stationLabel, r.kind, r.attempt, r.status,
              (r.failures || []).join('; '), (r.priorFailures || []).join('; ')
             ].join('\t');
    }));
    var text = lines.join('\n');
    if (navigator.clipboard) navigator.clipboard.writeText(text);
    var button = byId('copy-tsv');
    button.textContent = 'Copied ' + rows.length + ' rows';
    setTimeout(function () { button.textContent = 'Copy table'; }, 1800);
  }

  function syncControls() {
    byId('prior-filter').value = state.prior;
    byId('only-retest').checked = state.onlyRetest;
  }

  /* ----------------------------------------------------------------- init */

  function renderBuild() {
    var b = DATA.build || {};
    var slot = byId('build');
    if (!slot || (!b.commit && !b.release)) return;
    if (b.release) {
      slot.appendChild(b.releaseUrl
        ? h('a', { class: 'build-release', href: b.releaseUrl, target: '_blank',
                   rel: 'noopener noreferrer', text: b.release })
        : h('span', { class: 'build-release', text: b.release }));
    }
    if (b.commit) {
      slot.appendChild(b.commitUrl
        ? h('a', { class: 'build-commit', href: b.commitUrl, target: '_blank',
                   rel: 'noopener noreferrer', text: b.commit })
        : h('span', { class: 'build-commit', text: b.commit }));
    }
  }

  function init() {
    if (!ROWS.length) {
      byId('caption').textContent =
        'No runs. Build with `make builds` once the controllers are reachable.';
      return;
    }
    byId('meta').textContent = (DATA.source || {}).label || '';
    readHash();
    renderBuild();
    renderTiles();
    syncControls();
    render();

    var search = byId('prior-filter');
    search.addEventListener('input', function () {
      state.prior = search.value.trim();
      writeHash();
      render();
    });
    byId('only-retest').addEventListener('change', function (event) {
      state.onlyRetest = event.target.checked;
      writeHash();
      render();
    });

    // A pasted link has to arrive with its controls already showing the filter
    // it applied, or the reader cannot tell what they are looking at.
    window.addEventListener('hashchange', function () {
      state.station = null; state.prior = ''; state.onlyRetest = false;
      readHash();
      syncControls();
      render();
    });
    byId('copy-tsv').addEventListener('click', copyTsv);
    byId('copy-link').addEventListener('click', function () {
      if (navigator.clipboard) navigator.clipboard.writeText(location.href);
      var button = byId('copy-link');
      button.textContent = 'Link copied';
      setTimeout(function () { button.textContent = 'Copy link'; }, 1800);
    });

    var window_ = DATA.window || {};
    byId('footer-meta').textContent =
      'Window ' + (window_.from || '?') + ' → ' + (window_.to || '?') + ' · ' +
      (DATA.publishedDays || []).length + ' days published · built ' +
      String(DATA.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
