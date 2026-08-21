/* The line's flowchart drawn whole, with this dashboard's yields on it.
 *
 * WHY A SECOND CHART RATHER THAN A BIGGER FIRST ONE
 * flow.html is the summary: one SMT/ICT box, one ASSY, and the L6 accumulated
 * yield the line quotes (MLT × HTT). It reads at a glance and it is the version
 * people screenshot, so it stays exactly as it is.
 *
 * This one is the same line with the detail that summary leaves out — five
 * boards each through their own SMT/ICT, TIM between PV1 assembly and MLT, the
 * 2U and 4U paths kept apart, FAT on the rack. It needs branches, which is the
 * real reason it could not simply be added to the other: that chart stacks one
 * column per lane, and half of what is drawn here sits side by side.
 *
 * NO COMBINED FIGURE HERE, ON PURPOSE
 * The summary chart's accumulated yield is MLT × HTT. Adding a second product
 * over a different set of stages — with TIM in it, say — would put two numbers
 * called "L6 combined" on one site that disagree by a factor of two, and
 * whichever one a reader found first would be the one they quoted.
 *
 * LAYOUT
 * Each node names its lane, column and row, and each lane is a CSS grid. The
 * wires are drawn afterwards from the boxes' own rectangles — the same
 * technique flow.js uses, and the reason it works here unchanged: it never
 * knew where a box was, only where it ended up.
 *
 * Plain ES5, no build step, no dependencies.
 */
