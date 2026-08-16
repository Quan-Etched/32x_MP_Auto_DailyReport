/* One week: the yield per step, and every unit row behind it.
 *
 * The page exists because of an argument. Two people counted the same
 * validation and got 24 and 39, and settling it meant listing the units. So
 * the table of numbers is only half of this page — under it is every run that
 * went into them, with the serial, the release, the verdict and a link to the
 * controller that still holds the log. A yield nobody can check is a yield
 * nobody believes.
 *
 * The week lives in the hash (#week=2026-W33), so a week is a link.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_WEEKLY__ || {};
  var WEEKS = DATA.weeks || [];

  var el = {};
  var current = null;
  var filter = null;              /* station key, or null for all */
  var LIMIT = 400;                /* rows drawn before "show the rest" */
  var shown = LIMIT;

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
    if (v >= 0.9) return 'good';
    if (v >= 0.6) return 'warn';
    return 'bad';
  }

  function pick(label) {
    for (var i = 0; i < WEEKS.length; i++) {
      if (WEEKS[i].week === label) return WEEKS[i];
    }
    return WEEKS.length ? WEEKS[0] : null;   /* newest by default */
  }

  function hashWeek() {
    var match = /week=([0-9]{4}-W[0-9]{2})/.exec(location.hash || '');
    return match ? match[1] : null;
  }

  /* ------------------------------------------------------------------ bar */

  function renderBar() {
    el.bar.innerHTML = '';
    WEEKS.forEach(function (week) {
      var active = current && week.week === current.week;
      var button = h('button', {
        type: 'button', 'aria-pressed': active ? 'true' : 'false'
      }, [
        document.createTextNode(week.week),
        h('span', { class: 'n', text: week.from.slice(5) + ' – ' +
          week.endsOn.slice(5) + (week.partial ? ' · running' : '') })
      ]);
      button.addEventListener('click', function () {
        location.hash = 'week=' + week.week;
      });
      el.bar.appendChild(button);
    });
  }

  /* ---------------------------------------------------------------- tiles */

  function renderTiles(week) {
    var totals = week.totals || {};
    el.tiles.innerHTML = '';

    var units = (week.rows || []).reduce(function (sum, row) {
      return sum + row.units;
    }, 0);

    el.tiles.appendChild(tile('Rolled first-pass',
      pct(totals.rolledFpy),
      (totals.rolledOver || []).join(' × ') ||
        'no step had enough units to read', 'lead'));
    el.tiles.appendChild(tile('Units tested', String(units),
      (week.rows || []).length + ' steps · ' +
      (week.units || []).length + ' unit runs'));
    el.tiles.appendChild(tile('Week',
      week.from.slice(5) + ' – ' + week.endsOn.slice(5),
      week.partial ? 'still running — Monday to today' : 'Monday to Sunday'));
  }

  function tile(label, value, sub, extra) {
    return h('div', { class: 'wk-tile ' + (extra || '') }, [
      h('span', { class: 'k', text: label }),
      h('strong', { class: 'v', text: value }),
      h('span', { class: 's', text: sub })
    ]);
  }

  /* ---------------------------------------------------------------- steps */

  function renderSteps(week) {
    var body = byId('steps');
    body.innerHTML = '';

    (week.external || []).forEach(function (item) {
      var tr = h('tr', { class: 'reported' });
      tr.appendChild(h('td', {}, [
        h('span', { class: 'step', text: item.label }),
        h('span', { class: 'sub', text: 'asked weekly — Sigurd' })
      ]));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'n y ' + tone(item['yield']),
                               text: pct(item['yield']) }));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'fails',
        text: 'reported ' + item.asOf + ', not collected here' }));
      body.appendChild(tr);
    });

    (week.rows || []).forEach(function (row) {
      var tr = h('tr', { class: row.readable ? '' : 'thin' });
      tr.appendChild(h('td', {}, [
        h('span', { class: 'step', text: row.label }),
        h('span', { class: 'sub', text: (row.controller || '') +
          (row.readable ? '' : ' · under ' + DATA.minCohort +
            ' units, no yield reported') })
      ]));
      tr.appendChild(h('td', { class: 'n', text: String(row.units) }));
      tr.appendChild(h('td', { class: 'n', text: String(row.runs) }));
      tr.appendChild(h('td', { class: 'n y ' + tone(row.fpy) }, [
        document.createTextNode(pct(row.fpy)),
        h('span', { class: 'sub', text: row.readable
          ? 'of ' + row.newUnits + ' new' : row.newUnits + ' new' })
      ]));
      tr.appendChild(h('td', { class: 'n' }, [
        document.createTextNode(pct(row.finalYield)),
        h('span', { class: 'sub', text: row.passedUnits + ' passed' })
      ]));
      /* Named as a rate and spelled out underneath, because "retest load"
       * read as a count to more than one person. */
      tr.appendChild(h('td', { class: 'n retest' }, [
        document.createTextNode(row.retestRatio == null ? '—'
                                : pct(row.retestRatio)),
        h('span', { class: 'sub', text: row.retestUnits == null
          ? (row.retestNote || '')
          : row.retestUnits + ' of ' + row.units + ' units re-run' })
      ]));

      var fails = h('td', { class: 'fails' });
      (row.topFailures || []).slice(0, 3).forEach(function (item, index) {
        if (index) fails.appendChild(document.createElement('br'));
        fails.appendChild(h('b', { text: item.name }));
        fails.appendChild(document.createTextNode(' ×' + item.runs));
      });
      tr.appendChild(fails);
      body.appendChild(tr);
    });

    byId('steps-caption').textContent =
      week.from + ' to ' + week.to + ' (UTC)' +
      (week.partial ? ', week still running' : '') +
      '. First-pass yield counts units on their first run at that step. ' +
      'Steps with fewer than ' + DATA.minCohort +
      ' first-time units report counts only.';
  }

  /* --------------------------------------------------------------- source */

  function renderFilters(week) {
    var host = byId('filters');
    host.innerHTML = '';
    var steps = [];
    (week.units || []).forEach(function (row) {
      if (steps.indexOf(row.station) === -1) steps.push(row.station);
    });
    var labels = {};
    (week.rows || []).forEach(function (row) { labels[row.key] = row.label; });

    function chip(key, text) {
      var button = h('button', {
        type: 'button', class: 'wk-chip',
        'aria-pressed': filter === key ? 'true' : 'false', text: text
      });
      button.addEventListener('click', function () {
        filter = key; shown = LIMIT; renderUnits(week); renderFilters(week);
      });
      return button;
    }

    host.appendChild(chip(null, 'All steps'));
    steps.forEach(function (key) {
      var n = (week.units || []).filter(function (row) {
        return row.station === key;
      }).length;
      host.appendChild(chip(key, (labels[key] || key) + ' (' + n + ')'));
    });
  }

  function renderUnits(week) {
    var body = byId('units');
    var labels = {};
    (week.rows || []).forEach(function (row) { labels[row.key] = row.label; });

    var rows = (week.units || []).filter(function (row) {
      return !filter || row.station === filter;
    });

    body.innerHTML = '';
    rows.slice(0, shown).forEach(function (row) {
      var tr = h('tr', {});
      tr.appendChild(h('td', { class: 'day', text: row.day }));
      tr.appendChild(h('td', { text: labels[row.station] || row.station }));
      tr.appendChild(h('td', { class: 'dut', text: row.dut }));
      tr.appendChild(h('td', { class: 'rel', text: row.release }));
      tr.appendChild(h('td', { class: 'n', text: String(row.attempt) }));
      tr.appendChild(h('td', { class: 'res r-' + row.status, text: row.status }));
      tr.appendChild(h('td', { class: 'fails small',
                               text: (row.failures || []).join('\n') }));
      tr.appendChild(h('td', {}, [
        row.url ? h('a', { class: 'srclink', href: row.url, target: '_blank',
                           rel: 'noopener noreferrer',
                           title: row.url + '  (pega asks for an ESVM login)',
                           text: row.controller + ' ↗' })
                : document.createTextNode('—')
      ]));
      body.appendChild(tr);
    });

    byId('units-caption').textContent = rows.length + ' unit runs' +
      (filter ? ' at ' + (labels[filter] || filter) : ' across every step') +
      ', oldest first';

    var more = byId('more');
    more.innerHTML = '';
    if (rows.length > shown) {
      var button = h('button', { type: 'button', class: 'wk-more-btn',
        text: 'Show the remaining ' + (rows.length - shown) + ' rows' });
      button.addEventListener('click', function () {
        shown = rows.length; renderUnits(week);
      });
      more.appendChild(button);
    }
  }

  /* --------------------------------------------------------------- chrome */

  function renderSources(week) {
    var source = DATA.source || {};
    var host = byId('sources');
    host.innerHTML = '';
    host.appendChild(h('p', { class: 'src', text:
      'Data source: ' + (source.label || 'the station controllers') +
      ' — read directly from pega2–pega5, one row per unit rather than one ' +
      'per fixture, so a fixture of eight modules is eight rows here. Every ' +
      'row links to the run on its controller. Attempts are numbered over ' +
      (DATA.historyDays || 30) + ' days of history, so a unit returning this ' +
      'week counts as a retest rather than a first pass. VBB provisioning is ' +
      'left out: it is a real stage but not part of the product test flow. ' +
      'WST and FT are Sigurd’s and are asked for weekly in ' +
      '#production-test-eng. Built ' +
      String(DATA.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC') +
      '.' }));

    if (!week.hasDetail) {
      host.appendChild(h('p', { class: 'src', text:
        'Unit rows are kept for the four most recent weeks. This week is ' +
        'older than that, so only its summary remains — see weekly/ in the ' +
        'repo for the archived copy.' }));
    }
  }

  function renderBuild() {
    var info = DATA.build || {};
    var slot = byId('build');
    slot.innerHTML = '';
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

  function show() {
    var next = pick(hashWeek());
    if (!next) return;
    if (!current || current.week !== next.week) { filter = null; shown = LIMIT; }
    current = next;

    byId('title').textContent = 'Week ' + current.week;
    byId('meta').textContent = current.from + ' → ' + current.endsOn +
      (current.partial ? ' (running)' : '');
    document.title = 'Week ' + current.week + ' — yield and source data';

    byId('source-note').textContent =
      'Every run the controllers recorded this week, at the granularity the ' +
      'yield above was counted at. Filter by step, then check any number ' +
      'against the runs that made it.';

    renderBar();
    renderTiles(current);
    renderSteps(current);
    renderFilters(current);
    renderUnits(current);
    renderSources(current);
    renderBuild();
  }

  function init() {
    el.bar = byId('weekbar');
    el.tiles = byId('tiles');
    if (!WEEKS.length) {
      byId('steps-caption').textContent = 'No data — run `make weekly`.';
      return;
    }
    show();
    window.addEventListener('hashchange', show);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
