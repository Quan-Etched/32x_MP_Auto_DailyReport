/* Retests: who came back, on which build, and how it ended.
 *
 * WHY THE TABLE IS SHAPED LIKE THIS
 * The first version copied the workbook's retest tab literally — first attempt
 * on the left, retest on the right, sixteen columns. That shape assumes a unit
 * was re-run exactly once, and most of these were not: four attempts across
 * three builds is common here, and "first and last" throws away the middle,
 * which is where the version changed. So a row is one unit at one station, and
 * its attempts are a chain read left to right.
 *
 * The Sankey answers the question a table cannot without the reader adding up
 * rows: when the same unit comes back, which build does it come back on, and
 * does changing the build change the outcome.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RETEST__ || {};
  var ROWS = DATA.rows || [];
  var STATIONS = [['mlt', 'MLT'], ['htt', 'HTT']];

  var filter = null;      /* the chip: which traces the diagram is drawn from */
  var picked = null;      /* a node or ribbon clicked on the diagram */

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
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
            h('span', { class: 'rt-k', text: 'Came back' }),
            h('strong', { class: 'rt-v', text: pct(s.retestRate) }),
            h('span', { class: 'rt-s', text: s.retested + ' units re-run, ' +
              s.retestPassed + ' passing in the end' })
          ])
        ]),
        h('span', { class: 'rt-note', text: s.recovered +
          ' unit' + (s.recovered === 1 ? '' : 's') + ' failed first and passed ' +
          'later. The rest of the re-runs bought no unit — they were station ' +
          'time spent on units that were already good or are still bad.' })
      ]));
    });
  }

  /* --------------------------------------------------------------- sankey */

  /* Aggregated from the rows on screen rather than shipped pre-computed, so
   * filtering to MLT redraws the diagram for MLT. Three stages: the build a
   * unit first ran, the build it was re-run on, and how it ended.
   *
   * Hand-drawn rather than pulled from a library: the page has to work with no
   * network, and three stages of ribbons is less code than a dependency.
   */
  function sankeyFrom(rows) {
    var order = [], nodes = {}, flows = {}, ends = {};

    function node(label, stage) {
      var id = stage + '|' + label;
      if (!nodes[id]) {
        nodes[id] = { id: id, stage: stage, label: label, in: 0, out: 0 };
        order.push(id);
      }
      return nodes[id];
    }

    rows.forEach(function (row) {
      var from = row.stationLabel + ' ' + row.firstBuildShort;
      var to = row.stationLabel + ' ' + row.lastBuildShort;
      flows[from + '\u0000' + to] = (flows[from + '\u0000' + to] || 0) + 1;
      ends[to + '\u0000' + row.outcome] = (ends[to + '\u0000' + row.outcome] || 0) + 1;
    });

    var links = [];
    Object.keys(flows).sort(function (a, b) { return flows[b] - flows[a]; })
      .forEach(function (key) {
        var pair = key.split('\u0000');
        links.push({ source: node(pair[0], 0).id, target: node(pair[1], 1).id,
                     value: flows[key] });
      });
    Object.keys(ends).sort(function (a, b) { return ends[b] - ends[a]; })
      .forEach(function (key) {
        var pair = key.split('\u0000');
        links.push({ source: node(pair[0], 1).id, target: node(pair[1], 2).id,
                     value: ends[key], outcome: pair[1] });
      });

    return { nodes: order.map(function (id) { return nodes[id]; }), links: links };
  }

  function renderSankey(rows) {
    var host = byId('sankey');
    host.innerHTML = '';
    if (!rows.length) { host.hidden = true; return; }
    host.hidden = false;

    var data = sankeyFrom(rows);
    var nodes = data.nodes, links = data.links;

    var W = 1120, PAD = 8, NODE_W = 13, GAP = 9;
    var byKey = {};
    nodes.forEach(function (n) { byKey[n.id] = n; n.in = 0; n.out = 0; });
    links.forEach(function (l) {
      byKey[l.source].out += l.value;
      byKey[l.target].in += l.value;
    });
    nodes.forEach(function (n) { n.value = Math.max(n.in, n.out); });

    var perStage = [0, 1, 2].map(function (s) {
      return nodes.filter(function (n) { return n.stage === s; })
                  .sort(function (a, b) { return b.value - a.value; });
    });
    var tallest = Math.max.apply(null, perStage.map(function (col) {
      return col.reduce(function (sum, n) { return sum + n.value; }, 0);
    })) || 1;
    var maxRows = Math.max.apply(null, perStage.map(function (c) { return c.length; }));
    var H = Math.max(260, tallest * 3.1 + maxRows * GAP + PAD * 2);
    var scale = (H - PAD * 2 - Math.max(0, maxRows - 1) * GAP) / tallest;

    perStage.forEach(function (col, index) {
      var y = PAD;
      col.forEach(function (n) {
        n.x = index === 0 ? 150 : index === 1 ? W / 2 - NODE_W / 2 : W - 150 - NODE_W;
        n.y = y;
        n.h = Math.max(3, n.value * scale);
        n.sourceY = n.y;
        n.targetY = n.y;
        y += n.h + GAP;
      });
    });

    var frame = svg('svg', {
      viewBox: '0 0 ' + W + ' ' + Math.ceil(H), class: 'sk',
      preserveAspectRatio: 'xMidYMin meet'
    });

    /* Widest ribbons first, so a thin flow is never hidden under a fat one. */
    links.slice().sort(function (a, b) { return b.value - a.value; })
      .forEach(function (l) {
        var s = byKey[l.source], tn = byKey[l.target];
        var sh = l.value * scale, th = l.value * scale;
        var y0 = s.sourceY, y1 = tn.targetY;
        s.sourceY += sh; tn.targetY += th;
        var x0 = s.x + NODE_W, x1 = tn.x, mid = (x0 + x1) / 2;
        var path = svg('path', {
          d: 'M' + x0 + ',' + y0 + ' C' + mid + ',' + y0 + ' ' + mid + ',' + y1 +
             ' ' + x1 + ',' + y1 + ' L' + x1 + ',' + (y1 + th) +
             ' C' + mid + ',' + (y1 + th) + ' ' + mid + ',' + (y0 + sh) +
             ' ' + x0 + ',' + (y0 + sh) + ' Z',
          class: 'sk-link sk-pick ' + outcomeClass(l.outcome) +
                 (picked && picked.id === linkKey(s, tn) ? ' on' : ''),
          role: 'button', tabindex: '0',
          'aria-label': 'Show the ' + l.value + ' traces from ' + s.label +
                        ' to ' + tn.label
        });
        path.appendChild(svg('title', {})).textContent =
          s.label + '  \u2192  ' + tn.label + '   ' + l.value + ' unit' +
          (l.value === 1 ? '' : 's') + ' — click to list them';
        choose(path, linkSelection(s, tn));
        frame.appendChild(path);
      });

    nodes.forEach(function (n) {
      var chosen = picked && picked.id === nodeKey(n);
      var group = svg('g', {
        class: 'sk-pick' + (chosen ? ' on' : ''),
        role: 'button', tabindex: '0',
        'aria-label': 'Show the ' + n.value + ' traces at ' + n.label
      });
      group.appendChild(svg('rect', {
        x: n.x, y: n.y, width: NODE_W, height: n.h,
        class: 'sk-node ' + (n.stage === 2 ? outcomeClass(n.label) : '')
      }));
      var label = svg('text', {
        x: n.stage === 0 ? n.x - 8 : n.x + NODE_W + 8,
        y: n.y + n.h / 2 + 4, class: 'sk-text',
        'text-anchor': n.stage === 0 ? 'end' : 'start'
      });
      label.textContent = n.label + '  ' + n.value;
      group.appendChild(label);
      group.appendChild(svg('title', {})).textContent =
        n.label + '  ' + n.value + ' unit' + (n.value === 1 ? '' : 's') +
        ' — click to list them';
      choose(group, nodeSelection(n));
      frame.appendChild(group);
    });

    var crossed = rows.filter(function (r) { return r.crossedBuild; }).length;
    host.appendChild(h('h2', { text: 'Where these re-run units went' }));
    host.appendChild(h('p', { class: 'rt-note-wide', text:
      'Left: the build a unit first ran. Middle: the build it was re-run on. ' +
      'Right: how it ended. Follows the filter above — ' + rows.length +
      ' trace' + (rows.length === 1 ? '' : 's') + ' shown, ' + crossed +
      ' of them re-run against a different build, which is the only kind of ' +
      'retest that can tell you a fix worked.' }));
    host.appendChild(frame);
  }

  function stageLabel(row, stage) {
    if (stage === 0) return row.stationLabel + ' ' + row.firstBuildShort;
    if (stage === 1) return row.stationLabel + ' ' + row.lastBuildShort;
    return row.outcome;
  }

  function nodeKey(n) { return 'n' + n.stage + '|' + n.label; }
  function linkKey(s, t2) { return 'l' + s.stage + '|' + s.label + '>' + t2.label; }

  function nodeSelection(n) {
    var name = n.stage === 0 ? 'first ran ' + n.label
      : n.stage === 1 ? 're-run on ' + n.label
      : n.label;
    return {
      id: nodeKey(n), label: name,
      match: function (row) { return stageLabel(row, n.stage) === n.label; }
    };
  }

  function linkSelection(s, t2) {
    var name = s.stage === 0
      ? s.label + ' \u2192 ' + t2.label
      : t2.label + ' after ' + s.label;
    return {
      id: linkKey(s, t2), label: name,
      match: function (row) {
        return stageLabel(row, s.stage) === s.label &&
               stageLabel(row, t2.stage) === t2.label;
      }
    };
  }

  /* Mouse and keyboard, because these are the page's main controls now and a
   * control you can only reach with a pointer is half a control. */
  function choose(node, selection) {
    function pick(event) {
      event.preventDefault();
      picked = (picked && picked.id === selection.id) ? null : selection;
      renderRows();
      renderSankey(chipRows());
    }
    node.addEventListener('click', pick);
    node.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') pick(event);
    });
  }

  function outcomeClass(label) {
    if (label === 'Recovered') return 'ok';
    if (label === 'Still failing') return 'bad';
    if (label === 'Passed throughout') return 'neutral';
    return '';
  }

  /* -------------------------------------------------------------- filters */

  /* Two levels, deliberately. The chip decides what the diagram is drawn
   * from; clicking the diagram narrows the table without redrawing it. If a
   * click redrew the diagram to its own selection there would be nothing left
   * to click next, which is the difference between a picture you can explore
   * and one you can use once. */
  function shown() {
    return chipRows().filter(function (row) {
      return !picked || picked.match(row);
    });
  }

  function chipRows() {
    return ROWS.filter(function (row) {
      if (!filter) return true;
      if (filter === 'recovered') return row.recovered;
      if (filter === 'failing') return row.stillFailing;
      if (filter === 'crossed') return row.crossedBuild;
      return row.station === filter;
    });
  }

  function renderFilters() {
    var host = byId('filters');
    host.innerHTML = '';
    [[null, 'All traces'], ['mlt', 'MLT'], ['htt', 'HTT'],
     ['crossed', 'Re-run on a different build'],
     ['recovered', 'Recovered'], ['failing', 'Still failing']
    ].forEach(function (option) {
      var was = filter, wasPicked = picked;
      filter = option[0]; picked = null;
      var n = shown().length;
      filter = was; picked = wasPicked;
      var button = h('button', {
        type: 'button', class: 'rt-chip',
        'aria-pressed': filter === option[0] ? 'true' : 'false',
        text: option[1] + ' (' + n + ')'
      });
      button.addEventListener('click', function () {
        filter = option[0];
        picked = null;          /* a pick belongs to the set it was made in */
        renderFilters(); renderRows(); renderSankey(chipRows());
      });
      host.appendChild(button);
    });
  }

  /* ----------------------------------------------------------------- rows */

  function renderRows() {
    var body = byId('body');
    var rows = shown();
    body.innerHTML = '';

    rows.forEach(function (row) {
      var tr = h('tr', {});
      tr.appendChild(h('td', { class: 'day', text: row.day }));
      tr.appendChild(h('td', { class: 'dut', text: row.dut }));
      tr.appendChild(h('td', { class: 'st', text: row.stationLabel }));

      /* The chain. Each attempt is a chip: when, on which build, how it went,
       * linked to the run on the controller. */
      var chain = h('td', { class: 'chain' });
      row.attempts.forEach(function (a, index) {
        if (index) chain.appendChild(h('span', { class: 'arrow', text: '→' }));
        var chip = h('a', {
          class: 'att a-' + a.status,
          href: a.url || '#', target: '_blank', rel: 'noopener noreferrer',
          title: (a.failures || 'passed') + '\n' + (a.url || '')
        }, [
          h('span', { class: 'att-day', text: a.day.slice(5) }),
          h('span', { class: 'att-build', text: a.build }),
          h('span', { class: 'att-res', text: a.status === 'pass' ? 'P' : 'F' })
        ]);
        chain.appendChild(chip);
      });
      tr.appendChild(chain);

      /* What it failed on first, and what it fails on now — the pair that says
       * whether the retest moved the problem or repeated it. */
      var first = row.attempts[0], last = row.attempts[row.attempts.length - 1];
      tr.appendChild(h('td', { class: 'fails', text: first.failures || '' }));
      tr.appendChild(h('td', { class: 'fails', text: last.failures || '' }));

      var out = row.recovered ? ['Recovered', 'out-recovered']
        : row.stillFailing ? ['Still failing', 'out-failing']
        : ['Passed throughout', 'out-neutral'];
      tr.appendChild(h('td', { class: 'out ' + out[1] }, [
        document.createTextNode(out[0]),
        row.crossedBuild
          ? h('span', { class: 'x-build', text: 'across builds' })
          : h('span', { class: 'x-build same', text: 'same build' })
      ]));
      body.appendChild(tr);
    });

    renderPicked(rows.length);

    var w = DATA.window || {};
    byId('caption').textContent = rows.length + ' of ' + ROWS.length +
      ' traces — one unit at one station, ' + w.from + ' to ' + w.to +
      '. A trace starts at the unit’s first attempt on or after ' + w.anchored +
      ', which is where the workbook’s retest tab starts.';
  }

  /* ------------------------------------------------------------------ csv */

  /* One line per attempt, not per trace: the table collapses a unit's journey
   * into a chain of chips, which reads well and pivots badly. What someone
   * wants a download for is the raw attempt list.
   */
  function csv(rows) {
    var head = ['first_seen', 'dut_sn', 'dut_pn', 'station', 'attempt',
                'attempts_total', 'day', 'result', 'build', 'run_id',
                'failed_test_cases', 'run_url', 'trace_outcome',
                'crossed_build'];
    var lines = [head.join(',')];
    rows.forEach(function (row) {
      row.attempts.forEach(function (a, index) {
        lines.push([
          row.day, row.dut, row.pn, row.stationLabel, index + 1, row.count,
          a.day, a.status, a.suite, a.short,
          (a.failures || '').replace(/\n/g, '; '),
          a.url || '', row.outcome, row.crossedBuild ? 'yes' : 'no'
        ].map(field).join(','));
      });
    });
    return lines.join('\n');
  }

  function field(value) {
    var text = value == null ? '' : String(value);
    /* A failure list can contain a comma and a serial can look like a number
     * to a spreadsheet; quoting everything is cheaper than deciding. */
    return '"' + text.replace(/"/g, '""') + '"';
  }

  function wireDownload() {
    var button = byId('download');
    if (!button) return;
    button.addEventListener('click', function () {
      var rows = shown();
      var name = 'retests_' + (DATA.window || {}).from + '_to_' +
        (DATA.window || {}).to + (filter ? '_' + filter : '') + '.csv';
      var blob = new Blob([csv(rows)], { type: 'text/csv;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var link = h('a', { href: url, download: name });
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      /* Revoked on the next tick: revoking immediately races the download in
       * Safari and hands the reader an empty file. */
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      button.textContent = 'Downloaded ' + rows.length + ' traces';
      setTimeout(function () { button.textContent = 'Download CSV'; }, 2500);
    });
  }

  /* A table that silently shows a subset is a table someone quotes as the
   * whole. The selection is named above it, with the way out beside it. */
  function renderPicked(count) {
    var host = byId('picked');
    host.innerHTML = '';
    if (!picked) { host.hidden = true; return; }
    host.hidden = false;
    host.appendChild(h('span', { class: 'pk-k', text: 'Showing' }));
    host.appendChild(h('strong', { class: 'pk-v', text: picked.label }));
    host.appendChild(h('span', { class: 'pk-n', text: count + ' trace' +
      (count === 1 ? '' : 's') }));
    var clear = h('button', { type: 'button', class: 'pk-x',
                              text: 'show all' });
    clear.addEventListener('click', function () {
      picked = null; renderRows(); renderSankey(chipRows());
    });
    host.appendChild(clear);
  }

  /* --------------------------------------------------------------- chrome */

  function renderSources() {
    var source = DATA.source || {};
    byId('sources').appendChild(h('p', { class: 'src', text:
      'Data source: ' + (source.label || 'pega3') + ' — ' + (source.note || '') +
      '. ' + (DATA.runs || 0) + ' suite runs read. This page does not feed the ' +
      'daily yield or the station page; it is a trace, not a yield. Built ' +
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
    if (!ROWS.length) {
      byId('caption').textContent = 'No data — run `make retest`.';
      return;
    }
    var w = DATA.window || {};
    byId('meta').textContent = w.from + ' → ' + w.to + ' · ' + w.days + ' days';
    renderSplit();
    renderFilters();
    renderRows();
    renderSankey(chipRows());
    wireDownload();
    renderSources();
    renderBuild();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
