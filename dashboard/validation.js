/* One suite's validation run.
 *
 * Built because two people counted the mlt_2026.225 validation and got 24 and
 * 39, and both were right — one counted the validation suite, the other every
 * MLT unit that ran that day. The reconciliation box near the top is therefore
 * not a footnote; it is the thing the page is for.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_VALIDATION__ || {};
  var ROWS = DATA.rows || [];

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
  function pct(n, d) { return d ? (Math.round((n / d) * 1000) / 10) + '%' : '—'; }

  function tiles() {
    var c = DATA.counts || {};
    var host = byId('tiles');
    host.innerHTML = '';
    [
      ['Units through the suite', c.units, c.passed + ' passed · ' +
        c.failed + ' failed', pct(c.passed, c.units), ''],
      ['New to this station', (c['new'] || {}).units,
       (c['new'] || {}).passed + ' passed', pct((c['new'] || {}).passed, (c['new'] || {}).units),
       'k-new'],
      ['Been here before', (c.seen || {}).units,
       (c.seen || {}).passed + ' passed', pct((c.seen || {}).passed, (c.seen || {}).units),
       'k-fail']
    ].forEach(function (spec) {
      host.appendChild(h('div', { class: 'bld-tile ' + spec[4] }, [
        h('span', { class: 'k', text: spec[0] }),
        h('strong', { class: 'v', text: String(spec[1] === undefined ? '—' : spec[1]) }),
        h('span', { class: 's', text: spec[2] }),
        h('span', { class: 's dim', text: 'pass rate ' + spec[3] })
      ]));
    });
  }

  /* The two numbers, side by side, with the arithmetic shown. */
  function reconcile() {
    var r = DATA.reconcile || {};
    var host = byId('reconcile');
    if (!r.dayTotal) { host.hidden = true; return; }
    host.innerHTML = '';

    var mine = (DATA.counts || {}).units || 0;
    host.appendChild(h('h2', { text: 'If you have seen a different number' }));
    host.appendChild(h('p', {}, [
      document.createTextNode('This suite ran on '),
      h('strong', { text: String(mine) + ' units' }),
      document.createTextNode('. The station page and the daily tracker count '),
      h('strong', { text: String(r.dayTotal) }),
      document.createTextNode(' for the same day, because they count every MLT ' +
        'suite the line ran — production and validation together — and only ' +
        'their heading names a release. Both numbers are right about different ' +
        'questions. Everything the station ran that day:')
    ]));

    var table = h('table', { class: 'val-sib' });
    var body = h('tbody', {});
    body.appendChild(h('tr', { class: 'mine' }, [
      h('td', { class: 'mine', text: DATA.suite }),
      h('td', { class: 'n mine', text: String(mine) }),
      h('td', { class: 'mine', text: 'this page' })
    ]));
    (r.siblings || []).forEach(function (s) {
      body.appendChild(h('tr', {}, [
        h('td', { text: s.suite }),
        h('td', { class: 'n', text: String(s.units) }),
        h('td', { text: s.overlap === s.units
          ? 'all also in this suite'
          : (s.overlap ? s.overlap + ' also in this suite'
                       : 'no overlap — these are the extra units') })
      ]));
    });
    table.appendChild(body);
    host.appendChild(table);
  }

  function rows() {
    var body = byId('body');
    body.innerHTML = '';
    ROWS.forEach(function (row) {
      var cls = row.isNew ? 'k-new' : 'k-fail';
      var tr = h('tr', {});
      tr.appendChild(h('td', { class: 'dut ' + cls, text: row.dut }));
      tr.appendChild(h('td', { class: 'slot', text: String(row.slot) }));
      tr.appendChild(h('td', { class: 'kind ' + cls }, [
        h('span', { class: 'dot' }),
        document.createTextNode(row.isNew ? 'New build'
          : 'Retest (' + row.priorRuns + ' before)')
      ]));
      tr.appendChild(h('td', { class: 'res r-' + row.status, text: row.status }));
      tr.appendChild(h('td', { class: 'fails', text: (row.failures || []).join('\n') }));
      tr.appendChild(h('td', { class: 'fails prior',
        text: (row.priorFailures || []).slice(0, 4).join('\n') }));
      tr.appendChild(h('td', {}, [
        row.url ? h('a', { class: 'runlink', href: row.url, target: '_blank',
                           rel: 'noopener noreferrer', text: 'slot ' + row.slot + ' ↗' })
                : document.createTextNode('—')
      ]));
      body.appendChild(tr);
    });
    byId('caption').textContent = ROWS.length + ' units, newest failures first';
  }

  function runsList() {
    var host = byId('runs');
    var list = h('ul', {});
    (DATA.runs || []).forEach(function (run) {
      list.appendChild(h('li', {}, [
        h('a', { href: run.url, target: '_blank', rel: 'noopener noreferrer',
                 text: run.short }),
        document.createTextNode(' · ' + run.slots + ' slots · ' +
          (run.station || '') + ' · ' + (run.startedAt || '').replace('T', ' ').slice(0, 16))
      ]));
    });
    host.appendChild(h('h2', { text: 'Suite runs behind this page' }));
    host.appendChild(list);
  }

  function build() {
    var b = DATA.build || {};
    var slot = byId('build');
    if (b.release) slot.appendChild(h('span', { class: 'build-release', text: b.release }));
    if (b.commit) {
      slot.appendChild(b.commitUrl
        ? h('a', { class: 'build-commit', href: b.commitUrl, target: '_blank',
                   rel: 'noopener noreferrer', text: b.commit })
        : h('span', { class: 'build-commit', text: b.commit }));
    }
  }

  function init() {
    if (!ROWS.length) {
      byId('intro').textContent = 'No units found for this suite.';
      return;
    }
    var suite = DATA.suite || '';
    byId('title').textContent = suite.indexOf('225') !== -1
      ? 'MLT 225 validation' : 'Validation';
    byId('meta').textContent = (DATA.days || []).join(', ');

    byId('intro').appendChild(document.createTextNode('Every unit that went through '));
    byId('intro').appendChild(h('code', { text: suite }));
    byId('intro').appendChild(document.createTextNode(
      ' on ' + (DATA.days || []).join(', ') + ', from ' + (DATA.host || 'pega3') +
      '. Serial, slot, what it did, and whether it had been through MLT before.'));

    build();
    tiles();
    reconcile();
    rows();
    runsList();
    byId('footer-meta').textContent = 'Built ' +
      String(DATA.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
