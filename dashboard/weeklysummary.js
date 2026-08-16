/* Every week, one row. The index over the per-week pages.
 *
 * Columns are the test steps, so a step reads down the page and a week reads
 * across it. Which steps appear is decided by the data rather than hard-coded:
 * the line gained L10 stations mid-quarter and will gain more, and a fixed
 * column list would silently omit them.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_WEEKLY__ || {};
  var WEEKS = DATA.weeks || [];

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
  function pct(v) { return v == null ? '—' : (Math.round(v * 1000) / 10) + '%'; }
  function tone(v) {
    if (v == null) return '';
    return v >= 0.9 ? 'good' : v >= 0.6 ? 'warn' : 'bad';
  }

  /* Steps in line order, taken from whichever weeks have them. */
  function steps() {
    var seen = [], labels = {};
    WEEKS.forEach(function (week) {
      (week.rows || []).forEach(function (row) {
        if (seen.indexOf(row.key) === -1) seen.push(row.key);
        labels[row.key] = row.label;
      });
    });
    return seen.map(function (key) { return { key: key, label: labels[key] }; });
  }

  function render() {
    var cols = steps();

    var head = h('tr', {});
    head.appendChild(h('th', { scope: 'col', text: 'Week' }));
    head.appendChild(h('th', { scope: 'col', class: 'n', text: 'Rolled' }));
    cols.forEach(function (col) {
      head.appendChild(h('th', { scope: 'col', class: 'n', text: col.label }));
    });
    head.appendChild(h('th', { scope: 'col', class: 'n', text: 'Unit runs' }));
    byId('head').innerHTML = '';
    byId('head').appendChild(head);

    var body = byId('body');
    body.innerHTML = '';
    WEEKS.forEach(function (week) {
      var by = {};
      (week.rows || []).forEach(function (row) { by[row.key] = row; });

      var tr = h('tr', {});
      var cell = h('td', {}, [
        h('a', { class: 'wk-link', href: 'week.html#week=' + week.week,
                 text: week.week }),
        h('span', { class: 'sub', text: week.from.slice(5) + ' – ' +
          week.endsOn.slice(5) + (week.partial ? ' · running' : '') })
      ]);
      tr.appendChild(cell);
      tr.appendChild(h('td', { class: 'n y ' + tone((week.totals || {}).rolledFpy),
                               text: pct((week.totals || {}).rolledFpy) }));

      cols.forEach(function (col) {
        var row = by[col.key];
        var td = h('td', { class: 'n' });
        if (!row) {
          td.textContent = '—';
        } else if (row.fpy == null) {
          /* No yield published — either the stage reports quantity only, or
             it ran too few units. The count is the honest answer to both. */
          td.appendChild(h('span', { class: 'countonly',
                                     text: row.units + ' u' }));
          td.title = row.countsOnly
            ? 'Quantity only — chassis and rack level, in bring-up'
            : 'Fewer than ' + DATA.minCohort + ' first-time units';
        } else {
          td.className = 'n y ' + tone(row.fpy);
          td.appendChild(document.createTextNode(pct(row.fpy)));
          td.appendChild(h('span', { class: 'sub', text: row.units + ' u' }));
        }
        tr.appendChild(td);
      });

      tr.appendChild(h('td', { class: 'n', text: week.hasDetail
        ? String((week.units || []).length) : 'summary only' }));
      body.appendChild(tr);
    });

    byId('caption').textContent = WEEKS.length + ' weeks. ' +
      'A cell shows first-pass yield with the unit count under it; where a ' +
      'step ran fewer than ' + DATA.minCohort + ' first-time units only the ' +
      'count is shown, because a yield over three chassis is not a yield.';

    byId('meta').textContent = WEEKS.length
      ? WEEKS[WEEKS.length - 1].from + ' → ' + WEEKS[0].endsOn : '';

    var info = DATA.build || {};
    var slot = byId('build');
    if (info.release) {
      slot.appendChild(h('span', { class: 'build-release', text: info.release }));
    }
    if (info.commit) {
      slot.appendChild(info.commitUrl
        ? h('a', { class: 'build-commit', href: info.commitUrl,
                   target: '_blank', rel: 'noopener noreferrer',
                   text: info.commit })
        : h('span', { class: 'build-commit', text: info.commit }));
    }

    byId('sources').appendChild(h('p', { class: 'src', text:
      'Rolled first-pass is the product of the steps that had enough units to '
      + 'read — named on each week’s own page. VBB provisioning is '
      + 'excluded: a real stage, but not part of the product test flow. WST '
      + 'and FT are Sigurd’s and are asked for weekly in '
      + '#production-test-eng; they appear on a week’s page once '
      + 'reported. Source: ' + ((DATA.source || {}).label ||
        'the station controllers') + '.' }));
  }

  function init() {
    if (!WEEKS.length) {
      byId('caption').textContent = 'No data — run `make weekly`.';
      return;
    }
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
