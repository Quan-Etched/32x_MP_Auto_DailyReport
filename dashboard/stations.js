/* Station yield dashboard — daily, release, Pareto, retest.
 *
 * Data is pre-aggregated per station by src/factory/build_stations.py, so this
 * file renders prepared slices rather than re-implementing the metric
 * definitions a second time. The station bar switches slices; nothing here
 * recomputes yield.
 *
 * All label text (suite names, DUT serials, test names) comes from the API and
 * only ever reaches the DOM via textContent.
 */
'use strict';

(function () {

  var DATA = window.__FACTORY_STATIONS__;
  /* The chart library, aliased into the names the rest of this file already
   * uses. These renderers lived here until the weekly page needed the same
   * three; they moved to charts.js and this keeps the call sites unchanged. */
  var C = window.FactoryCharts || {};
  var h = C.h;
  var s = C.s;
  var build = C.build;
  var clear = C.clear;
  var measure = C.measure;
  var fmtInt = C.fmtInt;
  var fmtPct = C.fmtPct;
  var fmtDayShort = C.fmtDayShort;
  var fmtRange = C.fmtRange;
  var dict = C.dict;
  var ago = C.ago;
  var minutesSince = C.minutesSince;
  var niceTicks = C.niceTicks;
  var makeTooltip = C.makeTooltip;
  var attachCursor = C.attachCursor;
  var emptyPlot = C.emptyPlot;
  var barPath = C.barPath;
  var renderMix = C.renderMix;
  var renderTrend = C.renderTrend;
  var renderPareto = C.renderPareto;
  var renderRetestDepth = C.renderRetestDepth;
  var renderTable = C.renderTable;
  var renderLegend = C.renderLegend;
  var MIX_SERIES = C.MIX_SERIES;

  /* ------------------------------------------------------------ drill-down */

  /**
   * Build a runs.html link. Every number on this page is a count of runs, and
   * this is how a reader gets from the number to the rows behind it.
   *
   * Stays here rather than moving to charts.js with the renderers: it names a
   * station from this page's own state, and the chart code deliberately knows
   * nothing about which page it is drawing on.
   *
   * The filter keys are runs.html's, and its semantics are daily.py's — pass
   * `status: 'abort'` for the abort tile (EOS calls that verdict `error`) and
   * `status: 'graded'` for a pass-rate denominator. See build_runs.py.
   */
  function runsHref(extra) {
    var parts = ['station=' + encodeURIComponent(state.station)];
    Object.keys(extra || {}).forEach(function (key) {
      var value = extra[key];
      if (value === null || value === undefined || value === '') return;
      parts.push(key + '=' + encodeURIComponent(value));
    });
    return 'runs.html#' + parts.join('&');
  }

  function drill(extra) { location.href = runsHref(extra); }

  /* Which slice of history every chart on the page is about.
   *
   * '7d' is the default and says so on the control: the page answers "how is
   * the line doing this week", and a month-long average hides the week inside
   * it — a release that landed on Tuesday is all of a 7-day bar and a fifth of
   * a 30-day one. 'all' answers the question the default cannot: whether this
   * week is better or worse than the ones before it.
   *
   * Both are aggregated on the build side and shipped together. A view carries
   * per-release totals and a failure Pareto, neither of which can be recovered
   * by filtering the daily rows in the browser. */
  var state = { station: '__all__', paretoMode: 'pareto', range: '7d',
                area: null };

  function ranges() {
    return (DATA.ranges || {}).options || [];
  }

  /* The whole page reads through these three, so a range is one switch rather
   * than a condition at every call site. */
  function views() {
    return (state.range === 'all' ? DATA.viewsAll : DATA.views) || DATA.views || {};
  }
  function stationList() {
    return (state.range === 'all' ? DATA.stationsAll : DATA.stations) ||
           DATA.stations || [];
  }
  function currentWindow() {
    return (state.range === 'all' ? DATA.windowAll : DATA.window) ||
           DATA.window || {};
  }

  var refs = {
    meta: document.getElementById('meta'),
    freshness: document.getElementById('freshness'),
    notice: document.getElementById('notice'),
    bar: document.getElementById('stationbar'),
    note: document.getElementById('station-note'),
    tiles: document.getElementById('tiles'),
    retestTiles: document.getElementById('retest-tiles'),
    footer: document.getElementById('footer-meta'),
    theme: document.getElementById('theme-toggle'),
    paretoSub: document.getElementById('pareto-sub'),
    rangeBar: document.getElementById('rangebar')
  };


  /* ------------------------------------------------------- reconciliation */

  /* The two station pages disagree, and the first question anyone asks about a
   * yield number is whether it is right. This is the answer, computed from both
   * bundles on every build rather than written down once: what each source says
   * per station, and why they differ. It sits at the very bottom because it is
   * evidence to point at when challenged, not something to read first. */
  function renderReconcile() {
    var c = DATA.comparison;
    var host = document.getElementById('reconcile');
    if (!host || !c || !c.rows || !c.rows.length) return;
    host.hidden = false;
    clear(host);

    host.appendChild(h('h2', { class: 'rec-title',
      text: 'Why this page and the direct page disagree' }));

    var t = c.totals || {};
    host.appendChild(h('p', { class: 'rec-lede' }, [
      document.createTextNode(
        'This page reads OCP/EOS, which records one run per fixture. ' +
        'The direct page reads the station controllers, which record one ' +
        'result per unit — a fixture drives eight modules. So the same work ' +
        'is '),
      h('strong', { text: fmtInt(t.eosRuns) + ' runs here and ' +
                          fmtInt(t.pegaRuns) + ' there' }),
      document.createTextNode(
        ', and a fixture where one chip failed is one failure on this page ' +
        'and seven passes plus one failure on that one. Neither is wrong; the ' +
        'line asks the second question.')
    ]));

    var table = h('table', { class: 'rec-table' });
    var head = h('tr', {}, [
      h('th', { scope: 'col', text: 'Station' }),
      h('th', { scope: 'col', class: 'num', text: 'Runs here' }),
      h('th', { scope: 'col', class: 'num', text: 'Pass rate' }),
      h('th', { scope: 'col', class: 'num', text: 'Units, direct' }),
      h('th', { scope: 'col', class: 'num', text: 'Pass rate' }),
      h('th', { scope: 'col', class: 'num', text: 'Ratio' })
    ]);
    table.appendChild(h('thead', {}, [head]));

    var body = h('tbody', {});
    c.rows.forEach(function (row) {
      var missing = (!row.eosRuns && row.pegaRuns) || (row.eosRuns && !row.pegaRuns);
      body.appendChild(h('tr', { class: missing ? 'gap' : '' }, [
        h('td', { text: row.label }),
        h('td', { class: 'num', text: fmtInt(row.eosRuns) }),
        h('td', { class: 'num', text: row.eosRate === null || row.eosRate === undefined
          ? '—' : fmtPct(row.eosRate) }),
        h('td', { class: 'num', text: fmtInt(row.pegaRuns) }),
        h('td', { class: 'num', text: row.pegaRate === null || row.pegaRate === undefined
          ? '—' : fmtPct(row.pegaRate) }),
        h('td', { class: 'num', text: row.expansion ? row.expansion + '\u00d7' : '—' })
      ]));
    });
    table.appendChild(body);
    host.appendChild(h('div', { class: 'table-wrap' }, [table]));

    var notes = h('ul', { class: 'rec-notes' });
    [
      ['One run, eight units.', 'EOS gives a run one dutSerial and no slot ' +
        'number, so seven of every eight modules in a fixture are anonymous ' +
        'to it. The controllers return all eight. That is the whole of the ' +
        'MLT and HTT difference.'],
      ['A fixture verdict is not a unit verdict.', 'Run status describes the ' +
        'whole fixture, so one bad chip fails it. This page already derives a ' +
        'unit-level figure from the per-chip test names — ' +
        (t.eosUnitYield ? fmtPct(t.eosUnitYield) : 'the Unit yield tile') +
        ' line-wide — and it agrees with the direct page rather than with the ' +
        'run-level number above it. Two independent routes to the same answer.'],
      ['Neither page is complete.', 'L11 is empty here because EOS returns ' +
        'HTTP 502 for that level; Chip Screening and SLT are empty on the ' +
        'direct page because no controller we read reports them under those ' +
        'names. Rows where one side has nothing are marked.'],
      ['Checked against the line\u2019s own record.', 'Rebuilding 2026-08-12 ' +
        'from the controllers reproduced the hand-kept tracker exactly: 51 of ' +
        '51 units, 92 verdicts, no disagreement, from the same 14 suite runs ' +
        'the sheet cites.']
    ].forEach(function (pair) {
      notes.appendChild(h('li', {}, [
        h('strong', { text: pair[0] + ' ' }),
        document.createTextNode(pair[1])
      ]));
    });
    host.appendChild(notes);

    host.appendChild(h('p', { class: 'rec-foot' }, [
      document.createTextNode('Computed on every build from both bundles — '),
      h('a', { href: 'index.html', text: 'open the controller-sourced page' }),
      document.createTextNode(' to check any figure above against its own charts.')
    ]));
  }

  /* ------------------------------------------------------------- freshness */

  function renderFreshness() {
    var f = DATA.fetch || {};
    clear(refs.freshness);

    var fetchMins = minutesSince(f.lastFetchAttemptAt || f.lastFetchAt);
    var fetchState = f.lastFetchStatus === 'error' ? 'bad'
      : (fetchMins > 130 ? 'stale' : 'ok');       // hourly job: >2h is late
    var updateMins = minutesSince(f.lastUpdateAt);
    var updateState = updateMins > 360 ? 'stale' : 'ok';   // 6h of no new data

    refs.freshness.appendChild(cell('Last fetch', fetchState,
      ago(f.lastFetchAttemptAt || f.lastFetchAt) || 'never',
      f.lastFetchStatus === 'error'
        ? 'failed — ' + String(f.lastFetchError || '').slice(0, 90)
        : (f.lastFetchAttemptAt || '—')));

    refs.freshness.appendChild(cell('Last update', updateState,
      ago(f.lastUpdateAt) || 'never',
      f.consecutiveNoChange
        ? 'unchanged for ' + f.consecutiveNoChange + ' consecutive fetch' +
          (f.consecutiveNoChange === 1 ? '' : 'es')
        : 'data changed on the last fetch'));

    /* Where these numbers come from. Two pages now render this same layout
     * from different systems, and a reader landing on one of them has no way
     * to tell which — so each says, with a link to the tool. */
    var src = DATA.dataSource || {};
    if (src.label) {
      var value = src.url
        ? h('a', { class: 'v src', href: src.url, target: '_blank',
                   rel: 'noopener noreferrer', text: src.label })
        : h('div', { class: 'v', text: src.label });
      refs.freshness.appendChild(h('div', { class: 'cell' }, [
        h('div', { class: 'k', text: 'Data source' }),
        value,
        h('div', { class: 'sub2', text: src.note || '' })
      ]));
    }

    var strip = h('div', { class: 'fetchstrip' });
    (f.history || []).slice(-48).forEach(function (entry) {
      strip.appendChild(h('i', {
        class: entry.status === 'error' ? 'error' : (entry.changed ? 'changed' : 'same'),
        style: 'height:' + (entry.status === 'error' ? 26 : entry.changed ? 22 : 10) + 'px',
        title: entry.at + (entry.status === 'error' ? ' — fetch failed'
          : entry.changed ? ' — updated' : ' — no change')
      }));
    });
    var histCell = h('div', { class: 'cell' }, [
      h('div', { class: 'k', text: 'Recent fetches' }), strip,
      h('div', { class: 'sub2', text: (f.totalFetches || 0) + ' total · tall = data changed' })
    ]);
    refs.freshness.appendChild(histCell);

    // "All stations" has no per-station entry; report the newest station update
    // so the cell answers "has anything on the line moved?".
    var perStation = f.stations || {};
    if (state.station === '__all__') {
      var newest = null, totalRuns = 0;
      Object.keys(perStation).forEach(function (key) {
        if (key === 'unclassified') return;
        totalRuns += perStation[key].runs || 0;
        var at = perStation[key].lastUpdateAt;
        if (at && (!newest || at > newest)) newest = at;
      });
      refs.freshness.appendChild(cell('Newest station data', newest ? 'ok' : 'stale',
        ago(newest) || 'never', totalRuns + ' runs across all stations'));
      return;
    }

    var st = perStation[state.station];
    var station = currentStation();
    refs.freshness.appendChild(cell('This station', st && st.runs ? 'ok' : 'stale',
      st && st.runs ? (ago(st.lastUpdateAt) || 'never') : stateWord(station),
      st && st.runs ? (st.runs + ' runs in window')
        : (station.blockedBy ? 'EOS refused this level' : 'nothing collected')));
  }

  function cell(k, tone, value, sub) {
    return h('div', { class: 'cell' }, [
      h('div', { class: 'k', text: k }),
      h('div', { class: 'v' }, [h('span', { class: 'dot ' + tone }), h('span', { text: value })]),
      h('div', { class: 'sub2', text: sub || '' })
    ]);
  }

  /* ---------------------------------------------------------- station bar */

  function renderStationBar() {
    clear(refs.bar);
    stationList().forEach(function (station) {
      var empty = !station.runs;
      var btn = h('button', {
        type: 'button',
        class: empty ? 'empty' : '',
        'aria-pressed': station.key === state.station ? 'true' : 'false',
        onclick: function () {
          state.station = station.key;
          var next = '#station=' + encodeURIComponent(station.key);
          if (window.history && history.replaceState) history.replaceState(null, '', next);
          else location.hash = next;
          render();
        }
      }, [
        h('span', { text: station.label }),
        h('span', { class: 'n', text: empty ? stateWord(station) : String(station.runs) })
      ]);
      refs.bar.appendChild(btn);
    });
  }

  /* The range control. Above the station chips because it governs them too —
   * the run count on every chip is for the range that is selected. */
  function renderRangeBar() {
    if (!refs.rangeBar) return;
    var options = ranges();
    if (options.length < 2) return;          /* an older bundle: nothing to pick */
    clear(refs.rangeBar);
    refs.rangeBar.appendChild(h('span', { class: 'range-label', text: 'Range' }));

    options.forEach(function (option) {
      var on = option.key === state.range;
      var btn = h('button', {
        type: 'button',
        'aria-pressed': on ? 'true' : 'false',
        onclick: function () {
          if (state.range === option.key) return;
          state.range = option.key;
          render();
        }
      }, [
        h('span', { text: option.label }),
        /* "default" on one and "since 2026-08-01" on the other. Both come
         * from the bundle, so the floor the build actually used is the floor
         * the page claims. */
        option.note ? h('span', { class: 'n', text: option.note }) : null
      ]);
      refs.rangeBar.appendChild(btn);
    });

    var w = currentWindow();
    refs.rangeBar.appendChild(h('span', {
      class: 'range-window',
      text: (w.from || '?') + ' → ' + (w.to || '?') +
            (w.days ? '  ·  ' + w.days + (w.days === 1 ? ' day' : ' days') + ' with runs' : '')
    }));
  }

  /* The open breakdown, kept in state so switching station or range re-opens
   * the same area rather than silently closing it — the question "and what
   * about C2C on HTT" is one click, not two. */
  function showArea(row) {
    var host = document.getElementById('pareto-detail');
    if (!host) return;
    state.area = row ? row.area : null;
    C.renderAreaDetail(host, row, {
      dutHref: function (dut) { return runsHref({ dut: dut, status: 'fail' }); },
      onClose: function () { state.area = null; C.renderAreaDetail(host, null); }
    });
  }

  function stateWord(station) {
    if (station.state === 'blocked') return 'no access';
    if (station.state === 'unmapped') return 'not mapped';
    return '0';
  }

  function currentStation() {
    var list = stationList();
    for (var i = 0; i < list.length; i += 1) if (list[i].key === state.station) return list[i];
    return list[0] || { key: '__all__', label: 'All stations' };
  }

  /* ----------------------------------------------------------------- views */

  function render() {
    var station = currentStation();
    var view = views()[station.key] || emptyView();

    renderRangeBar();
    renderStationBar();
    /* The masthead says which window the numbers are for, so a screenshot of
     * this page carries its own range rather than depending on the control
     * being in the frame. */
    var w = currentWindow();
    refs.meta.textContent = (w.from || '?') + ' → ' + (w.to || '?') +
      '  ·  ' + DATA.timezone;
    renderFreshness();
    renderReconcile();
    renderNote(station);
    renderTiles(view.summary, station, view.units);

    var dailyRows = (view.daily || []).map(function (r) {
      return {
        label: fmtDayShort(r.day), sub: '', heading: r.day,
        pass: r.pass, fail: r.fail, abort: r.abort, total: r.runs,
        fpy: r.fpy, fpyPass: r.fpyPass, fpyTotal: r.fpyTotal, thin: r.thin, raw: r
      };
    });

    var relRows = (view.releases || []).map(function (r) {
      return {
        label: String(r.release), sub: fmtRange(r.firstDay, r.lastDay),
        heading: 'Release ' + r.release,
        pass: r.pass, fail: r.fail, abort: r.abort, total: r.runs,
        fpy: r.fpy, fpyPass: r.fpyPass, fpyTotal: r.fpyTotal, thin: r.thin, raw: r
      };
    });

    renderLegend(document.getElementById('legend-daily-mix'), MIX_SERIES);
    renderLegend(document.getElementById('legend-rel-mix'), MIX_SERIES);

    renderMix(document.getElementById('plot-daily-mix'), dailyRows, {
      ariaLabel: 'Pass, fail and abort counts per day. Click a bar for its runs',
      onSelect: function (row) { drill({ day: row.raw.day }); }
    });
    renderTrend(document.getElementById('plot-daily-fpy'), dailyRows, {
      ariaLabel: 'First-pass yield per day. Click a point for its first attempts',
      onSelect: function (row) {
        drill({ day: row.raw.day, attempt: 'first', status: 'graded' });
      }
    });
    renderMix(document.getElementById('plot-rel-mix'), relRows, {
      ariaLabel: 'Pass, fail and abort counts per software release. Click a bar for its runs',
      axisTitle: 'RELEASE · DATE RANGE TESTED',
      onSelect: function (row) { drill({ release: row.raw.release }); }
    });
    renderTrend(document.getElementById('plot-rel-fpy'), relRows, {
      ariaLabel: 'First-pass yield per software release. Click a point for its first attempts',
      onSelect: function (row) {
        drill({ release: row.raw.release, attempt: 'first', status: 'graded' });
      }
    });

    var paretoRows = view[state.paretoMode] || [];
    refs.paretoSub.textContent = state.paretoMode === 'pareto'
      ? 'Every failing test occurrence, bucketed by root-cause area'
      : 'One area per failing run — the first failure that stopped the unit';
    renderLegend(document.getElementById('legend-pareto'), [
      { label: 'fails', color: 'var(--series-1)' },
      { label: 'cumulative %', color: 'var(--text-primary)' }
    ]);
    /* Clicking a bar opens the breakdown under the chart rather than
     * navigating away: the reader is comparing areas, and a drill-through
     * would cost them the chart they were reading. The serials inside it do
     * navigate — that is the point at which they want the rows. */
    renderPareto(document.getElementById('plot-pareto'), paretoRows, {
      onSelect: function (row) { showArea(row); }
    });
    if (state.area) {
      var again = null;
      for (var pi = 0; pi < paretoRows.length; pi++) {
        if (paretoRows[pi].area === state.area) again = paretoRows[pi];
      }
      showArea(again);          /* null when the new view has no such area */
    }

    renderRetest(view);
    renderTables(dailyRows, relRows, paretoRows, view);
  }

  function emptyView() {
    return {
      summary: { runs: 0, pass: 0, fail: 0, abort: 0, graded: 0, units: 0,
                 fpy: null, passRate: null, fpyPass: 0, fpyTotal: 0 },
      daily: [], releases: [], pareto: [], firstFailure: [],
      retest: { units: 0, retestedUnits: 0, retestRate: null, recoveryRate: null,
                failedFirst: 0, recovered: 0, stillFailing: 0, totalRetestRuns: 0, depth: [] },
      retestDetail: [], retestDetailTruncated: 0
    };
  }

  function renderNote(station) {
    var bits = [];
    if (station.blockedBy) {
      bits.push(h('div', null, [
        h('b', { text: station.label + ' is unavailable. ' }),
        h('span', { text: 'EOS refused the request for this level: ' }),
        h('code', { text: String(station.blockedBy).slice(0, 300) })
      ]));
    } else if (station.state === 'unmapped') {
      bits.push(h('div', null, [
        h('b', { text: station.label + ' is not mapped. ' }),
        h('span', { text: station.note || '' })
      ]));
    } else if (station.state === 'unclassified' || (station.note && !station.runs)) {
      bits.push(h('div', null, [h('span', { text: station.note || '' })]));
    } else if (station.note && station.key !== '__all__') {
      bits.push(h('div', { text: station.note }));
    }

    clear(refs.note);
    if (!bits.length) { refs.note.hidden = true; return; }
    bits.forEach(function (b) { refs.note.appendChild(b); });
    refs.note.hidden = false;
  }

  /**
   * Headline tiles. Each value drills into exactly the population it counts, so
   * the row count on runs.html always reconciles with the number clicked: the
   * FPY tile carries its own denominator (graded first attempts), the pass-rate
   * tile carries all graded runs, and abort means `status=error`.
   */
  function renderTiles(summary, station, units) {
    clear(refs.tiles);
    var specs = [
      { label: 'Runs', value: fmtInt(summary.runs), n: summary.runs,
        note: fmtInt(summary.units) + ' distinct units', filter: {} },
      { label: 'First-pass yield', value: fmtPct(summary.fpy), n: summary.fpyTotal,
        note: summary.fpyPass + ' / ' + summary.fpyTotal + ' first attempts',
        filter: { attempt: 'first', status: 'graded' } },
      { label: 'Pass rate', value: fmtPct(summary.passRate), n: summary.graded,
        note: summary.pass + ' / ' + summary.graded + ' graded',
        filter: { status: 'graded' } },
      { label: 'Fail', value: fmtInt(summary.fail), n: summary.fail,
        note: 'unit verdict', filter: { status: 'fail' } },
      { label: 'Abort', value: fmtInt(summary.abort), n: summary.abort,
        note: 'harness error', filter: { status: 'abort' } }
    ];
    /* Unit yield, beside run yield rather than instead of it.
     *
     * A module fixture drives eight chips and EOS scores the fixture: one bad
     * chip is one failed run here and one failed unit of eight on the line's
     * own tracker. Both are true about different populations, so both are
     * shown, and the tile says which is which. It has no drill-down because
     * runs.html filters runs — there is no per-chip row to link to. */
    if (units && units.yield !== null && units.yield !== undefined && units.units) {
      specs.push({
        label: 'Unit yield', value: fmtPct(units.yield), n: 0,
        note: units.passed + ' / ' + (units.passed + units.failed) +
              ' chips, across ' + fmtInt(units.runs) + ' fixture runs',
        filter: {}
      });
    }

    specs.forEach(function (spec) {
      // A zero has nothing to drill into; linking it would promise rows that do
      // not exist.
      var value = spec.n
        ? h('a', {
            class: 'value drill', href: runsHref(spec.filter), text: spec.value,
            title: 'Show the ' + fmtInt(spec.n) + ' runs behind this number'
          })
        : h('div', { class: 'value', text: spec.value });
      refs.tiles.appendChild(h('div', { class: 'card tile' }, [
        h('div', { class: 'label', text: spec.label }),
        value,
        h('div', { class: 'foot' }, [h('span', { class: 'delta', text: spec.note })])
      ]));
    });
    void station;
  }

  function renderRetest(view) {
    var r = view.retest || {};
    clear(refs.retestTiles);
    [
      { k: 'Units entered', v: fmtInt(r.units), s: 'distinct DUT serials' },
      { k: 'Units retested', v: fmtInt(r.retestedUnits), s: fmtPct(r.retestRate, 0) + ' of units' },
      { k: 'Extra runs', v: fmtInt(r.totalRetestRuns), s: 'beyond the first attempt' },
      { k: 'Recovered', v: fmtPct(r.recoveryRate, 0),
        s: r.recovered + ' of ' + r.failedFirst + ' that failed first' },
      { k: 'Still failing', v: fmtInt(r.stillFailing), s: 'last attempt not a pass' }
    ].forEach(function (t) {
      refs.retestTiles.appendChild(h('div', { class: 'cell' }, [
        h('div', { class: 'k', text: t.k }),
        h('div', { class: 'v', text: t.v }),
        h('div', { class: 'sub2', text: t.s })
      ]));
    });
    renderRetestDepth(document.getElementById('plot-retest'), r.depth);
  }

  function renderTables(dailyRows, relRows, paretoRows, view) {
    // Day and release are the two slices people ask each other for by name
    // ("what happened on 8/11?", "how is 220 doing?"), so every count in these
    // tables is a link to exactly those runs.
    var byDay = function (extra) {
      return function (r) { return runsHref(dict({ day: r.raw.day }, extra)); };
    };
    var byRelease = function (extra) {
      return function (r) { return runsHref(dict({ release: r.raw.release }, extra)); };
    };

    renderTable(document.getElementById('table-daily-mix'), 'Pass / fail / abort by day', [
      { label: 'Day', get: function (r) { return r.raw.day; }, href: byDay() },
      { label: 'Runs', get: function (r) { return fmtInt(r.total); }, href: byDay() },
      { label: 'Pass', get: function (r) { return fmtInt(r.pass); }, href: byDay({ status: 'pass' }) },
      { label: 'Fail', get: function (r) { return fmtInt(r.fail); }, href: byDay({ status: 'fail' }) },
      { label: 'Abort', get: function (r) { return fmtInt(r.abort); }, href: byDay({ status: 'abort' }) },
      { label: 'Units', get: function (r) { return fmtInt(r.raw.units); } }
    ], dailyRows);

    renderTable(document.getElementById('table-daily-fpy'), 'First-pass yield by day', [
      { label: 'Day', get: function (r) { return r.raw.day; }, href: byDay() },
      { label: 'FPY', get: function (r) { return fmtPct(r.fpy); },
        href: byDay({ attempt: 'first', status: 'graded' }) },
      { label: 'First attempts', get: function (r) { return r.fpyPass + ' / ' + r.fpyTotal; },
        href: byDay({ attempt: 'first', status: 'graded' }) },
      { label: 'Sample', get: function (r) { return r.thin ? 'thin' : 'graded'; } }
    ], dailyRows);

    renderTable(document.getElementById('table-rel-mix'), 'Pass / fail / abort by release', [
      { label: 'Release', get: function (r) { return r.label; }, href: byRelease() },
      { label: 'Dates', get: function (r) { return r.sub || '—'; } },
      { label: 'Runs', get: function (r) { return fmtInt(r.total); }, href: byRelease() },
      { label: 'Pass', get: function (r) { return fmtInt(r.pass); }, href: byRelease({ status: 'pass' }) },
      { label: 'Fail', get: function (r) { return fmtInt(r.fail); }, href: byRelease({ status: 'fail' }) },
      { label: 'Abort', get: function (r) { return fmtInt(r.abort); }, href: byRelease({ status: 'abort' }) }
    ], relRows);

    renderTable(document.getElementById('table-rel-fpy'), 'First-pass yield by release', [
      { label: 'Release', get: function (r) { return r.label; }, href: byRelease() },
      { label: 'Dates', get: function (r) { return r.sub || '—'; } },
      { label: 'FPY', get: function (r) { return fmtPct(r.fpy); },
        href: byRelease({ attempt: 'first', status: 'graded' }) },
      { label: 'First attempts', get: function (r) { return r.fpyPass + ' / ' + r.fpyTotal; },
        href: byRelease({ attempt: 'first', status: 'graded' }) },
      { label: 'Sample', get: function (r) { return r.thin ? 'thin' : 'graded'; } }
    ], relRows);

    renderTable(document.getElementById('table-pareto'), 'Failure Pareto by root-cause area', [
      { label: 'Root-cause area', get: function (r) { return r.area; } },
      { label: 'Fails', get: function (r) { return fmtInt(r.fails); } },
      { label: 'Share', get: function (r) { return fmtPct(r.share); } },
      { label: 'Cumulative', get: function (r) { return fmtPct(r.cumulativeShare); } },
      { label: 'DUTs', get: function (r) { return fmtInt(r.duts); } },
      { label: 'Top test', get: function (r) { return r.topTest || '—'; } }
    ], paretoRows);

    var detail = view.retestDetail || [];
    renderTable(document.getElementById('table-retest'),
      'Units by attempt count' + (view.retestDetailTruncated
        ? ' (showing ' + detail.length + '; ' + view.retestDetailTruncated + ' more)' : ''), [
      { label: 'DUT serial', get: function (r) { return r.dut; } },
      { label: 'Attempts', get: function (r) { return fmtInt(r.attempts); } },
      { label: 'First', get: function (r) { return r.firstStatus; } },
      { label: 'Last', get: function (r) { return r.lastStatus; } },
      { label: 'Fails', get: function (r) { return fmtInt(r.failures); } },
      { label: 'From', get: function (r) { return r.firstDay || '—'; } },
      { label: 'To', get: function (r) { return r.lastDay || '—'; } },
      { label: 'Releases', get: function (r) { return (r.releases || []).join(', ') || '—'; } }
    ], detail);
  }

  /* ---------------------------------------------------------------- wiring */

  function wire() {
    document.addEventListener('click', function (e) {
      var toggle = e.target.closest('.view-toggle');
      if (toggle) {
        var card = toggle.getAttribute('data-toggle');
        var table = document.getElementById('table-' + card);
        var plot = document.getElementById('plot-' + card);
        var show = toggle.getAttribute('aria-pressed') !== 'true';
        toggle.setAttribute('aria-pressed', show ? 'true' : 'false');
        toggle.textContent = show ? 'Chart' : 'Table';
        table.hidden = !show;
        if (plot) plot.hidden = show;
        return;
      }
      var mode = e.target.closest('button[data-pareto]');
      if (mode) {
        state.paretoMode = mode.getAttribute('data-pareto');
        Array.prototype.forEach.call(
          mode.parentNode.querySelectorAll('button'),
          function (b) { b.setAttribute('aria-pressed', b === mode ? 'true' : 'false'); });
        render();
      }
    });

    var initial = document.documentElement.getAttribute('data-theme');
    refs.theme.textContent = 'Theme: ' + (initial || 'system');
    refs.theme.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme');
      var next = cur === 'dark' ? 'light' : cur === 'light' ? null : 'dark';
      if (next) document.documentElement.setAttribute('data-theme', next);
      else document.documentElement.removeAttribute('data-theme');
      refs.theme.textContent = 'Theme: ' + (next || 'system');
      render();
    });

    var timer;
    window.addEventListener('resize', function () {
      clearTimeout(timer);
      timer = setTimeout(render, 140);
    });

    // The selected station lives in the hash, so "look at L10 RIN" is a link
    // rather than an instruction. Back/forward move between stations.
    window.addEventListener('hashchange', function () {
      var next = stationFromHash();
      if (next !== state.station) { state.station = next; render(); }
    });
  }

  /* Unknown keys fall back to All stations rather than rendering an empty page
   * for a station that no longer exists in the registry. */
  function stationFromHash() {
    var match = /(?:^|[#&])station=([^&]+)/.exec(location.hash || '');
    var key = match ? decodeURIComponent(match[1]) : '';
    var known = DATA.views || {};
    return key && Object.prototype.hasOwnProperty.call(known, key) ? key : '__all__';
  }

  function boot() {
    if (!DATA || !DATA.views) {
      document.getElementById('content').appendChild(h('div', { class: 'card empty' },
        'No stations bundle found. Run `make refresh` (live) or `make demo` (synthetic).'));
      return;
    }
    var w = DATA.window || {};
    refs.meta.textContent = (w.from || '?') + ' → ' + (w.to || '?') + '  ·  ' + DATA.timezone;

    if (DATA.source === 'demo') {
      refs.notice.hidden = false;
      refs.notice.appendChild(h('span', { class: 'icon', 'aria-hidden': 'true', text: '⚠' }));
      refs.notice.appendChild(h('span', null, [
        h('strong', { text: 'Demo data. ' }),
        'Synthetic runs, not factory output.'
      ]));
    }

    refs.footer.textContent = 'Built ' + (DATA.generatedAt || 'unknown') +
      ' from a collection at ' + (DATA.collectedAt || 'unknown') + '.';

    state.station = stationFromHash();
    wire();
    render();
  }

  boot();
})();
