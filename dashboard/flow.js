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
  /* The photo is what the lane is *of*. Four of the five have one, because
   * four of the five are a thing you can hold or walk up to; the 2U/4U lane
   * is an assembly step, and inventing a picture for it would be decoration. */
  var LANES = [
    { key: 'asic', title: 'ASIC',            owner: '@Sigurd',
      img: 'img/asic.png',       alt: 'Sohu ASIC package' },
    { key: 'l6',   title: 'PCBA L6',         owner: '@Pega',
      img: 'img/pcba.png',       alt: 'Sohu module board' },
    { key: 'fatp', title: 'FATP L10 2U/4U',  owner: '' },
    { key: 'l106', title: 'FATP L10 6U',     owner: '',
      img: 'img/chassis-6u.png', alt: '6U chassis' },
    { key: 'l11',  title: 'Rack L11',        owner: '',
      img: 'img/rack.png',       alt: 'Rack' }
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
    /* Struck through on the line's own chart, because skipping it is the
       current proposal. The box carries the link to the data that proposal
       rests on — a struck-out box with no way to find out why is a decision
       nobody outside the room can check. */
    { id: 'slt',    lane: 'asic', label: 'SLT',          kind: 'test',
      sub: 'System level test', owner: 'Sigurd', station: 'slt',
      struck: true, why: 'go/slt-ft',
      whyUrl: 'https://literate-telegram-2y3e9lz.pages.github.io/index.html' },

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
    /* FT hands off to the board line, not SLT. The chart used to run
       SLT -> SMT / ICT, which says every die goes through system level test on
       its way to a board — it does not, SLT is a branch off FT and the line is
       deciding whether to keep it at all. */
    { from: 'ft',     to: 'smt',    route: 'across' },

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

  /* 2026-08-20T00:04:12Z -> 2026-08-20 00:04 UTC. Minutes, not seconds: this
     says how fresh a figure is, and nobody needs it to the second. */
  function stamp(iso) {
    if (!iso) return '—';
    var text = String(iso).replace('T', ' ').replace('Z', '');
    return text.slice(0, 16) + (String(iso).indexOf('Z') > -1 ? ' UTC' : '');
  }

  /* Week to date by default, and the reader can widen it.
   *
   * This chart is the one the line stands in front of and reads as "how are we
   * doing". A rolling window answers that with half of this week and half of
   * last, so a number quoted on Thursday covers days that were already quoted
   * on Monday under a different heading. The week the line is standing in is
   * the week it should show, accumulating from Monday — which is why it is the
   * default and not merely one of two equals.
   *
   * On a Monday morning that week is a handful of units, so flowwindow.js puts
   * the trailing seven days one click away and labels both with their run
   * counts. Which one is showing is read from there rather than decided here,
   * so the two drawings on this page cannot end up on different windows.
   *
   * Falls back to the seven-day set if an older bundle has no week views, so
   * the page renders rather than emptying while a build catches up. */
  function views() {
    return (window.FlowWindow && window.FlowWindow.views()) ||
           STATIONS.viewsWeek || STATIONS.views || {};
  }

  function windowOf() {
    return (window.FlowWindow && window.FlowWindow.window()) ||
           STATIONS.windowWeek || STATIONS.window || {};
  }

  function summary(key) {
    var view = views()[key];
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
      column.appendChild(h('div', { class: 'lane-photo' }, [
        lane.img ? h('img', { src: lane.img, alt: lane.alt, loading: 'lazy' })
                 : null
      ]));
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

    box.appendChild(h('span', {
      class: 'box-label' + (node.struck ? ' struck' : ''), text: node.label }));
    if (node.sub) box.appendChild(h('span', { class: 'box-sub', text: node.sub }));
    if (node.why) {
      box.appendChild(h('a', {
        class: 'box-why', href: node.whyUrl || '#', target: '_blank',
        rel: 'noopener noreferrer',
        title: 'the data behind the proposal to skip this stage'
      }, [document.createTextNode(node.why + ' \u2197')]));
    }

    if (measured) {
      box.appendChild(h('span', { class: 'box-yield' }, [
        h('strong', { text: pct(stat.passRate) || '—' }),
        h('span', { class: 'box-runs', text: stat.runs + ' units' })
      ]));
      /* Straight into the station's own page, at the station. The chart is
       * where someone notices a number; the drill-down is where they find out
       * why it is that number. */
      var link = h('a', {
        /* index.html, not direct.html: direct.html is a redirect now, and a
         * meta refresh drops the #fragment — so every one of these landed on
         * the station page with no station selected. */
        class: 'box-link', href: 'index.html#station=' + node.station,
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
                         : 'no runs in the window' }));
    }

    boxes[node.id] = box;
    return box;
  }

  /* The two yields the line is asked for.
   *
   * Per-step is what each station did; the product of MLT and HTT is what a
   * module's chance of clearing L6 first time actually is, and it is the
   * number nobody computes in their head: two stages in the sixties and
   * fifties feel like a sixty-something line and are a thirty-something one.
   */
  function combined() {
    var mlt = summary('mlt'), htt = summary('htt');
    if (!mlt || !htt || !mlt.runs || !htt.runs) return null;
    var a = mlt.passRate, b = htt.passRate;
    if (a == null || b == null) return null;
    return { rate: a * b, mlt: a, htt: b };
  }

  function renderCombined() {
    var both = combined();
    var host = byId('combined');
    if (!host) return;
    host.innerHTML = '';
    if (!both) { host.hidden = true; return; }
    host.hidden = false;
    host.appendChild(h('span', { class: 'cb-k', text: 'L6 combined' }));
    host.appendChild(h('strong', { class: 'cb-v', text: pct(both.rate) }));
    host.appendChild(h('span', { class: 'cb-s', text:
      'MLT ' + pct(both.mlt) + ' × HTT ' + pct(both.htt) +
      ' — a module\u2019s chance of clearing both first time' }));
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

  /* Everything the window governs, in one place so the control can ask for it
   * again. renderBuild and the footer stamp are deliberately outside it: they
   * describe the bundle rather than the window, and renderBuild appends, so a
   * second call would print the release twice. */
  function draw() {
    var win = windowOf();
    /* Both ends as times, not dates.
     *
     * Read at nine on a Thursday, "2026-08-17 to 2026-08-20" does not say
     * whether this morning's units are in the number. The start says which
     * Monday the count began, and the last-counted stamp says how current it
     * is — which is the question anyone asks of a live figure. */
    byId('meta').textContent = win.weekOf
      ? 'week to date \u00b7 from ' + stamp(win.startedAt) +
        ' \u00b7 last counted ' + (win.lastRunAt ? stamp(win.lastRunAt) : 'nothing yet') +
        (win.runs ? ' \u00b7 ' + win.runs + ' unit runs' : '')
      : (win.from
         ? 'yields from ' + win.from + ' to ' + win.to +
           (win.days ? ' \u00b7 ' + win.days + ' days' : '')
         : 'flow only — no station data loaded');

    /* The prose used to say how many days the window covered. It is a week
       now, and how much of it has happened is on the line above. */
    var days = byId('window-days');
    if (days) {
      days.textContent = win.weekOf
        ? 'this week, from Monday ' + win.weekOf
        : (win.days ? 'the last ' + win.days + ' days' : 'the collected window');
    }

    renderLanes();
    renderCombined();
    renderLegend();
    drawWires();
  }

  function init() {
    el.canvas = byId('canvas');
    el.wires = byId('wires');
    el.lanes = byId('lanes');
    el.legend = byId('legend');

    renderBuild();
    draw();
    /* Redrawn, not reloaded: the window is a way of reading the same bundle. */
    if (window.FlowWindow) window.FlowWindow.onChange(draw);

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
