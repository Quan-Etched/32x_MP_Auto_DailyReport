/* The chart library the station and weekly pages share.
 *
 * WHY THIS FILE EXISTS
 * These renderers lived inside stations.js, which was fine while one page drew
 * them. The weekly page now draws the same three — pass/fail by day, yield by
 * release, the failure Pareto — over one Monday-to-Sunday week, and two copies
 * of a chart is two answers to "what does a hollow marker mean". They are here
 * once and both pages call them.
 *
 * WHAT IS AND IS NOT IN HERE
 * Nothing in this file knows which page it is on. The renderers take a plot
 * element, a list of rows and an options object; where a click should go is an
 * `onActivate` callback the caller supplies, because the station page drills
 * into runs.html filtered by station and the weekly page has its own idea. No
 * DATA, no state, no refs — that separation is what made the extraction a move
 * rather than a rewrite.
 *
 * Row shapes are the renderers' contract, not this comment's: see renderMix
 * for the mix rows and renderTrend for the trend ones.
 */
(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

  /* ---------------------------------------------------------------- helpers */

  function h(tag, attrs, kids) { return build(document.createElement(tag), attrs, kids); }
  function s(tag, attrs, kids) { return build(document.createElementNS(SVG_NS, tag), attrs, kids); }

  function build(node, attrs, kids) {
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === 'text') node.textContent = value;
        else if (key.indexOf('on') === 0 && typeof value === 'function') {
          node.addEventListener(key.slice(2), value);
        } else node.setAttribute(key, value);
      });
    }
    if (kids) {
      (Array.isArray(kids) ? kids : [kids]).forEach(function (kid) {
        if (kid === null || kid === undefined || kid === false) return;
        node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
      });
    }
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  var measureCtx = document.createElement('canvas').getContext('2d');
  function measure(text, font) {
    measureCtx.font = font || '11px system-ui, -apple-system, sans-serif';
    return measureCtx.measureText(text).width;
  }

  function fmtInt(v) { return v === null || v === undefined ? '—' : Math.round(v).toLocaleString(); }
  function fmtPct(v, d) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return (v * 100).toFixed(d === undefined ? 1 : d) + '%';
  }
  function fmtDayShort(iso) {              // 2026-07-20 -> 7/20
    if (!iso) return '—';
    var p = iso.split('-');
    return parseInt(p[1], 10) + '/' + parseInt(p[2], 10);
  }
  function fmtRange(a, b) {
    if (!a) return '';
    return a === b ? fmtDayShort(a) : fmtDayShort(a) + '–' + fmtDayShort(b);
  }

  /* Shallow merge, ES5-style — no Object.assign, to match the rest of the file. */
  function dict(base, extra) {
    var out = {};
    Object.keys(base || {}).forEach(function (k) { out[k] = base[k]; });
    Object.keys(extra || {}).forEach(function (k) { out[k] = extra[k]; });
    return out;
  }

  function ago(iso) {
    if (!iso) return null;
    var then = Date.parse(iso);
    if (isNaN(then)) return null;
    var mins = Math.floor((Date.now() - then) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + ' min ago';
    var hours = Math.floor(mins / 60);
    if (hours < 24) return hours + 'h ' + (mins % 60) + 'm ago';
    var days = Math.floor(hours / 24);
    return days + 'd ' + (hours % 24) + 'h ago';
  }

  function minutesSince(iso) {
    var then = Date.parse(iso || '');
    return isNaN(then) ? Infinity : (Date.now() - then) / 60000;
  }

  function niceTicks(max, count) {
    if (!isFinite(max) || max <= 0) return [0, 1];
    var rough = max / (count || 4);
    var mag = Math.pow(10, Math.floor(Math.log10(rough)));
    var n = rough / mag;
    var step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
    var out = [];
    for (var v = 0; v <= max + step * 0.5; v += step) out.push(Math.round(v * 1e6) / 1e6);
    return out.length > 1 ? out : [0, step];
  }

  /* --------------------------------------------------------------- tooltip */

  function makeTooltip(plot) {
    var node = h('div', { class: 'tooltip', role: 'status' });
    plot.appendChild(node);
    return {
      show: function (x, y, rows, heading) {
        clear(node);
        if (heading) node.appendChild(h('div', { class: 'tt-head', text: heading }));
        rows.forEach(function (row) {
          node.appendChild(h('div', { class: 'tt-row' }, [
            row.color ? h('span', { class: 'tt-key block', style: 'background:' + row.color }) : null,
            h('span', { class: 'tt-name', text: row.name }),
            h('span', { class: 'tt-value', text: row.value })
          ]));
        });
        node.setAttribute('data-open', 'true');
        var w = node.offsetWidth || 180, ht = node.offsetHeight || 60;
        node.style.left = Math.max(4, Math.min(x + 14, plot.clientWidth - w - 4)) + 'px';
        node.style.top = Math.max(4, Math.min(y - ht / 2, plot.clientHeight - ht - 4)) + 'px';
      },
      hide: function () { node.setAttribute('data-open', 'false'); }
    };
  }

  /* Arrow keys move a cursor through the bars; Enter opens the drill-down for
   * wherever the cursor is, so the chart is reachable without a pointer. */
  function attachCursor(plot, count, onMove, onLeave, onActivate) {
    var index = -1;
    plot.setAttribute('tabindex', '0');
    plot.setAttribute('role', 'application');
    plot.addEventListener('keydown', function (e) {
      if (!count) return;
      if (e.key === 'ArrowRight') { index = Math.min(count - 1, index + 1); onMove(index); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { index = Math.max(0, (index < 0 ? count : index) - 1); onMove(index); e.preventDefault(); }
      else if (e.key === 'Home') { index = 0; onMove(0); e.preventDefault(); }
      else if (e.key === 'End') { index = count - 1; onMove(index); e.preventDefault(); }
      else if (e.key === 'Escape') { index = -1; onLeave(); }
      else if ((e.key === 'Enter' || e.key === ' ') && onActivate && index >= 0) {
        onActivate(index); e.preventDefault();
      }
    });
    plot.addEventListener('blur', function () { index = -1; onLeave(); });
  }

  function emptyPlot(plot, message) {
    clear(plot);
    plot.appendChild(h('div', { class: 'empty', text: message }));
  }

  /* ------------------------------------------------------- stacked columns */

  var MIX_SERIES = [
    { key: 'pass', label: 'pass', color: 'var(--status-good)' },
    { key: 'fail', label: 'fail', color: 'var(--status-critical)' },
    // Abort is an infrastructure outcome, not a unit verdict, so it takes a
    // categorical slot rather than a third status colour.
    { key: 'abort', label: 'abort', color: 'var(--series-7)' }
  ];

  var GAP = 2, MAXBAR = 34, CORNER = 4;

  function barPath(x, y, w, hh, r) {
    var rr = Math.max(0, Math.min(r, w / 2, hh));
    return 'M' + x + ',' + (y + hh) + 'L' + x + ',' + (y + rr) +
      'Q' + x + ',' + y + ' ' + (x + rr) + ',' + y +
      'L' + (x + w - rr) + ',' + y +
      'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + rr) +
      'L' + (x + w) + ',' + (y + hh) + 'Z';
  }

  /**
   * Stacked pass/fail/abort columns with the total above each bar.
   * `rows` need `{ label, sub, pass, fail, abort, total }`.
   */
  function renderMix(plot, rows, opts) {
    clear(plot);
    if (!rows.length) { emptyPlot(plot, opts.emptyText || 'No runs for this station.'); return; }

    var hasSub = rows.some(function (r) { return r.sub; });
    var width = Math.max(plot.clientWidth || 520, 320);

    /* Release names are long — CHECK_vbb_setup_validate_token_PROD is thirty
     * five characters over a band a fifth as wide — so centred horizontal
     * labels printed straight over each other and the axis became a smear.
     * Where they do not fit, they are turned and the chart is given the room
     * to turn them in. */
    var longest = rows.reduce(function (n, r) {
      return Math.max(n, String(r.label || '').length);
    }, 0);
    var bandGuess = (width - 56) / Math.max(1, rows.length);
    var tilt = longest * 6.1 > bandGuess;
    var LABEL_CAP = 30;
    var tiltRoom = tilt ? Math.min(96, Math.min(longest, LABEL_CAP) * 4.6) : 0;

    var height = (hasSub ? 300 : 276) + tiltRoom;
    var margin = {
      top: 24, right: 12, left: 44,
      bottom: (hasSub ? 48 : 34) + tiltRoom
    };
    var innerW = width - margin.left - margin.right;
    var innerH = height - margin.top - margin.bottom;

    var ticks = niceTicks(Math.max.apply(null, rows.map(function (r) { return r.total; }).concat([1])), 4);
    var yMax = ticks[ticks.length - 1];
    var band = innerW / rows.length;
    var barW = Math.min(MAXBAR, Math.max(4, band - 10));
    var yAt = function (v) { return margin.top + innerH - (v / yMax) * innerH; };

    var svg = s('svg', {
      viewBox: '0 0 ' + width + ' ' + height, height: height,
      role: 'img', 'aria-label': opts.ariaLabel
    });

    ticks.forEach(function (t) {
      var y = yAt(t);
      svg.appendChild(s('line', {
        class: t === 0 ? 'axisline' : 'gridline',
        x1: margin.left, x2: width - margin.right, y1: y, y2: y
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: margin.left - 8, y: y + 4, 'text-anchor': 'end', text: fmtInt(t)
      }));
    });

    var highlight = s('rect', {
      x: 0, y: margin.top, width: band, height: innerH,
      fill: 'var(--hover-wash)', opacity: 0, 'pointer-events': 'none'
    });
    svg.appendChild(highlight);

    /* Turned labels need only their own line width, so every bar can keep its
     * name; upright ones still get thinned out. */
    var labelEvery = tilt ? 1 : Math.max(1, Math.ceil((rows.length * 34) / innerW));

    rows.forEach(function (row, i) {
      var x = margin.left + i * band + (band - barW) / 2;
      var stackBottom = margin.top + innerH;

      var topIndex = -1;
      MIX_SERIES.forEach(function (ser, si) { if ((row[ser.key] || 0) > 0) topIndex = si; });

      MIX_SERIES.forEach(function (ser, si) {
        var value = row[ser.key] || 0;
        if (value <= 0) return;
        var raw = (value / yMax) * innerH;
        var y = stackBottom - raw;
        var drawH = (si === topIndex) ? raw : Math.max(1, raw - GAP);
        svg.appendChild(s('path', {
          d: barPath(x, y, barW, drawH, si === topIndex ? CORNER : 0),
          fill: ser.color
        }));
        // Only label inside the segment when the text genuinely fits.
        if (drawH >= 15 && barW >= 18) {
          svg.appendChild(s('text', {
            class: 'bar-inner', x: x + barW / 2, y: y + drawH / 2 + 4,
            'text-anchor': 'middle', fill: '#ffffff', text: String(value)
          }));
        }
        stackBottom -= raw;
      });

      if (row.total > 0) {
        svg.appendChild(s('text', {
          class: 'bar-value', x: x + barW / 2, y: yAt(row.total) - 6,
          'text-anchor': 'middle', text: String(row.total)
        }));
      }

      if (i % labelEvery === 0) {
        var cx = margin.left + i * band + band / 2;
        var full = String(row.label || '');
        var shown = full.length > LABEL_CAP
          ? full.slice(0, LABEL_CAP - 1) + '\u2026' : full;
        var ly = tilt ? (margin.top + innerH + 14) : height - (hasSub ? 30 : 14);
        var label = s('text', {
          class: 'tick', x: cx, y: ly,
          'text-anchor': tilt ? 'end' : 'middle', text: shown
        });
        if (tilt) {
          label.setAttribute('transform', 'rotate(-40 ' + cx + ' ' + ly + ')');
        }
        /* Truncated names keep the whole string on hover, so shortening the
         * axis never costs the reader the identity of a release. */
        if (shown !== full) {
          label.appendChild(s('title', { text: full }));
        }
        svg.appendChild(label);

        if (row.sub) {
          var sy = tilt ? (margin.top + innerH + 26) : height - 16;
          var sub = s('text', {
            class: 'x-sub', x: cx, y: sy,
            'text-anchor': tilt ? 'end' : 'middle', text: row.sub
          });
          if (tilt) {
            sub.setAttribute('transform', 'rotate(-40 ' + cx + ' ' + sy + ')');
          }
          svg.appendChild(sub);
        }
      }
    });

    if (opts.axisTitle) {
      svg.appendChild(s('text', {
        class: 'x-sub', x: margin.left + innerW / 2, y: height - 2,
        'text-anchor': 'middle', text: opts.axisTitle
      }));
    }

    plot.appendChild(svg);
    var tip = makeTooltip(plot);

    function show(i) {
      var row = rows[i];
      if (!row) return;
      highlight.setAttribute('x', margin.left + i * band);
      highlight.setAttribute('opacity', '1');
      tip.show(margin.left + i * band + band / 2, margin.top + innerH / 2,
        MIX_SERIES.map(function (ser) {
          return { color: ser.color, name: ser.label, value: fmtInt(row[ser.key] || 0) };
        }).concat([
          { name: 'total', value: fmtInt(row.total) },
          { name: 'FPY', value: fmtPct(row.fpy) + (row.thin ? ' (thin)' : '') }
        ]), row.heading || row.label);
    }
    function hide() { highlight.setAttribute('opacity', '0'); tip.hide(); }

    var hit = s('rect', { class: 'hit', x: margin.left, y: margin.top, width: innerW, height: innerH });
    svg.appendChild(hit);

    function indexAt(e) {
      var box = svg.getBoundingClientRect();
      var lx = (e.clientX - box.left) * (width / box.width) - margin.left;
      return Math.max(0, Math.min(rows.length - 1, Math.floor(lx / band)));
    }

    hit.addEventListener('pointermove', function (e) { show(indexAt(e)); });
    hit.addEventListener('pointerleave', hide);

    // Clicking opens the runs behind that bar. The target is the whole band
    // rather than the drawn bar, so a thin one-run column is still easy to hit.
    var activate = opts.onSelect ? function (i) {
      if (rows[i]) opts.onSelect(rows[i]);
    } : null;
    if (activate) {
      hit.setAttribute('class', 'hit drillable');
      hit.addEventListener('click', function (e) { activate(indexAt(e)); });
    }
    attachCursor(plot, rows.length, show, hide, activate);
  }

  /* ------------------------------------------------------------ FPY trend */

  /**
   * Percentage trend line. A hollow marker means the denominator was under the
   * thin-sample floor — 1/1 = 100% is a coin toss, not a yield, and it must not
   * read the same as 40/40.
   */
  function renderTrend(plot, rows, opts) {
    clear(plot);
    var usable = rows.filter(function (r) { return r.fpy !== null && r.fpy !== undefined; });
    if (!usable.length) { emptyPlot(plot, opts.emptyText || 'No graded first attempts.'); return; }

    var hasSub = rows.some(function (r) { return r.sub; });
    var width = Math.max(plot.clientWidth || 520, 320);

    /* Same problem as the bar chart: a release name is far wider than the
     * space between two points, so every label landed on its neighbours. */
    var longest = rows.reduce(function (n, r) {
      return Math.max(n, String(r.label || '').length);
    }, 0);
    var stepGuess = (width - 64) / Math.max(1, rows.length);
    var tilt = longest * 6.1 > stepGuess;
    var LABEL_CAP = 30;
    var tiltRoom = tilt ? Math.min(96, Math.min(longest, LABEL_CAP) * 4.6) : 0;

    var height = (hasSub ? 300 : 276) + tiltRoom;
    var margin = {
      top: 26, right: 18, left: 46,
      bottom: (hasSub ? 48 : 34) + tiltRoom
    };
    var innerW = width - margin.left - margin.right;
    var innerH = height - margin.top - margin.bottom;

    var step = rows.length > 1 ? innerW / (rows.length - 1) : 0;
    var xAt = function (i) { return rows.length > 1 ? margin.left + i * step : margin.left + innerW / 2; };
    var yAt = function (v) { return margin.top + innerH - v * innerH; };

    var svg = s('svg', {
      viewBox: '0 0 ' + width + ' ' + height, height: height,
      role: 'img', 'aria-label': opts.ariaLabel
    });

    [0, 0.25, 0.5, 0.75, 1].forEach(function (t) {
      var y = yAt(t);
      svg.appendChild(s('line', {
        class: t === 0 ? 'axisline' : 'gridline',
        x1: margin.left, x2: width - margin.right, y1: y, y2: y
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: margin.left - 8, y: y + 4, 'text-anchor': 'end',
        text: (t * 100).toFixed(0) + '%'
      }));
    });

    // Break the line where a period has no graded first attempt, rather than
    // interpolating across a gap that never happened.
    var segment = [];
    rows.forEach(function (row, i) {
      if (row.fpy === null || row.fpy === undefined) {
        if (segment.length > 1) svg.appendChild(line(segment));
        segment = [];
        return;
      }
      segment.push([xAt(i), yAt(row.fpy)]);
    });
    if (segment.length > 1) svg.appendChild(line(segment));

    function line(pts) {
      return s('path', {
        d: 'M' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join('L'),
        fill: 'none', stroke: 'var(--series-1)', 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      });
    }

    var labelEvery = tilt ? 1 : Math.max(1, Math.ceil((rows.length * 44) / innerW));

    rows.forEach(function (row, i) {
      if (row.fpy === null || row.fpy === undefined) return;
      var x = xAt(i), y = yAt(row.fpy);
      svg.appendChild(s('circle', {
        cx: x, cy: y, r: 4.5,
        fill: row.thin ? 'var(--surface-1)' : 'var(--series-1)',
        stroke: 'var(--series-1)', 'stroke-width': 2
      }));
      if (i % labelEvery === 0) {
        svg.appendChild(s('text', {
          class: 'bar-value', x: x, y: y - 10, 'text-anchor': 'middle',
          text: fmtPct(row.fpy, 1)
        }));
      }
    });

    rows.forEach(function (row, i) {
      if (i % labelEvery !== 0) return;
      var cx = xAt(i);
      var full = String(row.label || '');
      var shown = full.length > LABEL_CAP
        ? full.slice(0, LABEL_CAP - 1) + '\u2026' : full;
      var ly = tilt ? (margin.top + innerH + 14) : height - (hasSub ? 30 : 14);
      var label = s('text', {
        class: 'tick', x: cx, y: ly,
        'text-anchor': tilt ? 'end' : 'middle', text: shown
      });
      if (tilt) label.setAttribute('transform', 'rotate(-40 ' + cx + ' ' + ly + ')');
      if (shown !== full) label.appendChild(s('title', { text: full }));
      svg.appendChild(label);

      if (row.sub) {
        var sy = tilt ? (margin.top + innerH + 26) : height - 16;
        var sub = s('text', {
          class: 'x-sub', x: cx, y: sy,
          'text-anchor': tilt ? 'end' : 'middle', text: row.sub
        });
        if (tilt) sub.setAttribute('transform', 'rotate(-40 ' + cx + ' ' + sy + ')');
        svg.appendChild(sub);
      }
    });

    plot.appendChild(svg);
    var tip = makeTooltip(plot);
    var cursor = s('circle', { r: 6.5, fill: 'none', stroke: 'var(--text-primary)', 'stroke-width': 1.5, opacity: 0 });
    svg.appendChild(cursor);

    function show(i) {
      var row = rows[i];
      if (!row || row.fpy === null || row.fpy === undefined) { return; }
      cursor.setAttribute('cx', xAt(i));
      cursor.setAttribute('cy', yAt(row.fpy));
      cursor.setAttribute('opacity', '1');
      tip.show(xAt(i), yAt(row.fpy), [
        { color: 'var(--series-1)', name: 'first-pass yield', value: fmtPct(row.fpy) },
        { name: 'first attempts', value: row.fpyPass + ' / ' + row.fpyTotal },
        row.thin ? { name: 'sample', value: 'thin (<5)' } : null,
        { name: 'runs', value: fmtInt(row.total) }
      ].filter(Boolean), row.heading || row.label);
    }
    function hide() { cursor.setAttribute('opacity', '0'); tip.hide(); }

    var hit = s('rect', { class: 'hit', x: margin.left, y: margin.top, width: innerW, height: innerH });
    svg.appendChild(hit);

    function indexAt(e) {
      var box = svg.getBoundingClientRect();
      var lx = (e.clientX - box.left) * (width / box.width) - margin.left;
      return Math.max(0, Math.min(rows.length - 1, step ? Math.round(lx / step) : 0));
    }

    hit.addEventListener('pointermove', function (e) { show(indexAt(e)); });
    hit.addEventListener('pointerleave', hide);

    // The trend plots the FPY denominator, so its drill-down carries that
    // population — graded first attempts — not every run in the bucket.
    var activate = opts.onSelect ? function (i) {
      if (rows[i]) opts.onSelect(rows[i]);
    } : null;
    if (activate) {
      hit.setAttribute('class', 'hit drillable');
      hit.addEventListener('click', function (e) { activate(indexAt(e)); });
    }
    attachCursor(plot, rows.length, show, hide, activate);
  }

  /* ---------------------------------------------------------------- Pareto */

  /**
   * Classic Pareto: descending bars plus a cumulative-% line on a right axis,
   * with the 80% reference rule.
   *
   * This is the one place a second axis is used. It is the canonical form and
   * what the line already reads: the cumulative line is *derived from the same
   * counts as the bars* and is anchored (100% = the bar total), so it cannot
   * imply a relationship that is not in the data — unlike two independent
   * measures sharing a plot.
   */
  function renderPareto(plot, rows, opts) {
    opts = opts || {};
    clear(plot);
    if (!rows.length) { emptyPlot(plot, 'No failures in this window — nothing to rank.'); return; }

    var width = Math.max(plot.clientWidth || 700, 360);
    // top leaves room for the tallest bar's value label, which otherwise
    // escapes the plot and lands on the card subtitle.
    var margin = { top: 34, right: 52, bottom: 96, left: 48 };
    var height = 342;
    var innerW = width - margin.left - margin.right;
    var innerH = height - margin.top - margin.bottom;

    var ticks = niceTicks(Math.max.apply(null, rows.map(function (r) { return r.fails; })), 4);
    var yMax = ticks[ticks.length - 1];
    var band = innerW / rows.length;
    var barW = Math.min(46, Math.max(6, band - 14));
    var yAt = function (v) { return margin.top + innerH - (v / yMax) * innerH; };
    var yPct = function (p) { return margin.top + innerH - p * innerH; };

    var svg = s('svg', {
      viewBox: '0 0 ' + width + ' ' + height, height: height,
      role: 'img', 'aria-label': 'Failure Pareto by root-cause area with cumulative percentage'
    });

    ticks.forEach(function (t) {
      var y = yAt(t);
      svg.appendChild(s('line', {
        class: t === 0 ? 'axisline' : 'gridline',
        x1: margin.left, x2: width - margin.right, y1: y, y2: y
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: margin.left - 8, y: y + 4, 'text-anchor': 'end', text: fmtInt(t)
      }));
    });

    [0, 0.25, 0.5, 0.75, 1].forEach(function (p) {
      svg.appendChild(s('text', {
        class: 'ax-right', x: width - margin.right + 8, y: yPct(p) + 4,
        'text-anchor': 'start', text: (p * 100).toFixed(0) + '%'
      }));
    });

    svg.appendChild(s('line', {
      class: 'ref80', x1: margin.left, x2: width - margin.right, y1: yPct(0.8), y2: yPct(0.8)
    }));
    svg.appendChild(s('text', {
      class: 'x-sub', x: width - margin.right + 8, y: yPct(0.8) - 5, text: '80'
    }));

    var highlight = s('rect', {
      x: 0, y: margin.top, width: band, height: innerH,
      fill: 'var(--hover-wash)', opacity: 0, 'pointer-events': 'none'
    });
    svg.appendChild(highlight);

    rows.forEach(function (row, i) {
      var x = margin.left + i * band + (band - barW) / 2;
      var y = yAt(row.fails);
      svg.appendChild(s('path', {
        d: barPath(x, y, barW, margin.top + innerH - y, CORNER),
        fill: 'var(--series-1)'
      }));
      svg.appendChild(s('text', {
        class: 'bar-value', x: x + barW / 2, y: Math.max(11, y - 6),
        'text-anchor': 'middle', text: String(row.fails)
      }));

      // Area names are long; rotate them rather than truncating meaning away.
      var cx = margin.left + i * band + band / 2;
      svg.appendChild(s('text', {
        class: 'tick', x: cx, y: margin.top + innerH + 12,
        'text-anchor': 'end', transform: 'rotate(-35 ' + cx + ',' + (margin.top + innerH + 12) + ')',
        text: row.area
      }));
    });

    var pts = rows.map(function (row, i) {
      return [margin.left + i * band + band / 2, yPct(row.cumulativeShare)];
    });
    if (pts.length > 1) {
      svg.appendChild(s('path', {
        class: 'cum-line',
        d: 'M' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join('L')
      }));
    }
    pts.forEach(function (p) {
      svg.appendChild(s('rect', { class: 'cum-marker', x: p[0] - 3, y: p[1] - 3, width: 6, height: 6 }));
    });

    plot.appendChild(svg);
    var tip = makeTooltip(plot);

    function show(i) {
      var row = rows[i];
      if (!row) return;
      highlight.setAttribute('x', margin.left + i * band);
      highlight.setAttribute('opacity', '1');
      tip.show(margin.left + i * band + band / 2, margin.top + innerH / 2, [
        { color: 'var(--series-1)', name: 'fails', value: fmtInt(row.fails) },
        { name: 'share', value: fmtPct(row.share) },
        { name: 'cumulative', value: fmtPct(row.cumulativeShare) },
        { name: 'distinct DUTs', value: fmtInt(row.duts) },
        /* Which stations, not which single test. "top test" named one string
         * out of thirty and left the reader no better off; where a failure
         * happens is the first thing anyone asks, and it is the thing that
         * decides who owns it. */
        (row.byStation || []).length
          ? { name: 'stations', value: row.byStation.slice(0, 3).map(
                function (s) { return s.label + ' ' + s.fails; }).join(' · ') }
          : (row.topTest ? { name: 'top test', value: row.topTest } : null),
        opts.onSelect ? { name: '', value: 'click for the breakdown' } : null
      ].filter(Boolean), row.area);
    }
    function hide() { highlight.setAttribute('opacity', '0'); tip.hide(); }

    var hit = s('rect', { class: 'hit', x: margin.left, y: margin.top, width: innerW, height: innerH });
    svg.appendChild(hit);
    hit.addEventListener('pointermove', function (e) {
      var box = svg.getBoundingClientRect();
      var lx = (e.clientX - box.left) * (width / box.width) - margin.left;
      show(Math.max(0, Math.min(rows.length - 1, Math.floor(lx / band))));
    });
    hit.addEventListener('pointerleave', hide);

    /* A bar is a question, so it should be answerable. Without this the chart
     * could say "794 failures in Other" and offer no way to find out what they
     * were — which is how a Pareto becomes decoration. */
    function activate(i) {
      if (opts.onSelect && rows[i]) opts.onSelect(rows[i], i);
    }
    if (opts.onSelect) {
      plot.classList.add('is-clickable');
      hit.addEventListener('click', function (e) {
        var box = svg.getBoundingClientRect();
        var lx = (e.clientX - box.left) * (width / box.width) - margin.left;
        activate(Math.max(0, Math.min(rows.length - 1, Math.floor(lx / band))));
      });
    }
    attachCursor(plot, rows.length, show, hide, opts.onSelect ? activate : null);
  }

  /* ---------------------------------------------------------------- retest */

  function renderRetestDepth(plot, depth) {
    clear(plot);
    var rows = (depth || []).filter(function (d) { return d.units > 0; });
    if (!rows.length) { emptyPlot(plot, 'No units tested at this station.'); return; }

    var width = Math.max(plot.clientWidth || 520, 320);
    var height = 220;
    var margin = { top: 22, right: 12, bottom: 40, left: 44 };
    var innerW = width - margin.left - margin.right;
    var innerH = height - margin.top - margin.bottom;

    var ticks = niceTicks(Math.max.apply(null, rows.map(function (r) { return r.units; })), 4);
    var yMax = ticks[ticks.length - 1];
    var band = innerW / rows.length;
    var barW = Math.min(48, Math.max(8, band - 16));
    var yAt = function (v) { return margin.top + innerH - (v / yMax) * innerH; };

    var svg = s('svg', {
      viewBox: '0 0 ' + width + ' ' + height, height: height,
      role: 'img', 'aria-label': 'Units by number of attempts at this station'
    });

    ticks.forEach(function (t) {
      var y = yAt(t);
      svg.appendChild(s('line', {
        class: t === 0 ? 'axisline' : 'gridline',
        x1: margin.left, x2: width - margin.right, y1: y, y2: y
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: margin.left - 8, y: y + 4, 'text-anchor': 'end', text: fmtInt(t)
      }));
    });

    var tip = makeTooltip(plot);

    rows.forEach(function (row, i) {
      var x = margin.left + i * band + (band - barW) / 2;
      var y = yAt(row.units);
      // One attempt is the good outcome; anything beyond it is rework.
      var color = row.attempts === 1 ? 'var(--status-good)' : 'var(--series-2)';
      var rect = s('path', {
        d: barPath(x, y, barW, margin.top + innerH - y, CORNER),
        fill: color, class: 'mark', tabindex: '0',
        'aria-label': row.units + ' units with ' + row.attempts + ' attempts'
      });
      svg.appendChild(rect);
      svg.appendChild(s('text', {
        class: 'bar-value', x: x + barW / 2, y: y - 6, 'text-anchor': 'middle',
        text: String(row.units)
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: margin.left + i * band + band / 2, y: height - 20,
        'text-anchor': 'middle',
        text: row.attempts >= 5 ? '5+' : String(row.attempts)
      }));

      function show() {
        tip.show(x + barW / 2, y, [
          { color: color, name: 'units', value: fmtInt(row.units) },
          { name: 'attempts each', value: row.attempts >= 5 ? '5 or more' : String(row.attempts) }
        ], row.attempts === 1 ? 'First time through' : 'Retested');
      }
      rect.addEventListener('pointerenter', show);
      rect.addEventListener('focus', show);
      rect.addEventListener('pointerleave', tip.hide);
      rect.addEventListener('blur', tip.hide);
    });

    svg.appendChild(s('text', {
      class: 'x-sub', x: margin.left + innerW / 2, y: height - 4,
      'text-anchor': 'middle', text: 'ATTEMPTS PER UNIT'
    }));

    plot.appendChild(svg);
  }

  /* ---------------------------------------------------------------- tables */

  function renderTable(node, caption, columns, rows) {
    clear(node);
    if (!rows.length) {
      node.appendChild(h('div', { class: 'empty', text: 'Nothing to show.' }));
      return;
    }
    var table = h('table');
    table.appendChild(h('caption', { text: caption }));
    var head = h('tr');
    columns.forEach(function (c) { head.appendChild(h('th', { scope: 'col', text: c.label })); });
    table.appendChild(h('thead', null, head));
    var body = h('tbody');
    rows.forEach(function (row) {
      var tr = h('tr');
      columns.forEach(function (c, i) {
        var cell = h(i === 0 ? 'th' : 'td', i === 0 ? { scope: 'row' } : null);
        var text = c.get(row);
        // A column with href() renders as a drill-down link, underlined like
        // every other clickable number on the page. Zeroes stay plain text —
        // there are no rows behind them.
        var href = c.href && text !== '0' && text !== '—' ? c.href(row) : null;
        if (href) cell.appendChild(h('a', { class: 'drill-cell', href: href, text: text }));
        else cell.textContent = text;
        tr.appendChild(cell);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    node.appendChild(table);
  }

  function renderLegend(node, series) {
    clear(node);
    series.forEach(function (e) {
      node.appendChild(h('span', { class: 'item' }, [
        h('span', { class: 'key-rect', style: 'background:' + e.color }),
        h('span', { text: e.label })
      ]));
    });
  }

  /* ----------------------------------------------------------------- state */

  /* The breakdown behind one Pareto bar.
   *
   * Three questions, in the order they get asked: where did it fail, what
   * failed, and which units. Built here rather than on each page so the
   * station page and the week page cannot answer them differently.
   *
   * `dutHref` is optional — the station page can link a serial into the run
   * table, the week page has those rows on the page already. */
  function renderAreaDetail(host, row, opts) {
    opts = opts || {};
    clear(host);
    if (!row) { host.hidden = true; return; }
    host.hidden = false;

    var head = h('div', { class: 'pd-head' }, [
      h('h3', { class: 'pd-title', text: row.area }),
      h('span', { class: 'pd-sum', text:
        fmtInt(row.fails) + ' failing tests · ' + fmtPct(row.share) +
        ' of the window · ' + fmtInt(row.duts) + ' distinct units' +
        (row.testCount ? ' · ' + fmtInt(row.testCount) + ' distinct tests' : '') })
    ]);
    if (opts.onClose) {
      var close = h('button', { type: 'button', class: 'pd-close',
                                'aria-label': 'Close the breakdown', text: '\u00d7' });
      close.addEventListener('click', opts.onClose);
      head.appendChild(close);
    }
    host.appendChild(head);

    var grid = h('div', { class: 'pd-grid' });

    grid.appendChild(pdTable('Where it failed', ['Station', 'Fails', 'Units'],
      (row.byStation || []).map(function (s) {
        return [s.label, fmtInt(s.fails), fmtInt(s.duts)];
      }), 'No station recorded.'));

    grid.appendChild(pdTable('What failed', ['Test', 'Fails'],
      (row.byTest || []).map(function (t) { return [t.test, fmtInt(t.fails)]; }),
      'No test names recorded.',
      row.testCount > (row.byTest || []).length
        ? 'top ' + (row.byTest || []).length + ' of ' + row.testCount
        : null));

    grid.appendChild(pdTable('Units most affected', ['DUT SN', 'Fails'],
      (row.topDuts || []).map(function (d) {
        return [opts.dutHref ? h('a', { class: 'pd-link', href: opts.dutHref(d.dut),
                                        text: d.dut }) : d.dut,
                fmtInt(d.fails)];
      }), 'No serials recorded.'));

    host.appendChild(grid);
  }

  function pdTable(title, columns, rows, empty, note) {
    var card = h('div', { class: 'pd-card' }, [
      h('h4', { class: 'pd-h', text: title }),
      note ? h('span', { class: 'pd-note', text: note }) : null
    ]);
    if (!rows.length) {
      card.appendChild(h('p', { class: 'pd-empty', text: empty }));
      return card;
    }
    var table = h('table', { class: 'pd-table' });
    var thead = h('thead', {}, [h('tr', {}, columns.map(function (c, i) {
      return h('th', { scope: 'col', class: i ? 'n' : '', text: c });
    }))]);
    var tbody = h('tbody', {}, rows.map(function (cells) {
      return h('tr', {}, cells.map(function (value, i) {
        var td = h('td', { class: i ? 'n' : '' });
        if (value && value.nodeType) td.appendChild(value);
        else td.textContent = value;
        return td;
      }));
    }));
    table.appendChild(thead);
    table.appendChild(tbody);
    card.appendChild(h('div', { class: 'pd-wrap' }, [table]));
    return card;
  }

  window.FactoryCharts = {
    renderAreaDetail: renderAreaDetail,
    /* The pass / fail / abort series, exported because the legend beside a
     * mix chart is drawn by the page and has to name the same three in the
     * same colours as the bars. */
    MIX_SERIES: MIX_SERIES,
    h: h,
    s: s,
    build: build,
    clear: clear,
    measure: measure,
    fmtInt: fmtInt,
    fmtPct: fmtPct,
    fmtDayShort: fmtDayShort,
    fmtRange: fmtRange,
    dict: dict,
    ago: ago,
    minutesSince: minutesSince,
    niceTicks: niceTicks,
    makeTooltip: makeTooltip,
    attachCursor: attachCursor,
    emptyPlot: emptyPlot,
    barPath: barPath,
    renderMix: renderMix,
    renderTrend: renderTrend,
    renderPareto: renderPareto,
    renderRetestDepth: renderRetestDepth,
    renderTable: renderTable,
    renderLegend: renderLegend,
  };
})();
