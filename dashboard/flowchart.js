/* The grid flowchart renderer, shared by every chart that needs branches.
 *
 * flow.html keeps its own renderer and stays frozen: that chart is one column
 * per lane, it carries the accumulated yield the line quotes, and it is the
 * version people screenshot. Everything else — the comprehensive chart, the
 * end-to-end one — is the same drawing at more detail, which is the same
 * renderer with different data. Three copies of it would have drifted inside a
 * week.
 *
 * A chart is three lists. Lanes are columns with a photo and a title; nodes
 * name their lane, column and row; edges name two nodes. Nothing is positioned
 * by hand: each lane is a CSS grid, and the wires are computed afterwards from
 * the boxes' own rectangles — so the drawing survives a font change, a narrow
 * window, or a box being inserted in the middle of a lane.
 *
 * `station` on a node is this repo's station key and the only thing that turns
 * into a number. A node without one is a stage nobody here collects, and its box
 * says so rather than looking like a stage at 100%.
 *
 * Plain ES5, no build step, no dependencies.
 */
(function () {
  'use strict';

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
  function pct(rate) {
    return rate == null ? null : (Math.round(rate * 1000) / 10) + '%';
  }

  function render(chart) {
    var STATIONS = window.__FACTORY_STATIONS__ || {};
    var LANES = chart.lanes || [];
    var NODES = chart.nodes || [];
    var EDGES = chart.edges || [];
    /* Per-chart so two charts on one site cannot collide on an SVG marker id. */
    var ARROW = 'arrow-' + (chart.id || 'flow');
    var PREFIX = (chart.id || 'flow') + '-';

    /* Which elements to draw into. Defaulted so a page with one chart says
       nothing, and named so a page with two charts can host both: the summary
       and the end-to-end flow live on flow.html together now, and a shared
       #canvas meant whichever script ran second wiped the first. */
    var into = chart.targets || {};
    var el = {
      canvas: byId(into.canvas || 'canvas'),
      lanes: byId(into.lanes || 'lanes'),
      wires: byId(into.wires || 'wires'),
      legend: into.legend || 'legend'
    };
    if (!el.canvas || !el.lanes || !el.wires) return;
    var boxes = {};

    function views() { return STATIONS.viewsWeek || STATIONS.views || {}; }
    function summary(key) {
      var view = views()[key];
      return (view && view.summary) || null;
    }
    function labelOf(key) {
      var found = (STATIONS.stations || []).filter(function (station) {
        return station.key === key;
      })[0];
      return (found && found.label) || key;
    }

    /* ---------------------------------------------------------------- boxes */

    function renderBox(node) {
      var stat = node.station ? summary(node.station) : null;
      var measured = !!(stat && stat.runs);

      var box = h('div', {
        class: 'box k-' + node.kind + (measured ? ' measured' : '')
               + (node.dashed ? ' dashed' : '') + (node.small ? ' small' : ''),
        id: PREFIX + node.id
      });
      box.appendChild(h('span', { class: 'box-label', text: node.label }));
      if (node.sub) {
        box.appendChild(h('span', { class: 'box-sub', text: node.sub }));
      }

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
          box.appendChild(h('span', { class: 'box-note', text:
            'shares the ' + labelOf(node.station) + ' figure' }));
        }
      } else if (node.owner) {
        box.appendChild(h('span', { class: 'box-note',
                                    text: 'measured by ' + node.owner }));
      } else if (node.note) {
        /* A stage we know about and do not collect. Said plainly, with whatever
         * is known about why — a blank box and a box at 100% must never look
         * the same. */
        box.appendChild(h('span', { class: 'box-note', text: node.note }));
      } else if (node.station) {
        box.appendChild(h('span', { class: 'box-note', text: 'no runs' }));
      }

      boxes[node.id] = box;
      return box;
    }

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

    /* ---------------------------------------------------------------- wires */

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
        id: ARROW, viewBox: '0 0 10 10', refX: '9', refY: '5',
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
          var mid = (a.right + b.left) / 2;
          d = 'M ' + a.right + ' ' + a.cy + ' L ' + mid + ' ' + a.cy +
              ' L ' + mid + ' ' + b.cy + ' L ' + (b.left - 2) + ' ' + b.cy;
        } else if (Math.abs(a.cx - b.cx) > 4 && Math.abs(a.cy - b.cy) < 4) {
          /* Same row, different column: PV1 SMT/ICT into PV1 ASSY, SFT into
           * Runin. Straight across, either direction. */
          var left = a.cx < b.cx;
          d = 'M ' + (left ? a.right : a.left) + ' ' + a.cy +
              ' L ' + (left ? b.left - 2 : b.right + 2) + ' ' + b.cy;
        } else if (Math.abs(a.cx - b.cx) > 4) {
          /* Different column and different row — a board joining the module
           * chain from the side. Out sideways, then along. */
          var over = a.cx < b.cx;
          d = 'M ' + (over ? a.right : a.left) + ' ' + a.cy +
              ' L ' + b.cx + ' ' + a.cy +
              ' L ' + b.cx + ' ' + (b.cy < a.cy ? b.bottom + 2 : b.top - 2);
        } else if (b.cy < a.cy) {
          /* Upwards, which most of the module chain is. */
          d = 'M ' + a.cx + ' ' + a.top + ' L ' + b.cx + ' ' + (b.bottom + 2);
        } else {
          d = 'M ' + a.cx + ' ' + a.bottom + ' L ' + b.cx + ' ' + (b.top - 2);
        }

        el.wires.appendChild(svg('path', {
          d: d, fill: 'none', 'marker-end': 'url(#' + ARROW + ')',
          class: 'wire' + (edge.kind ? ' w-' + edge.kind : '')
        }));
      });
    }

    /* --------------------------------------------------------------- chrome */

    function renderLegend() {
      var host = byId(el.legend);
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
      if (chart.chrome === false) return;
      var meta = byId('meta');
      if (meta) {
        meta.textContent = counted.length + ' of ' + NODES.length +
                           ' boxes carry a number';
      }
      var build = STATIONS.build || {};
      var stamp = byId('build');
      if (stamp) {
        stamp.textContent = build.release
          ? build.release + ' · ' + build.commit : '';
      }
      var days = byId('window-days');
      if (days && window_.days) {
        days.textContent = 'the last ' + window_.days + ' days';
      }
      var footer = byId('footer-meta');
      if (footer) {
        footer.textContent = STATIONS.collectedAt
          ? 'Controllers read ' + String(STATIONS.collectedAt).replace('T', ' ')
          : '';
      }
    }

    renderLanes();
    renderLegend();
    renderMeta();
    /* After layout: the wires come from where the boxes ended up, so they
     * cannot be drawn in the frame that created them. */
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(renderWires);
    } else {
      renderWires();
    }
    window.addEventListener('resize', renderWires);
  }

  window.FactoryFlow = { render: render };
})();
