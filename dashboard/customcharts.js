/* Section 5 of the customize page: the station page's charts, over a range and
 * a set of stations rather than one station at a time.
 *
 * WHY THIS IS NOT JUST A LINK TO THE STATION PAGE
 * The station page answers "how is MLT doing" — one station, the collected
 * window, fixed. The question this page exists for is the other one: "how did
 * these four stations do over these eleven days", which no page could answer
 * without picking a station and a range by hand and then adding the numbers up
 * on paper.
 *
 * Three charts, the three the station page has and this one lacked:
 *
 *   Yield by day       — first-pass yield per day, over the selected stations
 *                        together, with the pass/fail/abort mix behind it.
 *   Yield by release   — the same figure sliced by software release, which is
 *                        the slice that answers "did that build help".
 *   Error pareto       — what is actually failing, ranked.
 *
 * Everything is computed from the run bundle the page already loads, over the
 * same selection sections 1 and 2 make, so no number here can disagree with the
 * CSV that section 3 hands out — they are the same rows.
 *
 * FIRST PASS, COUNTED THE SAME WAY EVERYWHERE
 * A run is a first attempt when no earlier graded run exists for that unit at
 * that station inside the window. Window-relative, exactly as build_fpy and the
 * station page do it: a unit first tested before the range looks like a first
 * attempt here, and that is stated rather than silently corrected, because the
 * alternative is a denominator nobody can reconstruct.
 */
