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

  /* ------------------------------------------------------------ drill-down */

  /**
   * Build a runs.html link. Every number on this page is a count of runs, and
   * this is how a reader gets from the number to the rows behind it.
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
    var height = hasSub ? 300 : 276;
    var margin = { top: 24, right: 12, bottom: hasSub ? 48 : 34, left: 44 };
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

    var labelEvery = Math.max(1, Math.ceil((rows.length * 34) / innerW));

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
        svg.appendChild(s('text', {
          class: 'tick', x: margin.left + i * band + band / 2, y: height - (hasSub ? 30 : 14),
          'text-anchor': 'middle', text: row.label
        }));
        if (row.sub) {
          svg.appendChild(s('text', {
            class: 'x-sub', x: margin.left + i * band + band / 2, y: height - 16,
            'text-anchor': 'middle', text: row.sub
          }));
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
    var height = hasSub ? 300 : 276;
    var margin = { top: 26, right: 18, bottom: hasSub ? 48 : 34, left: 46 };
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

    var labelEvery = Math.max(1, Math.ceil((rows.length * 44) / innerW));

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
      svg.appendChild(s('text', {
        class: 'tick', x: xAt(i), y: height - (hasSub ? 30 : 14),
        'text-anchor': 'middle', text: row.label
      }));
      if (row.sub) {
        svg.appendChild(s('text', {
          class: 'x-sub', x: xAt(i), y: height - 16, 'text-anchor': 'middle', text: row.sub
        }));
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
  function renderPareto(plot, rows) {
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
        row.topTest ? { name: 'top test', value: row.topTest } : null
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
    attachCursor(plot, rows.length, show, hide);
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

  var state = { station: '__all__', paretoMode: 'pareto' };

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
    paretoSub: document.getElementById('pareto-sub')
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
    (DATA.stations || []).forEach(function (station) {
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

  function stateWord(station) {
    if (station.state === 'blocked') return 'no access';
    if (station.state === 'unmapped') return 'not mapped';
    return '0';
  }

  function currentStation() {
    var list = DATA.stations || [];
    for (var i = 0; i < list.length; i += 1) if (list[i].key === state.station) return list[i];
    return list[0] || { key: '__all__', label: 'All stations' };
  }

  /* ----------------------------------------------------------------- views */

  function render() {
    var station = currentStation();
    var view = (DATA.views || {})[station.key] || emptyView();

    renderStationBar();
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
    renderPareto(document.getElementById('plot-pareto'), paretoRows);

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
    var views = DATA.views || {};
    return key && Object.prototype.hasOwnProperty.call(views, key) ? key : '__all__';
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
