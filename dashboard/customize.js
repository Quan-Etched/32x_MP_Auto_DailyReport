/* Pick a range of UTC days and a set of stations, then take the CSV.
 *
 * WHY THE DAY IS COMPUTED AND NOT READ
 * Every row in the bundle carries a `day`, and using it here would be wrong.
 * That field is factory-local (America/Los_Angeles) because the run table it
 * was built for is read by people standing in the factory — and on this
 * bundle it disagrees with the UTC date on 2126 of 5427 rows. A UTC filter that
 * quietly used it would be about 40% wrong at the boundaries and would look
 * perfectly plausible. So the day is derived from the run's own epoch, every
 * time, and the page says UTC in three places.
 *
 * That also lines this page up with the daily tracker, whose tabs are UTC for
 * a reason of its own (build_dailyexcel._utc_day: the line's sheet files a
 * 17:30-local run under the next day, and a derived tab bucketed locally would
 * sit on a different day from the tabs beside it).
 *
 * THE PREVIEW IS TRUNCATED AND THE CSV IS NOT
 * A table with ten thousand rows in it helps nobody, so the preview stops. The
 * download is the whole selection, and the note above the table says which is
 * which — a file that silently held less than it offered would be the worse
 * failure of the two.
 *
 * Plain ES5, no build step, no dependencies.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RUNS__ || window.__FACTORY_RUNS_PEGA__ || {};
  var RUNS = DATA.runs || [];
  var NAMES = DATA.testNames || [];
  var TSTATUS = DATA.testStatuses || [];
  var LABELS = DATA.stationLabels || {};
  var LINKS = DATA.links || {};

  /* Parent nodes rather than real tests, decided at build time. A nest fails
   * because a leaf under it did, so listing it as the failure names the shape
   * of the suite instead of the fault. */
  var CONTAINERS = {};
  (DATA.containerNames || []).forEach(function (index) { CONTAINERS[index] = true; });

  /* How many rows the preview shows. The CSV ignores this. */
  var PREVIEW = 200;

  var view = { from: null, to: null, stations: null };

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else if (attrs[key] !== null && attrs[key] !== undefined)
        node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  function labelOf(key) { return LABELS[key] || key; }

  /* ------------------------------------------------------------------ days */

  /* The run's UTC day, from its own timestamp. Never the bundle's `day`. */
  function utcDay(run) {
    if (!run.t) return null;
    return new Date(run.t * 1000).toISOString().slice(0, 10);
  }

  var DAYS = (function () {
    var seen = {};
    RUNS.forEach(function (run) {
      var day = utcDay(run);
      if (day) seen[day] = (seen[day] || 0) + 1;
    });
    return Object.keys(seen).sort();
  })();

  function shift(day, days) {
    var at = new Date(day + 'T00:00:00Z');
    at.setUTCDate(at.getUTCDate() + days);
    return at.toISOString().slice(0, 10);
  }

  /* ------------------------------------------------------------- selection */

  function stationCounts() {
    var counts = {};
    RUNS.forEach(function (run) {
      var day = utcDay(run);
      if (!day || day < view.from || day > view.to) return;
      counts[run.k] = (counts[run.k] || 0) + 1;
    });
    return counts;
  }

  function allStations() {
    var seen = {};
    RUNS.forEach(function (run) { if (run.k) seen[run.k] = true; });
    return Object.keys(seen).sort(function (a, b) {
      return labelOf(a).localeCompare(labelOf(b));
    });
  }

  function selected() {
    return RUNS.filter(function (run) {
      var day = utcDay(run);
      if (!day || day < view.from || day > view.to) return false;
      return view.stations[run.k];
    }).sort(function (a, b) { return (a.t || 0) - (b.t || 0); });
  }

  /* --------------------------------------------------------------- decoding */

  /* The per-run noise on a controller test id.
   *
   * ``2d257ec5_validate_coldplate_temperature`` and
   * ``e4306c91_validate_coldplate_temperature`` are the same test failing on
   * two runs. Left as they are, a hundred failures of one case become a hundred
   * distinct strings and the column cannot be pivoted — which is most of why
   * somebody wanted the CSV. Same expression as rootcause.RUN_PREFIX, which is
   * what the Pareto groups on, so a signature here matches a signature there.
   */
  var RUN_PREFIX = /^[0-9a-f]{6,10}_(chip\d+_|sohu_)?/i;
  function signature(name) {
    return name ? String(name).replace(RUN_PREFIX, '') : name;
  }

  function failedCases(run) {
    var out = [];
    (run.T || []).forEach(function (test) {
      var status = TSTATUS[test[1]];
      if (status !== 'fail' && status !== 'error') return;
      if (CONTAINERS[test[0]]) return;
      var name = signature(NAMES[test[0]]);
      if (name && out.indexOf(name) === -1) out.push(name);
    });
    return out;
  }

  function firstFailure(run) {
    var cases = failedCases(run);
    if (cases.length) return cases[0];
    /* Nothing but nests failed. Naming one is more use than a blank beside a
     * Failed verdict, which is the one thing that column must not be. */
    var fallback = null;
    (run.T || []).forEach(function (test) {
      var status = TSTATUS[test[1]];
      if (fallback || (status !== 'fail' && status !== 'error')) return;
      fallback = signature(NAMES[test[0]]) || null;
    });
    return fallback;
  }

  function runLink(run) {
    var cfg = LINKS.pega;
    if (!cfg || !run.i) return '';
    var host = (cfg.hosts || {})[run.k];
    if (!host) return '';
    var id = String(run.i), slot = null, hash = id.indexOf('#slot');
    if (hash !== -1) { slot = id.slice(hash + 5); id = id.slice(0, hash); }
    var template = slot === null ? cfg.runTemplateNoSlot : cfg.urlTemplate;
    if (!template) return '';
    return template.replace('{host}', host)
      .replace('{run}', encodeURIComponent(id))
      .replace('{slot}', encodeURIComponent(slot || ''));
  }

  function stamp(run) {
    if (!run.t) return '';
    return new Date(run.t * 1000).toISOString().replace('T', ' ').slice(0, 19);
  }

  /* ---------------------------------------------------------------- columns */

  var COLUMNS = [
    ['Day_UTC', function (r) { return utcDay(r) || ''; }],
    ['Station', function (r) { return labelOf(r.k); }],
    ['Station_Key', function (r) { return r.k || ''; }],
    ['DUT_SN', function (r) { return r.d || ''; }],
    ['Suite', function (r) { return r.su || ''; }],
    ['Status', function (r) { return r.s || ''; }],
    ['Attempt', function (r) { return r.a === undefined ? '' : r.a; }],
    ['Started_UTC', stamp],
    ['Duration_s', function (r) { return r.u === undefined ? '' : r.u; }],
    ['First_Failure', function (r) { return firstFailure(r) || ''; }],
    ['Failed_Cases', function (r) { return failedCases(r).join('; '); }],
    ['Run_Link', runLink]
  ];

  /* The preview shows the columns worth scanning; the CSV carries all of them.
   * Twelve columns on screen is a horizontal scrollbar and nothing gained. */
  var PREVIEW_COLUMNS = ['Day_UTC', 'Station', 'DUT_SN', 'Suite', 'Status',
                         'Attempt', 'Started_UTC', 'First_Failure'];

  /* -------------------------------------------------------------- rendering */

  function renderQuick() {
    var host = byId('quick');
    host.innerHTML = '';
    if (!DAYS.length) return;
    var last = DAYS[DAYS.length - 1];
    [['Last 7 days', shift(last, -6)], ['Last 30 days', shift(last, -29)],
     ['Everything', DAYS[0]]].forEach(function (pair) {
      var from = pair[1] < DAYS[0] ? DAYS[0] : pair[1];
      var on = view.from === from && view.to === last;
      var button = h('button', {
        type: 'button', class: 'view-toggle' + (on ? ' on' : ''), text: pair[0]
      });
      button.addEventListener('click', function () {
        view.from = from; view.to = last; writeHash(); render();
      });
      host.appendChild(button);
    });
  }

  function renderPickers() {
    var from = byId('from'), to = byId('to');
    if (DAYS.length) {
      from.setAttribute('min', DAYS[0]); from.setAttribute('max', DAYS[DAYS.length - 1]);
      to.setAttribute('min', DAYS[0]); to.setAttribute('max', DAYS[DAYS.length - 1]);
    }
    from.value = view.from;
    to.value = view.to;
    byId('range-sub').textContent = DAYS.length
      ? 'The controllers hold ' + DAYS[0] + ' to ' + DAYS[DAYS.length - 1] +
        ' (' + plural(DAYS.length, 'day') + ' with runs). Day resolution, UTC.'
      : 'No runs in the bundle.';
  }

  function renderStations() {
    var host = byId('stations');
    host.innerHTML = '';
    var counts = stationCounts();
    var keys = allStations();
    keys.forEach(function (key) {
      var count = counts[key] || 0;
      var id = 'st-' + key;
      var box = h('label', {
        class: 'check' + (count ? '' : ' empty'),
        title: count ? '' : 'no runs in the chosen days'
      });
      var input = h('input', { type: 'checkbox', id: id });
      if (view.stations[key]) input.setAttribute('checked', 'checked');
      input.addEventListener('change', function (event) {
        view.stations[key] = event.target.checked;
        writeHash();
        render();
      });
      box.appendChild(input);
      box.appendChild(h('span', { class: 'check-k', text: labelOf(key) }));
      box.appendChild(h('span', { class: 'check-n',
                                  text: count ? String(count) : '—' }));
      host.appendChild(box);
    });

    var quick = byId('station-quick');
    quick.innerHTML = '';
    [['All', true], ['None', false]].forEach(function (pair) {
      var button = h('button', { type: 'button', class: 'view-toggle',
                                 text: pair[0] });
      button.addEventListener('click', function () {
        keys.forEach(function (key) { view.stations[key] = pair[1]; });
        writeHash();
        render();
      });
      quick.appendChild(button);
    });

    var picked = keys.filter(function (key) { return view.stations[key]; });
    byId('stations-sub').textContent = picked.length
      ? plural(picked.length, 'station') + ' picked: ' +
        picked.map(labelOf).join(', ')
      : 'None picked — choose at least one.';
  }

  function tally(rows) {
    var out = { pass: 0, fail: 0, other: 0, units: {} };
    rows.forEach(function (run) {
      if (run.s === 'pass') out.pass += 1;
      else if (run.s === 'fail') out.fail += 1;
      else out.other += 1;
      if (run.d) out.units[run.d] = true;
    });
    out.unitCount = Object.keys(out.units).length;
    var graded = out.pass + out.fail;
    out.yield = graded ? Math.round(1000 * out.pass / graded) / 10 : null;
    return out;
  }

  function renderTiles(rows) {
    var host = byId('tiles');
    host.innerHTML = '';
    var all = tally(rows);
    [['Runs', String(rows.length), plural(all.unitCount, 'distinct unit')],
     ['Passed', String(all.pass), all.yield === null ? 'no graded runs'
        : all.yield + '% of graded'],
     ['Failed', String(all.fail), all.other ? all.other + ' other' : '']
    ].forEach(function (trio) {
      host.appendChild(h('div', { class: 'sheet-tile' }, [
        h('span', { class: 'tile-title', text: trio[0] }),
        h('strong', { class: 'tile-value', text: trio[1] }),
        trio[2] ? h('span', { class: 'tile-sub', text: trio[2] }) : null
      ]));
    });
  }

  function renderBreakdown(rows) {
    var head = byId('breakdown-head'), body = byId('breakdown-body');
    head.innerHTML = ''; body.innerHTML = '';
    var per = {};
    rows.forEach(function (run) {
      (per[run.k] = per[run.k] || []).push(run);
    });
    var keys = Object.keys(per).sort(function (a, b) {
      return per[b].length - per[a].length;
    });
    if (!keys.length) return;

    head.appendChild(h('tr', {}, ['Station', 'Runs', 'Units', 'Passed',
                                  'Failed', 'Yield'].map(function (title, at) {
      return h('th', { class: at ? 'num' : '', text: title });
    })));
    keys.forEach(function (key) {
      var t = tally(per[key]);
      body.appendChild(h('tr', {}, [
        h('td', { text: labelOf(key) }),
        h('td', { class: 'num', text: String(per[key].length) }),
        h('td', { class: 'num', text: String(t.unitCount) }),
        h('td', { class: 'num tone-pass', text: String(t.pass) }),
        h('td', { class: 'num tone-fail', text: String(t.fail) }),
        h('td', { class: 'num',
                  text: t.yield === null ? '—' : t.yield + '%' })
      ]));
    });
  }

  function renderPreview(rows) {
    var head = byId('preview-head'), body = byId('preview-body');
    head.innerHTML = ''; body.innerHTML = '';
    var pick = COLUMNS.filter(function (pair) {
      return PREVIEW_COLUMNS.indexOf(pair[0]) !== -1;
    });
    head.appendChild(h('tr', {}, pick.map(function (pair) {
      return h('th', { text: pair[0] });
    })));
    rows.slice(0, PREVIEW).forEach(function (run) {
      body.appendChild(h('tr', {}, pick.map(function (pair) {
        var value = String(pair[1](run) === null ? '' : pair[1](run));
        var cls = pair[0] === 'Status'
          ? (run.s === 'pass' ? 'tone-pass' : run.s === 'fail' ? 'tone-fail' : '')
          : (pair[0] === 'DUT_SN' || pair[0] === 'Suite' ? 'mono' : '');
        return h('td', { class: cls, text: value });
      })));
    });

    byId('preview-note').textContent = rows.length > PREVIEW
      ? 'Showing the first ' + PREVIEW + ' of ' + rows.length +
        ' rows. The CSV has all ' + rows.length + ', with four more columns ' +
        '(station key, duration, every failed case, and the run link).'
      : rows.length
        ? 'All ' + plural(rows.length, 'row') + ', and the CSV adds four ' +
          'columns: station key, duration, every failed case, and the run link.'
        : 'Nothing selected yet.';
  }

  function renderDownload(rows) {
    var host = byId('download');
    host.innerHTML = '';
    if (!window.FactoryCsv) return;
    var button = h('button', {
      type: 'button', class: 'view-toggle primary',
      text: rows.length ? 'Download CSV (' + rows.length + ' rows)'
                        : 'Nothing to download'
    });
    if (!rows.length) button.setAttribute('disabled', 'disabled');
    button.addEventListener('click', function () {
      var lines = [COLUMNS.map(function (pair) { return pair[0]; })];
      rows.forEach(function (run) {
        lines.push(COLUMNS.map(function (pair) { return pair[1](run); }));
      });
      var picked = Object.keys(view.stations).filter(function (key) {
        return view.stations[key];
      });
      var name = 'runs-' + view.from + '_to_' + view.to +
                 (picked.length === 1 ? '-' + picked[0] : '') + '.csv';
      window.FactoryCsv.download(name, window.FactoryCsv.toCsv(lines));
    });
    host.appendChild(button);
  }

  /* ---------------------------------------------------------------- the URL */

  /* The selection lives in the hash, so a useful view is sendable — the same
   * reason every other page here puts its state there. */
  function writeHash() {
    var picked = Object.keys(view.stations).filter(function (key) {
      return view.stations[key];
    });
    var all = allStations();
    var parts = ['from=' + view.from, 'to=' + view.to];
    if (picked.length !== all.length) parts.push('stations=' + picked.join(','));
    location.replace('#' + parts.join('&'));
  }

  function readHash() {
    var hash = location.hash || '';
    var from = /from=(\d{4}-\d{2}-\d{2})/.exec(hash);
    var to = /to=(\d{4}-\d{2}-\d{2})/.exec(hash);
    var stations = /stations=([a-z0-9_,]+)/.exec(hash);
    var last = DAYS.length ? DAYS[DAYS.length - 1] : null;

    view.from = (from && from[1]) || (last ? shift(last, -6) : null);
    if (DAYS.length && view.from < DAYS[0]) view.from = DAYS[0];
    view.to = (to && to[1]) || last;

    view.stations = {};
    var wanted = stations ? stations[1].split(',') : null;
    allStations().forEach(function (key) {
      view.stations[key] = wanted ? wanted.indexOf(key) !== -1 : true;
    });
  }

  /* -------------------------------------------------------------------- run */

  function render() {
    if (view.from && view.to && view.from > view.to) {
      var swap = view.from; view.from = view.to; view.to = swap;
    }
    renderQuick();
    renderPickers();
    renderStations();
    var rows = selected();
    renderTiles(rows);
    renderBreakdown(rows);
    renderPreview(rows);
    renderDownload(rows);
    byId('take-sub').textContent = rows.length
      ? plural(rows.length, 'run') + ' from ' + view.from + ' to ' + view.to +
        ' (UTC)'
      : 'Widen the days or pick more stations.';
    byId('meta').textContent = view.from && view.to
      ? view.from + ' → ' + view.to + ' UTC' : '';
  }

  function init() {
    if (!byId('stations') || !byId('preview-body')) return;
    if (!RUNS.length) {
      var notice = byId('notice');
      notice.hidden = false;
      notice.textContent =
        'No run bundle — run `make build` and publish, then reload.';
      return;
    }
    readHash();
    /* Written once on load: without it a shared URL has no range in it and the
     * recipient gets "last seven days" relative to their own bundle, which is a
     * different seven days. */
    writeHash();
    var build = DATA.build || {};
    byId('build').textContent = build.release
      ? build.release + ' · ' + build.commit : '';
    byId('footer-meta').textContent =
      'Source: ' + (DATA.source === 'pega' ? 'the station controllers'
                                           : String(DATA.source || '?')) +
      (DATA.collectedAt
        ? ', read ' + String(DATA.collectedAt).replace('T', ' ') : '') +
      '. ' + plural(RUNS.length, 'unit run') + ' in the bundle.';

    ['from', 'to'].forEach(function (which) {
      byId(which).addEventListener('change', function (event) {
        if (!event.target.value) return;
        view[which] = event.target.value;
        writeHash();
        render();
      });
    });
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