(function () {
  'use strict';

  var C = window.FactoryCharts || {};
  var DATA = window.__FACTORY_RUNS__ || window.__FACTORY_RUNS_PEGA__ || {};
  var RUNS = DATA.runs || [];
  var NAMES = DATA.testNames || [];
  var TSTATUS = DATA.testStatuses || [];
  var LABELS = DATA.stationLabels || {};
  var CONTAINERS = {};

  /* Same expression as rootcause.RUN_PREFIX and the all-hands Pareto, so a
     test name groups the same way on every page that ranks failures. */
  var RUN_PREFIX = /^[0-9a-f]{6,10}_(chip\d+_|sohu_)?/i;

  var GRADED = { pass: true, fail: true, error: true };

  var picked = { from: null, to: null, stations: null };

  function byId(id) { return document.getElementById(id); }
  function pct(v) { return C.fmtPct ? C.fmtPct(v) : v; }
  function int(v) { return C.fmtInt ? C.fmtInt(v) : String(v); }

  function utcDay(run) {
    return run.t ? new Date(run.t * 1000).toISOString().slice(0, 10) : '';
  }

  function chosen() {
    return RUNS.filter(function (run) {
      var day = utcDay(run);
      if (!day) return false;
      if (picked.from && day < picked.from) return false;
      if (picked.to && day > picked.to) return false;
      if (picked.stations && picked.stations.indexOf(run.k) === -1) return false;
      return true;
    });
  }

  /* Which runs are somebody's first attempt at their station, inside the
     window. Keyed on unit *and* station: a module that passed MLT and then went
     to HTT is a first attempt at both, and keying on the unit alone would count
     the second one as a retest. */
  function firstAttempts(runs) {
    var earliest = {};
    runs.forEach(function (run) {
      if (!GRADED[run.s]) return;
      var key = run.d + '|' + run.k;
      var at = run.t || 0;
      if (earliest[key] === undefined || at < earliest[key]) earliest[key] = at;
    });
    var first = {};
    runs.forEach(function (run) {
      if (!GRADED[run.s]) return;
      var key = run.d + '|' + run.k;
      if ((run.t || 0) === earliest[key] && !first[key]) first[key] = run;
    });
    return first;
  }

  /* Bucket runs by a key, and count the things every chart here needs. */
  function tally(runs, keyOf) {
    var first = firstAttempts(runs);
    var firstSet = {};
    Object.keys(first).forEach(function (k) { firstSet[first[k].i] = true; });

    var buckets = {};
    runs.forEach(function (run) {
      var key = keyOf(run);
      if (!key) return;
      var b = buckets[key] || (buckets[key] = {
        key: key, runs: 0, pass: 0, fail: 0, abort: 0, graded: 0,
        fpyPass: 0, fpyTotal: 0, units: {}, firstDay: null, lastDay: null
      });
      b.runs += 1;
      b.units[run.d] = true;
      if (run.s === 'pass') b.pass += 1;
      else if (run.s === 'fail') b.fail += 1;
      else if (run.s === 'error') b.abort += 1;
      if (GRADED[run.s]) b.graded += 1;
      if (firstSet[run.i]) {
        b.fpyTotal += 1;
        if (run.s === 'pass') b.fpyPass += 1;
      }
      var day = utcDay(run);
      if (day) {
        if (!b.firstDay || day < b.firstDay) b.firstDay = day;
        if (!b.lastDay || day > b.lastDay) b.lastDay = day;
      }
    });
    return Object.keys(buckets).map(function (key) {
      var b = buckets[key];
      b.unitCount = Object.keys(b.units).length;
      b.fpy = b.fpyTotal ? b.fpyPass / b.fpyTotal : null;
      /* Under twenty first attempts the figure moves a long way on one unit.
         Marked, not withheld — same call the weekly table now makes. */
      b.thin = b.fpyTotal > 0 && b.fpyTotal < 20;
      return b;
    });
  }

  function dayRows(runs) {
    return tally(runs, utcDay)
      .sort(function (a, b) { return a.key < b.key ? -1 : 1; })
      .map(function (b) {
        return {
          label: C.fmtDayShort ? C.fmtDayShort(b.key) : b.key,
          sub: '', heading: b.key,
          pass: b.pass, fail: b.fail, abort: b.abort, total: b.runs,
          fpy: b.fpy, fpyPass: b.fpyPass, fpyTotal: b.fpyTotal, thin: b.thin,
          raw: b
        };
      });
  }

  function releaseRows(runs) {
    return tally(runs, function (run) { return run.r || run.v || ''; })
      .sort(function (a, b) { return b.runs - a.runs; })
      .slice(0, 14)
      .map(function (b) {
        return {
          label: String(b.key), heading: 'Release ' + b.key,
          sub: C.fmtRange ? C.fmtRange(b.firstDay, b.lastDay) : '',
          pass: b.pass, fail: b.fail, abort: b.abort, total: b.runs,
          fpy: b.fpy, fpyPass: b.fpyPass, fpyTotal: b.fpyTotal, thin: b.thin,
          raw: b
        };
      });
  }

  /* Ranked failing test cases. Counted once per run — a case that fails eight
     chips of one module is one failure of that module, not eight, which is the
     same rule the all-hands Pareto and the error table use. */
  function paretoRows(runs) {
    var counts = {}, total = 0;
    runs.forEach(function (run) {
      if (run.s !== 'fail' && run.s !== 'error') return;
      var seen = {};
      (run.T || []).forEach(function (test) {
        var status = TSTATUS[test[1]];
        if (status !== 'fail' && status !== 'error') return;
        if (CONTAINERS[test[0]]) return;
        var name = String(NAMES[test[0]] || '').replace(RUN_PREFIX, '');
        if (!name || seen[name]) return;
        seen[name] = true;
        var entry = counts[name] || (counts[name] = {
          area: name, fails: 0, duts: {}, stations: {} });
        entry.fails += 1;
        entry.duts[run.d] = true;
        entry.stations[run.k] = (entry.stations[run.k] || 0) + 1;
        total += 1;
      });
    });
    var rows = Object.keys(counts).map(function (name) { return counts[name]; })
      .sort(function (a, b) {
        return b.fails - a.fails || a.area.localeCompare(b.area);
      })
      .slice(0, 14);
    var running = 0;
    return rows.map(function (row) {
      running += row.fails;
      return {
        area: row.area,
        fails: row.fails,
        duts: Object.keys(row.duts).length,
        share: total ? row.fails / total : 0,
        cumulativeShare: total ? running / total : 0,
        byStation: Object.keys(row.stations).map(function (k) {
          return { station: k, label: LABELS[k] || k, fails: row.stations[k],
                   duts: 0 };
        }).sort(function (a, b) { return b.fails - a.fails; }),
        byTest: []
      };
    });
  }

  function render() {
    if (!byId('cc-day-plot') || !C.renderMix) return;
    var runs = chosen();

    var days = dayRows(runs);
    var rels = releaseRows(runs);
    var fails = paretoRows(runs);

    byId('cc-sub').textContent = runs.length
      ? int(runs.length) + ' runs over ' + days.length + ' days at '
        + (picked.stations ? picked.stations.length : 'all') + ' stations, '
        + picked.from + ' to ' + picked.to
        + '. First pass is counted per unit per station inside this range — a '
        + 'unit first tested before it looks like a first attempt here.'
      : 'Nothing in this range at the stations picked above.';

    C.renderLegend(byId('cc-day-legend'), C.MIX_SERIES);
    C.renderLegend(byId('cc-rel-legend'), C.MIX_SERIES);
    C.renderLegend(byId('cc-pareto-legend'), [
      { label: 'fails', color: 'var(--series-1)' },
      { label: 'cumulative %', color: 'var(--text-primary)' }
    ]);

    C.renderMix(byId('cc-day-plot'), days, {
      ariaLabel: 'Pass, fail and abort per day over the selected stations',
      emptyText: 'No runs in this range.'
    });
    C.renderTrend(byId('cc-day-fpy'), days, {
      ariaLabel: 'First-pass yield per day over the selected stations'
    });
    C.renderMix(byId('cc-rel-plot'), rels, {
      ariaLabel: 'Pass, fail and abort per software release',
      emptyText: 'No runs in this range.'
    });
    C.renderTrend(byId('cc-rel-fpy'), rels, {
      ariaLabel: 'First-pass yield per software release'
    });
    C.renderPareto(byId('cc-pareto-plot'), fails, {
      ariaLabel: 'Failing test cases, ranked'
    });

    C.renderTable(byId('cc-day-table'), 'By day', [
      { label: 'Day', get: function (r) { return r.raw.key; } },
      { label: 'Runs', get: function (r) { return int(r.total); } },
      { label: 'Units', get: function (r) { return int(r.raw.unitCount); } },
      { label: 'Pass', get: function (r) { return int(r.pass); } },
      { label: 'Fail', get: function (r) { return int(r.fail); } },
      { label: 'FPY', get: function (r) {
          return pct(r.fpy) + (r.thin ? ' *' : ''); } },
      { label: 'First attempts', get: function (r) {
          return r.fpyPass + ' / ' + r.fpyTotal; } }
    ], days);

    C.renderTable(byId('cc-rel-table'), 'By software release', [
      { label: 'Release', get: function (r) { return r.label; } },
      { label: 'Dates', get: function (r) { return r.sub || '—'; } },
      { label: 'Runs', get: function (r) { return int(r.total); } },
      { label: 'Units', get: function (r) { return int(r.raw.unitCount); } },
      { label: 'Fail', get: function (r) { return int(r.fail); } },
      { label: 'FPY', get: function (r) {
          return pct(r.fpy) + (r.thin ? ' *' : ''); } },
      { label: 'First attempts', get: function (r) {
          return r.fpyPass + ' / ' + r.fpyTotal; } }
    ], rels);

    C.renderTable(byId('cc-pareto-table'), 'Failing test cases', [
      { label: 'Test case', get: function (r) { return r.area; } },
      { label: 'Failures', get: function (r) { return int(r.fails); } },
      { label: 'Units', get: function (r) { return int(r.duts); } },
      { label: 'Share', get: function (r) { return pct(r.share, 0); } },
      { label: 'Cumulative', get: function (r) {
          return pct(r.cumulativeShare, 0); } },
      { label: 'Stations', get: function (r) {
          return r.byStation.map(function (s) {
            return s.label + ' ' + s.fails; }).join(', '); } }
    ], fails);
  }

  /* Sections 1 and 2 report their selection here, the same way section 4 is
     told. One selection, three consumers, no chance of the charts describing a
     different range from the CSV. */
  window.FactoryCustomCharts = {
    show: function (from, to, stations) {
      picked.from = from;
      picked.to = to;
      picked.stations = stations ? stations.slice() : null;
      render();
    }
  };
})();
