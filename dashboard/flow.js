/* The production test flowchart, with this dashboard's yields on it.
 *
 * WHY IT IS DRAWN AND NOT DRAWN-ON
 * The line's flowchart lives in a slide deck, so it is a picture: correct on
 * the day it was exported and silent about whether anything is being measured.
 * Here the boxes are elements, the yields come from the station bundle the
 * rest of the site is built from, and a stage nobody collects says so in the
 * box rather than looking the same as a stage at 100%.
 *
 * COLOUR IS A CLAIM, NOT DECORATION
 * Green means the stage produces a yield. Grey means it builds or moves
 * something without testing it. That rule is the whole legend, and it is why
 * Flash/BFT is green here while the line's own chart draws it pink — we count
 * 165 VBB provisioning runs at 70.9%, so it yields.
 *
 * Wires are drawn after layout from the boxes' own rectangles, so nothing is
 * hand-positioned and the chart survives a font change or a narrow window.
 *
 * Plain ES5, no build step, no dependencies.
 */
(function () {
  'use strict';

  var STATIONS = window.__FACTORY_STATIONS__ || {};

  /* Lanes, left to right, exactly as the line's chart reads. */
  var LANES = [
    { key: 'asic', title: 'ASIC',            owner: '@Sigurd' },
    { key: 'l6',   title: 'PCBA L6',         owner: '@Pega' },
    { key: 'fatp', title: 'FATP L10 2U/4U',  owner: '' },
    { key: 'l106', title: 'FATP L10 6U',     owner: '' },
    { key: 'l11',  title: 'Rack L11',        owner: '' }
  ];

  /* One entry per box.
   *
   * `station` is this repo's station key, and it is the only thing that turns
   * into a number — a box without one is a stage we do not collect, which the
   * box then says out loud. `owner` names who does measure it, so "no number"
   * reads as "someone else's data" rather than as "nobody knows".
   */
  var NODES = [
    { id: 'asic',   lane: 'asic', label: 'ASIC',         kind: 'build' },
    { id: 'wst',    lane: 'asic', label: 'WST',          kind: 'test',
      sub: 'Wafer sort', owner: 'Sigurd' },
    { id: 'ft',     lane: 'asic', label: 'FT',           kind: 'test',
      sub: 'Final test', owner: 'Sigurd' },
    { id: 'slt',    lane: 'asic', label: 'SLT',          kind: 'test',
      sub: 'System level test', owner: 'Sigurd', station: 'slt' },

    { id: 'smt',    lane: 'l6',   label: 'SMT / ICT',    kind: 'build',
      sub: 'HPB & VBB & PV1 & PDB' },
    { id: 'flash',  lane: 'l6',   label: 'Flash / BFT',  kind: 'test',
      sub: 'VBB', station: 'vbb_provision' },
    { id: 'assy6',  lane: 'l6',   label: 'ASSY',         kind: 'build' },
    { id: 'mlt',    lane: 'l6',   label: 'MLT',          kind: 'test',
      station: 'mlt' },
    { id: 'htt',    lane: 'l6',   label: 'HTT',          kind: 'test',
      station: 'htt' },

    { id: 'assy10', lane: 'fatp', label: 'ASSY',         kind: 'build',
      tags: ['4U', '2U'] },

    { id: 'assy6u', lane: 'l106', label: 'ASSY',         kind: 'build',
      tags: ['6U'] },
    { id: 'u2',     lane: 'l106', label: '2U',           kind: 'test',
      station: 'l10_2u' },
    { id: 'fat',    lane: 'l106', label: 'FAT',          kind: 'test',
      station: 'l10_fat' },
    { id: 'sft10',  lane: 'l106', label: 'SFT',          kind: 'test',
      station: 'l10_sft' },
    { id: 'rin10',  lane: 'l106', label: 'Runin',        kind: 'test',
      station: 'l10_rin' },

    { id: 'assy11', lane: 'l11',  label: 'ASSY',         kind: 'build' },
    { id: 'prov11', lane: 'l11',  label: 'Provisioning', kind: 'test',
      station: 'l11_provision' },
    { id: 'sft11',  lane: 'l11',  label: 'SFT',          kind: 'test',
      station: 'l11_test' },
    { id: 'rin11',  lane: 'l11',  label: 'Runin',        kind: 'test',
      station: 'l11_test', shared: true },
    { id: 'pack',   lane: 'l11',  label: 'Pack',         kind: 'pack' }
  ];

  /* `down` is the next box in the same lane; `across` hands off to the next
   * lane; `bypass` is a board that skips a stage and rejoins later. */
  var EDGES = [
    { from: 'asic',   to: 'wst',    route: 'down' },
    { from: 'wst',    to: 'ft',     route: 'down' },
    { from: 'ft',     to: 'slt',    route: 'down' },
    { from: 'slt',    to: 'smt',    route: 'across' },

    { from: 'smt',    to: 'flash',  route: 'down',   label: 'VBB' },
    { from: 'flash',  to: 'assy6',  route: 'down' },
    { from: 'smt',    to: 'assy6',  route: 'bypass', label: 'HPB & PDB' },
    { from: 'assy6',  to: 'mlt',    route: 'down' },
    { from: 'mlt',    to: 'htt',    route: 'down' },
    { from: 'htt',    to: 'assy10', route: 'across' },

    { from: 'assy10', to: 'fat',    route: 'across', label: '4U' },
    { from: 'assy10', to: 'assy6u', route: 'across', label: '2U' },

    { from: 'assy6u', to: 'u2',     route: 'down' },
    { from: 'u2',     to: 'fat',    route: 'down' },
    { from: 'fat',    to: 'sft10',  route: 'down' },
    { from: 'sft10',  to: 'rin10',  route: 'down' },
    { from: 'rin10',  to: 'assy11', route: 'across' },

    { from: 'assy11', to: 'prov11', route: 'down' },
    { from: 'prov11', to: 'sft11',  route: 'down' },
    { from: 'sft11',  to: 'rin11',  route: 'down' },
    { from: 'rin11',  to: 'pack',   route: 'down' }
  ];

  var el = {};
  var boxes = {};

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
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    return node;
  }

  function byId(id) { return document.getElementById(id); }

  function summary(key) {
    var view = (STATIONS.views || {})[key];
    return (view && view.summary) || null;
  }

  function pct(rate) {
    return rate == null ? null : (Math.round(rate * 1000) / 10) + '%';
  }

  /* ----------------------------------------------------------------- boxes */

  function renderLanes() {
    el.lanes.innerHTML = '';
    LANES.forEach(function (lane) {
      var column = h('div', { class: 'lane' });
      column.appendChild(h('div', { class: 'lane-head' }, [
        lane.owner ? h('span', { class: 'lane-owner', text: lane.owner }) : null,
        h('span', { class: 'lane-title', text: lane.title })
      ]));

      var stack = h('div', { class: 'lane-stack' });
      NODES.filter(function (node) { return node.lane === lane.key; })
        .forEach(function (node) { stack.appendChild(renderBox(node)); });
      column.appendChild(stack);
      el.lanes.appendChild(column);
    });
  }

  function renderBox(node) {
    var stat = node.station ? summary(node.station) : null;
    var measured = !!(stat && stat.runs);

    var box = h('div', {
      class: 'box k-' + node.kind + (measured ? ' measured' : ''),
      id: 'box-' + node.id
    });

    if (node.tags) {
      var tags = h('div', { class: 'box-tags' });
      node.tags.forEach(function (tag) {
        tags.appendChild(h('span', { class: 'tag t-' + tag, text: tag }));
      });
      box.appendChild(tags);
    }

    box.appendChild(h('span', { class: 'box-label', text: node.label }));
    if (node.sub) box.appendChild(h('span', { class: 'box-sub', text: node.sub }));

    if (measured) {
      box.appendChild(h('span', { class: 'box-yield' }, [
        h('strong', { text: pct(stat.passRate) || '—' }),
        h('span', { class: 'box-runs', text: stat.runs + ' units' })
      ]));
      /* Straight into the station's own page, at the station. The chart is
       * where someone notices a number; the drill-down is where they find out
       * why it is that number. */
      var link = h('a', {
        class: 'box-link', href: 'direct.html#station=' + node.station,
        title: 'Open ' + node.label + ' on the station page'
      }, [document.createTextNode('open')]);
      box.appendChild(link);
      if (node.shared) {
        box.appendChild(h('span', { class: 'box-note',
          text: 'counted with SFT — pega5 runs both under one suite' }));
      }
    } else if (node.kind === 'test') {
      /* A test stage with no number here. Naming who has it is the difference
       * between a gap in the line and a gap in this dashboard. */
      box.appendChild(h('span', { class: 'box-note',
        text: node.owner ? 'measured at ' + node.owner + ' — not collected here'
                         : 'no runs in the last 30 days' }));
    }

    boxes[node.id] = box;
    return box;
  }

  /* ----------------------------------------------------------------- wires */

  function rectOf(id) {
    var box = boxes[id];
    var base = el.canvas.getBoundingClientRect();
    var own = box.getBoundingClientRect();
    return {
      left: own.left - base.left, right: own.right - base.left,
      top: own.top - base.top, bottom: own.bottom - base.top,
      cx: own.left - base.left + own.width / 2,
      cy: own.top - base.top + own.height / 2
    };
  }

  function drawWires() {
    var base = el.canvas.getBoundingClientRect();
    el.wires.setAttribute('width', base.width);
    el.wires.setAttribute('height', base.height);
    el.wires.setAttribute('viewBox', '0 0 ' + base.width + ' ' + base.height);
    el.wires.innerHTML = '';

    var defs = svg('defs');
    var marker = svg('marker', {
      id: 'arrow', viewBox: '0 0 10 10', refX: '9', refY: '5',
      markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse'
    });
    marker.appendChild(svg('path', { d: 'M 0 0 L 10 5 L 0 10 z',
                                     class: 'wire-head' }));
    defs.appendChild(marker);
    el.wires.appendChild(defs);

    EDGES.forEach(function (edge) {
      if (!boxes[edge.from] || !boxes[edge.to]) return;
      var a = rectOf(edge.from);
      var b = rectOf(edge.to);
      var d, labelAt;

      if (edge.route === 'down') {
        d = 'M ' + a.cx + ' ' + a.bottom + ' L ' + b.cx + ' ' + (b.top - 2);
        labelAt = { x: a.cx + 8, y: (a.bottom + b.top) / 2, anchor: 'start' };
      } else if (edge.route === 'bypass') {
        /* Out to the right of the lane, down past the stage being skipped,
         * and back in. Boards that never go through Flash take this. */
        var out = Math.max(a.right, b.right) + 22;
        d = 'M ' + a.right + ' ' + a.cy +
            ' L ' + out + ' ' + a.cy +
            ' L ' + out + ' ' + b.cy +
            ' L ' + (b.right + 2) + ' ' + b.cy;
        labelAt = { x: out + 4, y: (a.cy + b.cy) / 2, anchor: 'start' };
      } else {
        /* Across lanes: out of the right edge, half way, then in. */
        var mid = (a.right + b.left) / 2;
        d = 'M ' + a.right + ' ' + a.cy +
            ' L ' + mid + ' ' + a.cy +
            ' L ' + mid + ' ' + b.cy +
            ' L ' + (b.left - 2) + ' ' + b.cy;
        labelAt = { x: mid + 4, y: Math.min(a.cy, b.cy) - 6, anchor: 'start' };
      }

      el.wires.appendChild(svg('path', {
        d: d, class: 'wire', fill: 'none', 'marker-end': 'url(#arrow)'
      }));

      if (edge.label) {
        var text = svg('text', {
          x: labelAt.x, y: labelAt.y, class: 'wire-label',
          'text-anchor': labelAt.anchor
        });
        text.textContent = edge.label;
        el.wires.appendChild(text);
      }
    });
  }

  /* --------------------------------------------------------------- chrome */

  function renderLegend() {
    var counted = NODES.filter(function (node) {
      return node.station && (summary(node.station) || {}).runs;
    }).length;
    var tests = NODES.filter(function (node) {
      return node.kind === 'test';
    }).length;

    el.legend.innerHTML = '';
    [
      ['k-test measured', 'Yields, measured here',
       counted + ' of ' + tests + ' test stages'],
      ['k-test', 'Yields, measured elsewhere', 'WST, FT and SLT sit with Sigurd'],
      ['k-build', 'Builds or moves, no verdict', 'assembly and SMT'],
      ['k-pack', 'Ships', 'end of the line']
    ].forEach(function (item) {
      el.legend.appendChild(h('span', { class: 'legend-item' }, [
        h('span', { class: 'swatch ' + item[0] }),
        h('span', { class: 'legend-label', text: item[1] }),
        h('span', { class: 'legend-note', text: item[2] })
      ]));
    });
  }

  function renderBuild() {
    var build = STATIONS.build || {};
    var slot = byId('build');
    if (build.release) {
      slot.appendChild(h('span', { class: 'build-release', text: build.release }));
    }
    if (build.commit) {
      slot.appendChild(build.commitUrl
        ? h('a', { class: 'build-commit', href: build.commitUrl, target: '_blank',
                   rel: 'noopener noreferrer', text: build.commit })
        : h('span', { class: 'build-commit', text: build.commit }));
    }
  }

  function init() {
    el.canvas = byId('canvas');
    el.wires = byId('wires');
    el.lanes = byId('lanes');
    el.legend = byId('legend');

    var window30 = STATIONS.window || {};
    byId('meta').textContent = window30.from
      ? 'yields from ' + window30.from + ' to ' + window30.to
      : 'flow only — no station data loaded';

    renderLanes();
    renderLegend();
    renderBuild();
    drawWires();

    byId('footer-meta').textContent = 'Yields built ' +
      String(STATIONS.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC');

    /* Fonts land after first paint and boxes move; redraw once they have. */
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(drawWires);
    }
    window.addEventListener('resize', drawWires);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
