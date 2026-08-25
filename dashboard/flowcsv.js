/* The station table, as a CSV, from the end-to-end flow.
 *
 * WHY IT IS BUILT AND NOT TYPED
 * The table has two kinds of column. Which controller holds the logs, and which
 * test package is actually running, are facts the controllers already know — and
 * a version number typed into a spreadsheet is stale the next time anybody
 * deploys. So those are read at download time. Everything else is a fact about
 * the line that no controller knows: how many instances exist, which is the
 * canary, who owns it, what the open action is. Those come from flowmeta.js,
 * which is hand-edited on purpose.
 *
 * The station list itself comes from the chart, so the CSV and the drawing
 * cannot disagree about which stages exist. Add a box to flowe2e.js and it
 * appears here on the next download, with its computed columns filled and the
 * hand columns blank — which is the right default: a blank cell asks somebody
 * to fill it, a missing row hides a station.
 */
(function () {
  'use strict';

  var STATIONS = window.__FACTORY_STATIONS__ || {};
  var META = window.__FLOW_STATIONS__ || {};
  var TABLE = window.__FLOW_TABLE_META__ || {};

  /* Which controller each station's logs live on.
     The registry already carries it — stations.py records the controller
     because which physical station ran a suite is the controller's fact, not
     the suite's — so it is read from there rather than kept by hand, where it
     would go stale the first time a station moved. */
  var CONTROLLER = (function () {
    var out = {};
    (STATIONS.stations || []).forEach(function (row) {
      if (row.controller) out[row.key] = row.controller;
    });
    return out;
  })();

  function logHost(key) {
    var host = CONTROLLER[key];
    return host ? host.charAt(0).toUpperCase() + host.slice(1) + ':3000' : '';
  }

  function view(key) {
    return (STATIONS.views || {})[key] || null;
  }

  /* The release actually running at a station: the most recent version the
     controller reported, not the one somebody meant to deploy. */
  function release(key) {
    var got = view(key);
    if (!got) return '';
    var releases = got.releases || [];
    if (!releases.length) return '';
    var newest = releases.slice().sort(function (a, b) {
      return String(b.lastDay || '').localeCompare(String(a.lastDay || ''));
    })[0];
    return newest ? String(newest.release || '') : '';
  }

  var TYPE = {
    test: 'Test', process: 'Process', build: 'Build', pack: 'Pack'
  };

  function rowsFor(chart) {
    var lines = [];

    /* Session one: who this is and where the live drawing is. Two columns, so
       it reads as a header block above the table rather than as data. */
    var today = new Date();
    var stamp = [String(today.getMonth() + 1), String(today.getDate()),
                 today.getFullYear()].map(function (part, index) {
      return index < 2 && part.length < 2 ? '0' + part : part;
    }).join('/');
    lines.push(['Team', TABLE.team || '']);
    lines.push(['Version', TABLE.version || '']);
    lines.push(['Date', stamp]);
    lines.push(['Iterative Flow', TABLE.flow || '']);
    lines.push([]);

    lines.push(['Station Name', 'Station Type', 'Location', 'DUT',
                'Test Pkg Release', 'Test Log Storage', 'Total Amount',
                'Instances', 'Canary Station', 'Status',
                'Action Item in Critical Path', 'Test DRI']);

    /* Two boxes on this chart share a label — the PDB board out of SMT and the
       PDB process check — and two rows called "PDB" in a spreadsheet is a
       reconciliation problem for whoever opens it. The lane disambiguates them
       the way the chart does visually. */
    var seen = {};
    (chart.nodes || []).forEach(function (node) {
      seen[node.label] = (seen[node.label] || 0) + 1;
    });
    var laneName = {};
    (chart.lanes || []).forEach(function (lane) {
      laneName[lane.key] = lane.title;
    });

    (chart.nodes || []).forEach(function (node) {
      var hand = META[node.id] || {};
      var key = node.station || '';
      var name = seen[node.label] > 1
        ? node.label + ' (' + (node.sub || laneName[node.lane] || node.id) + ')'
        : node.label;
      lines.push([
        name,
        TYPE[node.kind] || node.kind || '',
        hand.location || '',
        hand.dut || '',
        key ? release(key) : '',
        key ? logHost(key) : '',
        hand.total || '',
        hand.instances || '',
        hand.canary || '',
        hand.status || '',
        /* The chart's own open question, where it has one, so the CSV and the
           drawing raise the same thing rather than two versions of it. */
        hand.action || node.question || '',
        hand.dri || ''
      ]);
    });
    return lines;
  }

  function attach(chart) {
    var host = document.getElementById('e2e-download');
    if (!host || !window.FactoryCsv) return;
    host.innerHTML = '';
    window.FactoryCsv.attach(host, {
      label: 'Station table (CSV)',
      title: 'every stage on this chart, with the live test package and log '
           + 'host, and the hand-kept columns from flowmeta.js',
      name: function () {
        return 'station-table-' + new Date().toISOString().slice(0, 10)
               + '.csv';
      },
      rows: function () { return rowsFor(chart); }
    });
  }

  window.FactoryFlowCsv = { attach: attach, rows: rowsFor };
})();
