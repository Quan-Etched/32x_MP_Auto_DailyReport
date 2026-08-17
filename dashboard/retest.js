/* Retests, laid out like the workbook's Retest tab.
 *
 * First attempt on the left, retest on the right, MLT and HTT on one row per
 * unit — the shape the line already reads in its reviews. The split above the
 * table is the thing the daily tracker cannot show: it keeps one row per unit
 * with the latest attempt winning, so a unit that failed in the morning and
 * passed in the afternoon is one pass there, and the fresh units and the
 * re-runs are averaged into a single number that describes neither.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RETEST__ || {};
  var ROWS = DATA.rows || [];
  var STATIONS = [['mlt', 'MLT'], ['htt', 'HTT']];

  var filter = null;          /* 'recovered' | 'failing' | station key | null */

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

  /* ---------------------------------------------------------------- split */

  function renderSplit() {
    var host = byId('split');
    host.innerHTML = '';
    STATIONS.forEach(function (pair) {
      var s = (DATA.split || {})[pair[0]];
      if (!s) return;
      host.appendChild(h('div', { class: 'rt-card' }, [
        h('h2', { text: s.label }),
        h('div', { class: 'rt-pair' }, [
          h('div', { class: 'rt-new' }, [
            h('span', { class: 'rt-k', text: 'New input — first attempt' }),
            h('strong', { class: 'rt-v', text: pct(s.firstPassRate) }),
            h('span', { class: 'rt-s', text: s.firstPass + ' of ' + s.units +
              ' units passed first time' })
          ]),
          h('div', { class: 'rt-back' }, [
            h('span', { class: 'rt-k', text: 'Came back for a retest' }),
            h('strong', { class: 'rt-v', text: pct(s.retestRate) }),
            h('span', { class: 'rt-s', text: s.retested + ' units, ' +
              s.retestPassed + ' passing in the end' })
          ])
        ]),
        h('span', { class: 'rt-note', text: s.recovered +
          ' unit' + (s.recovered === 1 ? '' : 's') + ' failed first and passed ' +
          'on a later attempt — recovered, at the cost of ' +
          (s.retested === 1 ? 'one extra occupancy' :
           s.retested + ' extra station occupancies') + '.' })
      ]));
    });
  }

  /* -------------------------------------------------------------- filters */

  function shown() {
    return ROWS.filter(function (row) {
      if (!filter) return true;
      if (filter === 'recovered') {
        return STATIONS.some(function (p) {
          return (row.attempts[p[0]] || {}).recovered;
        });
      }
      if (filter === 'failing') {
        return STATIONS.some(function (p) {
          var a = row.attempts[p[0]] || {};
          return a.count > 1 && a.stillFailing;
        });
      }
      return (row.retested || []).indexOf(filter) !== -1;
    });
  }

  function renderFilters() {
    var host = byId('filters');
    host.innerHTML = '';
    var options = [[null, 'All retested units']];
    STATIONS.forEach(function (p) {
      options.push([p[0], 'Re-run at ' + p[1]]);
    });
    options.push(['recovered', 'Recovered on retest']);
    options.push(['failing', 'Still failing']);

    options.forEach(function (option) {
      var n = ROWS.filter(function (row) {
        var was = filter; filter = option[0];
        var keep = shown().indexOf(row) !== -1;
        filter = was; return keep;
      }).length;
      var button = h('button', {
        type: 'button', class: 'rt-chip',
        'aria-pressed': filter === option[0] ? 'true' : 'false',
        text: option[1] + ' (' + n + ')'
      });
      button.addEventListener('click', function () {
        filter = option[0]; renderFilters(); renderRows();
      });
      host.appendChild(button);
    });
  }

  /* ----------------------------------------------------------------- rows */

  function attemptCells(tr, attempt, isRetest) {
    var cls = isRetest ? 'rt' : '';
    if (!attempt) {
      for (var i = 0; i < 3; i++) tr.appendChild(h('td', { class: cls }));
      return;
    }
    tr.appendChild(h('td', { class: 'res r-' + attempt.status + ' ' + cls,
                             text: attempt.status === 'pass' ? 'Passed' : 'Failed' }));
    tr.appendChild(h('td', { class: 'fails ' + cls,
                             text: attempt.failures || '' }));
    var link = h('td', { class: cls });
    if (attempt.url) {
      link.appendChild(h('a', {
        class: 'link', href: attempt.url, target: '_blank',
        rel: 'noopener noreferrer',
        title: attempt.url + '  (pega3 asks for an ESVM login)',
        text: attempt.short
      }));
    }
    /* The build each attempt ran. A retest against a new release is a
     * different event from a retest against the same one, and the column
     * would otherwise look identical. */
    link.appendChild(h('span', { class: 'build', text: attempt.suite || '' }));
    tr.appendChild(link);
    return;
  }

  function outcome(row) {
    var recovered = 0, failing = 0;
    STATIONS.forEach(function (p) {
      var a = row.attempts[p[0]];
      if (!a || a.count < 2) return;
      if (a.recovered) recovered += 1;
      else if (a.stillFailing) failing += 1;
    });
    if (recovered && !failing) return ['Recovered', 'out-recovered'];
    if (failing && !recovered) return ['Still failing', 'out-failing'];
    if (recovered && failing) return ['Mixed', 'out-mixed'];
    return ['Re-run, passed both', 'out-recovered'];
  }

  function renderRows() {
    var body = byId('body');
    var rows = shown();
    body.innerHTML = '';

    rows.forEach(function (row) {
      var tr = h('tr', {});
      tr.appendChild(h('td', { class: 'day', text: row.day }));
      tr.appendChild(h('td', { class: 'dut', text: row.dut }));
      tr.appendChild(h('td', { text: row.pn || '' }));

      STATIONS.forEach(function (p) {
        var a = row.attempts[p[0]];
        attemptCells(tr, a ? a.first : null, false);
      });
      STATIONS.forEach(function (p) {
        var a = row.attempts[p[0]];
        /* Only a station that was actually re-run has a retest column; a unit
         * that ran MLT once and HTT three times must not appear to have been
         * re-run at MLT. */
        attemptCells(tr, (a && a.count > 1) ? a.last : null, true);
      });

      var out = outcome(row);
      tr.appendChild(h('td', { class: 'out ' + out[1], text: out[0] }));
      body.appendChild(tr);
    });

    var window7 = DATA.window || {};
    byId('caption').textContent = rows.length + ' of ' + ROWS.length +
      ' units re-run, ' + window7.from + ' to ' + window7.to + ' (UTC). ' +
      'Attempts are numbered inside the window: a unit first tested before ' +
      window7.from + ' and re-run since counts as a first attempt here.';
  }

  /* --------------------------------------------------------------- chrome */

  function renderSources() {
    var source = DATA.source || {};
    byId('sources').appendChild(h('p', { class: 'src', text:
      'Data source: ' + (source.label || 'pega3') + ' — ' + (source.note || '') +
      '. Every build is included, production and validation and debug alike, ' +
      'because the daily tracker includes them and this page has to reconcile ' +
      'with it; each attempt names the build it ran. ' + (DATA.runs || 0) +
      ' suite runs read. Built ' +
      String(DATA.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC') +
      '.' }));
  }

  function renderBuild() {
    var info = DATA.build || {};
    var slot = byId('build');
    if (info.release) {
      slot.appendChild(h('span', { class: 'build-release', text: info.release }));
    }
    if (info.commit) {
      slot.appendChild(info.commitUrl
        ? h('a', { class: 'build-commit', href: info.commitUrl, target: '_blank',
                   rel: 'noopener noreferrer', text: info.commit })
        : h('span', { class: 'build-commit', text: info.commit }));
    }
  }

  function init() {
    if (!ROWS.length && !(DATA.split || {}).mlt) {
      byId('caption').textContent = 'No data — run `make retest`.';
      return;
    }
    var window7 = DATA.window || {};
    byId('meta').textContent = window7.from + ' → ' + window7.to +
      ' · ' + (window7.days || 7) + ' days';
    renderSplit();
    renderFilters();
    renderRows();
    renderSources();
    renderBuild();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