(function () {
  'use strict';

  var STATIONS = window.__FACTORY_STATIONS__ || {};

  var LANES = [
    { key: 'asic', title: 'ASIC',           owner: '@Sigurd',
      img: 'img/asic.png',       alt: 'Sohu ASIC package', cols: 1 },
    { key: 'l6',   title: 'PCBA L6',        owner: '@Pega',
      img: 'img/pcba.png',       alt: 'Sohu module board', cols: 2 },
    { key: 'fatp', title: 'FATP L10 2U/4U', owner: '', cols: 1 },
    { key: 'l106', title: 'FATP L10 6U',    owner: '',
      img: 'img/chassis-6u.png', alt: '6U chassis', cols: 2 },
    { key: 'l11',  title: 'Rack L11',       owner: '',
      img: 'img/rack.png',       alt: 'Rack', cols: 1 }
  ];

  /* One entry per box, with where it sits.
   *
   * `station` is this repo's station key and the only thing that becomes a
   * number; a box without one is a stage we do not collect, which the box then
   * says out loud. The module chain ascends — PV1 ASSY at the bottom, HTT at
   * the top — because that is how the line draws it, and a chart that rearranges
   * the line's own layout to suit a renderer stops being the line's chart.
   */
  var NODES = [
    { id: 'asic',   lane: 'asic', col: 1, row: 1, label: 'ASIC', kind: 'build' },
    { id: 'wst',    lane: 'asic', col: 1, row: 2, label: 'WST',  kind: 'test',
      sub: 'Wafer sort', owner: 'Sigurd' },
    { id: 'ft',     lane: 'asic', col: 1, row: 3, label: 'FT',   kind: 'test',
      sub: 'Final test', owner: 'Sigurd' },
    { id: 'slt',    lane: 'asic', col: 1, row: 4, label: 'SLT',  kind: 'test',
      sub: 'System level test', owner: 'Sigurd', station: 'slt' },

    /* Five boards, five SMT/ICT lines. None reports to a controller. */
    { id: 'smt_bb', lane: 'l6', col: 1, row: 1, label: 'BB',  kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'smt_hpb', lane: 'l6', col: 1, row: 2, label: 'HPB', kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'htt',    lane: 'l6', col: 2, row: 3, label: 'HTT', kind: 'test',
      station: 'htt' },
    { id: 'mlt',    lane: 'l6', col: 2, row: 4, label: 'MLT', kind: 'test',
      station: 'mlt' },
    { id: 'tim',    lane: 'l6', col: 2, row: 5, label: 'TIM', kind: 'test',
      sub: 'Coldplate bake', station: 'tim' },
    { id: 'smt_pv1', lane: 'l6', col: 1, row: 6, label: 'PV1', kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'assy_pv1', lane: 'l6', col: 2, row: 6, label: 'PV1 ASSY',
      kind: 'build' },
    { id: 'smt_vbb', lane: 'l6', col: 1, row: 7, label: 'VBB', kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'flash',  lane: 'l6', col: 2, row: 7, label: 'Flash / BFT',
      kind: 'test', station: 'vbb_provision' },
    { id: 'smt_pdb', lane: 'l6', col: 1, row: 8, label: 'PDB', kind: 'build',
      sub: 'SMT / ICT' },

    { id: 'assy4u', lane: 'fatp', col: 1, row: 1, label: '4U ASSY',
      kind: 'build' },
    { id: 'assy2u', lane: 'fatp', col: 1, row: 2, label: '2U ASSY',
      kind: 'build' },
    /* The 2U test appears in both L10 lanes on the line's chart, dashed in
     * both, because one station serves both paths. Drawn twice and marked
     * shared, so neither box pretends the number is only its own. */
    { id: 'u2_fatp', lane: 'fatp', col: 1, row: 3, label: '2U', kind: 'test',
      station: 'l10_2u', dashed: true, shared: true },

    { id: 'run10',  lane: 'l106', col: 2, row: 1, label: 'Runin', kind: 'test',
      station: 'l10_rin' },
    { id: 'sft10',  lane: 'l106', col: 1, row: 1, label: 'SFT',   kind: 'test',
      station: 'l10_sft' },
    { id: 'fat10',  lane: 'l106', col: 1, row: 2, label: 'FAT',   kind: 'test',
      station: 'l10_fat' },
    { id: 'u2_6u',  lane: 'l106', col: 1, row: 3, label: '2U',    kind: 'test',
      station: 'l10_2u', dashed: true, shared: true },
    { id: 'assy6u', lane: 'l106', col: 1, row: 4, label: 'ASSY',  kind: 'build' },

    { id: 'assy11', lane: 'l11', col: 1, row: 1, label: 'ASSY', kind: 'build' },
    { id: 'prov11', lane: 'l11', col: 1, row: 2, label: 'Provision',
      kind: 'test', station: 'l11_provision' },
    /* Three rack stages, one station key in the registry. Each says so rather
     * than three boxes quietly repeating one figure. */
    { id: 'fat11',  lane: 'l11', col: 1, row: 3, label: 'FAT', kind: 'test',
      station: 'l11_test', shared: true },
    { id: 'sft11',  lane: 'l11', col: 1, row: 4, label: 'SFT', kind: 'test',
      station: 'l11_test', shared: true },
    { id: 'run11',  lane: 'l11', col: 1, row: 5, label: 'Runin', kind: 'test',
      station: 'l11_test', shared: true },
    { id: 'pack',   lane: 'l11', col: 1, row: 6, label: 'Pack', kind: 'pack' }
  ];

  /* Wires. `kind` is how the line draws it, not what it means to us: `dashed`
   * where its chart dashes, `lead` for the one it picks out in blue. */
  var EDGES = [
    { from: 'asic',    to: 'wst' },
    { from: 'wst',     to: 'ft' },
    { from: 'ft',      to: 'slt',     kind: 'dashed' },
    { from: 'ft',      to: 'smt_pv1', across: true },

    { from: 'smt_pv1', to: 'assy_pv1' },
    { from: 'assy_pv1', to: 'tim' },
    { from: 'tim',     to: 'mlt' },
    { from: 'mlt',     to: 'htt' },
    { from: 'htt',     to: 'assy4u',  across: true },
    { from: 'smt_hpb', to: 'assy4u',  across: true },
    { from: 'smt_bb',  to: 'assy4u',  across: true, kind: 'dashed' },
    { from: 'smt_vbb', to: 'flash' },
    { from: 'flash',   to: 'assy4u',  across: true },
    { from: 'smt_pdb', to: 'assy2u',  across: true, kind: 'lead' },

    { from: 'assy2u',  to: 'u2_fatp' },
    { from: 'assy4u',  to: 'assy6u',  across: true },
    { from: 'u2_fatp', to: 'assy6u',  across: true },

    { from: 'assy6u',  to: 'u2_6u' },
    { from: 'u2_6u',   to: 'fat10' },
    { from: 'fat10',   to: 'sft10' },
    { from: 'sft10',   to: 'run10' },
    { from: 'run10',   to: 'assy11',  across: true },

    { from: 'assy11',  to: 'prov11' },
    { from: 'prov11',  to: 'fat11' },
    { from: 'fat11',   to: 'sft11' },
    { from: 'sft11',   to: 'run11' },
    { from: 'run11',   to: 'pack' }
  ];

  var el = {};
  var boxes = {};

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
  function svg(tag, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function views() { return STATIONS.viewsWeek || STATIONS.views || {}; }
  function summary(key) {
    var view = views()[key];
    return (view && view.summary) || null;
  }
  function pct(rate) {
    return rate == null ? null : (Math.round(rate * 1000) / 10) + '%';
  }
  function labelOf(key) {
    var found = (STATIONS.stations || []).filter(function (station) {
      return station.key === key;
    })[0];
    return found && found.label;
  }

  /* ----------------------------------------------------------------- boxes */

  function renderLanes() {
    el.lanes.innerHTML = '';
    boxes = {};
    LANES.forEach(function (lane) {
      var column = h('div', { class: 'lane' });
      column.appendChild(h('div', { class: 'lane-photo' }, [
        lane.img ? h('img', { src: lane.img, alt: lane.alt, loading: 'lazy' })
                 : null
      ]));
      column.appendChild(h('div', { class: 'lane-head' }, [
        lane.owner ? h('span', { class: 'lane-owner', text: lane.owner }) : null,
        h('span', { class: 'lane-title', text: lane.title })
      ]));

      /* A grid rather than a stack, which is the whole difference from the
       * summary chart: PV1 SMT/ICT and PV1 ASSY are one row, two columns. */
      var grid = h('div', {
        class: 'lane-grid',
        style: 'grid-template-columns: repeat(' + (lane.cols || 1) + ', 1fr)'
      });
      NODES.filter(function (node) { return node.lane === lane.key; })
        .forEach(function (node) {
          var box = renderBox(node);
          box.setAttribute('style',
            'grid-column: ' + node.col + '; grid-row: ' + node.row);
          grid.appendChild(box);
        });
      column.appendChild(grid);
      el.lanes.appendChild(column);
    });
  }

  function renderBox(node) {
    var stat = node.station ? summary(node.station) : null;
    var measured = !!(stat && stat.runs);

    var box = h('div', {
      class: 'box k-' + node.kind + (measured ? ' measured' : '')
             + (node.dashed ? ' dashed' : ''),
      id: 'full-' + node.id
    });
    box.appendChild(h('span', { class: 'box-label', text: node.label }));
    if (node.sub) box.appendChild(h('span', { class: 'box-sub', text: node.sub }));

    if (measured) {
      box.appendChild(h('span', { class: 'box-yield' }, [
        h('strong', { text: pct(stat.passRate) || '—' }),
        h('span', { class: 'box-runs', text: stat.runs + ' units' })
      ]));
      box.appendChild(h('a', {
        class: 'box-link', href: 'index.html#station=' + node.station,
        title: 'Open ' + node.label + ' on the station page'
      }, [document.createTextNode('open')]));
      if (node.shared) {
        /* The registry's label, not its key: "shares l10_2u's figure" is a
         * key leaking into prose on a page a reader is meant to trust. */
        box.appendChild(h('span', { class: 'box-note', text:
          'shares the ' + (labelOf(node.station) || node.station) +
          ' figure' }));
      }
    } else if (node.owner) {
      box.appendChild(h('span', { class: 'box-note',
                                  text: 'measured by ' + node.owner }));
    } else if (node.station) {
      box.appendChild(h('span', { class: 'box-note', text: 'no runs' }));
    }

    boxes[node.id] = box;
    return box;
  }

  /* ----------------------------------------------------------------- wires */

  function rectOf(id) {
    var base = el.canvas.getBoundingClientRect();
    var own = boxes[id].getBoundingClientRect();
    return {
      left: own.left - base.left, right: own.right - base.left,
      top: own.top - base.top, bottom: own.bottom - base.top,
      cx: own.left - base.left + own.width / 2,
      cy: own.top - base.top + own.height / 2
    };
  }

  function renderWires() {
    var base = el.canvas.getBoundingClientRect();
    el.wires.setAttribute('width', base.width);
    el.wires.setAttribute('height', base.height);
    el.wires.setAttribute('viewBox', '0 0 ' + base.width + ' ' + base.height);
    el.wires.innerHTML = '';

    var defs = svg('defs');
    var marker = svg('marker', {
      id: 'arrow-full', viewBox: '0 0 10 10', refX: '9', refY: '5',
      markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse'
    });
    marker.appendChild(svg('path', { d: 'M 0 0 L 10 5 L 0 10 z',
                                     class: 'wire-head' }));
    defs.appendChild(marker);
    el.wires.appendChild(defs);

    EDGES.forEach(function (edge) {
      if (!boxes[edge.from] || !boxes[edge.to]) return;
      var a = rectOf(edge.from), b = rectOf(edge.to);
      var d;

      if (edge.across) {
        /* Out of the right edge, half way, then in. */
        var mid = (a.right + b.left) / 2;
        d = 'M ' + a.right + ' ' + a.cy + ' L ' + mid + ' ' + a.cy +
            ' L ' + mid + ' ' + b.cy + ' L ' + (b.left - 2) + ' ' + b.cy;
      } else if (Math.abs(a.cx - b.cx) > 4 && Math.abs(a.cy - b.cy) < 4) {
        /* Same row, different column — PV1 SMT/ICT into PV1 ASSY, SFT into
         * Runin. Straight across. */
        var left = a.cx < b.cx;
        d = 'M ' + (left ? a.right : a.left) + ' ' + a.cy +
            ' L ' + (left ? b.left - 2 : b.right + 2) + ' ' + b.cy;
      } else if (b.cy < a.cy) {
        /* Upwards, which most of the module chain is: out of the top. */
        d = 'M ' + a.cx + ' ' + a.top + ' L ' + b.cx + ' ' + (b.bottom + 2);
      } else {
        d = 'M ' + a.cx + ' ' + a.bottom + ' L ' + b.cx + ' ' + (b.top - 2);
      }

      el.wires.appendChild(svg('path', {
        d: d, fill: 'none', 'marker-end': 'url(#arrow-full)',
        class: 'wire' + (edge.kind ? ' w-' + edge.kind : '')
      }));
    });
  }

  /* ---------------------------------------------------------------- chrome */

  function renderLegend() {
    var host = byId('legend');
    if (!host) return;
    host.innerHTML = '';
    [['test', 'Tested here — the box carries its yield'],
     ['build', 'Built or moved, not tested'],
     ['pack', 'Shipped']].forEach(function (pair) {
      host.appendChild(h('span', { class: 'lg' }, [
        h('span', { class: 'lg-sw k-' + pair[0] }),
        h('span', { text: pair[1] })
      ]));
    });
    host.appendChild(h('span', { class: 'lg' }, [
      h('span', { class: 'lg-sw k-test dashed' }),
      h('span', { text: 'Dashed as the line’s own chart dashes it' })
    ]));
  }

  function renderMeta() {
    var counted = NODES.filter(function (node) {
      return node.station && summary(node.station);
    });
    var window_ = STATIONS.windowWeek || STATIONS.window || {};
    byId('meta').textContent =
      counted.length + ' of ' + NODES.length + ' boxes carry a number';
    var build = STATIONS.build || {};
    byId('build').textContent = build.release
      ? build.release + ' · ' + build.commit : '';
    var days = byId('window-days');
    if (days && window_.days) days.textContent = 'the last ' + window_.days + ' days';
    byId('footer-meta').textContent = STATIONS.collectedAt
      ? 'Controllers read ' + String(STATIONS.collectedAt).replace('T', ' ')
      : '';
  }

  function init() {
    el.canvas = byId('canvas');
    el.lanes = byId('lanes');
    el.wires = byId('wires');
    if (!el.canvas || !el.lanes || !el.wires) return;

    renderLanes();
    renderLegend();
    renderMeta();
    /* After layout: the wires are computed from where the boxes ended up, so
     * they cannot be drawn in the same frame the boxes were created in. */
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(renderWires);
    } else {
      renderWires();
    }
    window.addEventListener('resize', renderWires);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
