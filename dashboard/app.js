/* Factory metrics dashboard.
 *
 * The bundle in data/metrics.js is run-level, not pre-aggregated: the filter row
 * re-slices it and every stat, chart and table re-aggregates from the same
 * slice, so the numbers on screen always agree with each other.
 *
 * Aggregation here mirrors src/factory/hourly.py. Definitions live in
 * docs/metrics.md; the Python side is the one pinned by unit tests.
 *
 * All label text comes from the API (station names, test names, DUT serials) and
 * is therefore untrusted — it only ever reaches the DOM through textContent.
 */
'use strict';

(function () {

  var DATA = window.__FACTORY_METRICS__;
  var SVG_NS = 'http://www.w3.org/2000/svg';

  /* ---------------------------------------------------------------- helpers */

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    applyAttrs(node, attrs);
    appendKids(node, kids);
    return node;
  }

  function s(tag, attrs, kids) {
    var node = document.createElementNS(SVG_NS, tag);
    applyAttrs(node, attrs);
    appendKids(node, kids);
    return node;
  }

  function applyAttrs(node, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === 'class') node.setAttribute('class', value);
      else if (key === 'text') node.textContent = value;      // never innerHTML
      else if (key === 'style') node.setAttribute('style', value);
      else if (key.indexOf('on') === 0 && typeof value === 'function') {
        node.addEventListener(key.slice(2), value);
      } else node.setAttribute(key, value);
    });
  }

  function appendKids(node, kids) {
    if (!kids) return;
    (Array.isArray(kids) ? kids : [kids]).forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
    });
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  var measureCanvas = document.createElement('canvas').getContext('2d');
  function measureText(text, font) {
    measureCanvas.font = font || '11px system-ui, -apple-system, sans-serif';
    return measureCanvas.measureText(text).width;
  }

  function truncate(text, max) {
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }

  /* -------------------------------------------------------------- formatters */

  function fmtInt(value) {
    return value === null || value === undefined ? '—' : Math.round(value).toLocaleString();
  }

  function fmtNum(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    return value.toFixed(digits === undefined ? 1 : digits);
  }

  function fmtPct(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return '—';
    return (value * 100).toFixed(digits === undefined ? 1 : digits) + '%';
  }

  function fmtDur(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return '—';
    if (seconds < 90) return Math.round(seconds) + 's';
    var mins = Math.floor(seconds / 60);
    var secs = Math.round(seconds % 60);
    if (secs === 60) { mins += 1; secs = 0; }
    return mins + 'm ' + (secs < 10 ? '0' : '') + secs + 's';
  }

  /* ----------------------------------------------------------- time bucketing */

  var TZ = (DATA && DATA.timezone) || 'UTC';
  var hourParts;
  try {
    hourParts = new Intl.DateTimeFormat('en-CA', {
      timeZone: TZ, year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', hour12: false
    });
  } catch (err) {
    hourParts = new Intl.DateTimeFormat('en-CA', {
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hour12: false
    });
  }

  var hourKeyCache = Object.create(null);

  /** Bucket a UTC epoch second into a local hour label, YYYY-MM-DDTHH. */
  function hourKey(ts) {
    var bucket = Math.floor(ts / 3600) * 3600;
    var cached = hourKeyCache[bucket];
    if (cached) return cached;
    var parts = {};
    hourParts.formatToParts(new Date(bucket * 1000)).forEach(function (part) {
      parts[part.type] = part.value;
    });
    var hour = parts.hour === '24' ? '00' : parts.hour;
    var key = parts.year + '-' + parts.month + '-' + parts.day + 'T' + hour;
    hourKeyCache[bucket] = key;
    return key;
  }

  /**
   * Every hour label between two instants, including hours with no runs — a
   * quiet hour is a zero on the timeline, not a missing column.
   */
  function hourSequence(minTs, maxTs) {
    var keys = [];
    var seen = Object.create(null);
    for (var ts = Math.floor(minTs / 3600) * 3600; ts <= maxTs; ts += 3600) {
      var key = hourKey(ts);
      if (!seen[key]) { seen[key] = true; keys.push(key); }
    }
    if (!keys.length) keys.push(hourKey(minTs));
    return keys;
  }

  function hourLabel(key) { return key.slice(11, 13); }
  function dayLabel(key) { return key.slice(5, 10); }

  /* ------------------------------------------------------------ aggregation */

  function percentile(values, fraction) {
    var sorted = values.filter(function (v) {
      return v !== null && v !== undefined && !isNaN(v);
    }).sort(function (a, b) { return a - b; });
    if (!sorted.length) return null;
    if (sorted.length === 1) return sorted[0];
    var position = fraction * (sorted.length - 1);
    var lower = Math.floor(position);
    var upper = Math.min(lower + 1, sorted.length - 1);
    var weight = position - lower;
    return sorted[lower] * (1 - weight) + sorted[upper] * weight;
  }

  var SCORED = { pass: 1, fail: 1, error: 1 };

  function summarize(runs) {
    var hours = {};
    var units = {};
    var scored = 0, passed = 0, firstAttempts = 0, fpyPassed = 0, failures = 0;
    var durations = [];

    runs.forEach(function (run) {
      hours[hourKey(run.t)] = true;
      if (run.dut) units[run.dut] = true;
      if (SCORED[run.s]) { scored += 1; if (run.s === 'pass') passed += 1; }
      if (run.a === 1) { firstAttempts += 1; if (run.s === 'pass') fpyPassed += 1; }
      if (run.d !== null && run.d !== undefined) durations.push(run.d);
      failures += (run.f || []).length;
    });

    var activeHours = Object.keys(hours).length;
    var unitCount = Object.keys(units).length;
    return {
      runs: runs.length,
      units: unitCount,
      activeHours: activeHours,
      unitsPerHour: activeHours ? unitCount / activeHours : null,
      runsPerHour: activeHours ? runs.length / activeHours : null,
      passRate: scored ? passed / scored : null,
      firstPassYield: firstAttempts ? fpyPassed / firstAttempts : null,
      cycleTimeMedian: percentile(durations, 0.5),
      cycleTimeP90: percentile(durations, 0.9),
      failedRuns: runs.filter(function (r) { return r.s === 'fail' || r.s === 'error'; }).length,
      testFailures: failures
    };
  }

  /** One row per hour across the whole span, zero-filled. */
  function hourlyRows(runs) {
    if (!runs.length) return [];
    var min = Infinity, max = -Infinity;
    runs.forEach(function (run) {
      if (run.t < min) min = run.t;
      if (run.t > max) max = run.t;
    });

    var grouped = Object.create(null);
    runs.forEach(function (run) {
      var key = hourKey(run.t);
      (grouped[key] || (grouped[key] = [])).push(run);
    });

    return hourSequence(min, max).map(function (key) {
      var bucket = grouped[key] || [];
      var passed = 0, failed = 0, errored = 0, firstAttempts = 0, fpyPassed = 0;
      var durations = [], units = {}, stations = Object.create(null);
      var testsRun = 0, testsFailed = 0;

      bucket.forEach(function (run) {
        if (run.s === 'pass') passed += 1;
        else if (run.s === 'fail') failed += 1;
        else if (run.s === 'error') errored += 1;
        if (run.a === 1) { firstAttempts += 1; if (run.s === 'pass') fpyPassed += 1; }
        if (run.d !== null && run.d !== undefined) durations.push(run.d);
        if (run.dut) units[run.dut] = true;
        stations[run.st] = (stations[run.st] || 0) + 1;
        testsRun += run.nt || 0;
        testsFailed += run.nf || 0;
      });

      var scored = passed + failed + errored;
      return {
        hour: key,
        runs: bucket.length,
        units: Object.keys(units).length,
        passed: passed,
        failed: failed,
        errored: errored,
        passRate: scored ? passed / scored : null,
        firstAttempts: firstAttempts,
        firstPassYield: firstAttempts ? fpyPassed / firstAttempts : null,
        cycleTimeMedian: percentile(durations, 0.5),
        cycleTimeP90: percentile(durations, 0.9),
        testsRun: testsRun,
        testsFailed: testsFailed,
        stations: stations
      };
    });
  }

  function paretoRows(runs, limit) {
    var counts = Object.create(null);
    var codes = Object.create(null);
    var duts = Object.create(null);

    runs.forEach(function (run) {
      (run.f || []).forEach(function (failure) {
        var name = failure.t || '(unnamed)';
        counts[name] = (counts[name] || 0) + 1;
        if (failure.c) {
          var perTest = codes[name] || (codes[name] = Object.create(null));
          perTest[failure.c] = (perTest[failure.c] || 0) + 1;
        }
        if (run.dut) (duts[name] || (duts[name] = Object.create(null)))[run.dut] = true;
      });
    });

    var total = Object.keys(counts).reduce(function (sum, key) { return sum + counts[key]; }, 0);
    var ranked = Object.keys(counts).sort(function (a, b) {
      return counts[b] - counts[a] || a.localeCompare(b);
    }).slice(0, limit || 12);

    var cumulative = 0;
    return ranked.map(function (name) {
      cumulative += counts[name];
      var perTest = codes[name] || {};
      var topCode = Object.keys(perTest).sort(function (a, b) {
        return perTest[b] - perTest[a];
      })[0] || null;
      return {
        test: name,
        failures: counts[name],
        share: total ? counts[name] / total : 0,
        cumulativeShare: total ? cumulative / total : 0,
        duts: Object.keys(duts[name] || {}).length,
        topCode: topCode
      };
    });
  }

  function stationRows(runs) {
    var grouped = Object.create(null);
    runs.forEach(function (run) {
      (grouped[run.st] || (grouped[run.st] = [])).push(run);
    });
    return Object.keys(grouped).map(function (station) {
      var bucket = grouped[station];
      var scored = bucket.filter(function (r) { return SCORED[r.s]; });
      var passed = scored.filter(function (r) { return r.s === 'pass'; }).length;
      var units = Object.create(null);
      bucket.forEach(function (r) { if (r.dut) units[r.dut] = true; });
      return {
        station: station,
        runs: bucket.length,
        units: Object.keys(units).length,
        passRate: scored.length ? passed / scored.length : null,
        cycleTimeMedian: percentile(bucket.map(function (r) { return r.d; }), 0.5)
      };
    }).sort(function (a, b) { return b.runs - a.runs; });
  }

  function dutRows(runs, limit) {
    var grouped = Object.create(null);
    runs.forEach(function (run) {
      if (run.dut) (grouped[run.dut] || (grouped[run.dut] = [])).push(run);
    });
    return Object.keys(grouped).map(function (dut) {
      var bucket = grouped[dut].slice().sort(function (a, b) { return a.t - b.t; });
      var stations = Object.create(null);
      bucket.forEach(function (r) { stations[r.st] = true; });
      return {
        dut: dut,
        runs: bucket.length,
        failures: bucket.filter(function (r) { return r.s === 'fail' || r.s === 'error'; }).length,
        lastStatus: bucket[bucket.length - 1].s,
        stations: Object.keys(stations).sort().join(', ')
      };
    }).filter(function (row) { return row.failures > 1; })
      .sort(function (a, b) { return b.failures - a.failures || b.runs - a.runs; })
      .slice(0, limit || 20);
  }

  /* ------------------------------------------------------------------ scales */

  function niceTicks(max, count) {
    if (!isFinite(max) || max <= 0) return [0, 1];
    var rough = max / (count || 5);
    var magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
    var normalized = rough / magnitude;
    var step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
    var ticks = [];
    for (var value = 0; value <= max + step * 0.5; value += step) {
      ticks.push(Math.round(value * 1e6) / 1e6);
    }
    return ticks.length > 1 ? ticks : [0, step];
  }

  var TIME_STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400];

  /** Ticks that land on readable clock intervals rather than raw round numbers. */
  function niceTimeTicks(max, count) {
    if (!isFinite(max) || max <= 0) return [0, 60];
    var target = max / (count || 4);
    var step = TIME_STEPS[TIME_STEPS.length - 1];
    for (var i = 0; i < TIME_STEPS.length; i += 1) {
      if (TIME_STEPS[i] >= target) { step = TIME_STEPS[i]; break; }
    }
    var ticks = [];
    for (var value = 0; value <= max + step * 0.5; value += step) ticks.push(value);
    return ticks.length > 1 ? ticks : [0, step];
  }

  /**
   * Day labels under the hour axis: one per midnight, plus the leading partial
   * day — but only when it will not collide with the first midnight label.
   */
  function dayLabelIndices(rows, xAt) {
    var indices = [];
    rows.forEach(function (row, index) {
      if (hourLabel(row.hour) === '00') indices.push(index);
    });
    if (!indices.length || xAt(indices[0]) - xAt(0) > 46) indices.unshift(0);
    return indices;
  }

  /* ---------------------------------------------------------------- tooltip */

  function makeTooltip(plot) {
    var node = h('div', { class: 'tooltip', role: 'status' });
    plot.appendChild(node);
    return {
      node: node,
      show: function (x, y, rows, heading) {
        clear(node);
        if (heading) node.appendChild(h('div', { class: 'tt-head', text: heading }));
        rows.forEach(function (row) {
          node.appendChild(h('div', { class: 'tt-row' }, [
            row.color ? h('span', {
              class: 'tt-key' + (row.block ? ' block' : ''),
              style: 'background:' + row.color
            }) : null,
            h('span', { class: 'tt-name', text: row.name }),
            h('span', { class: 'tt-value', text: row.value })
          ]));
        });
        node.setAttribute('data-open', 'true');
        var width = node.offsetWidth || 170;
        var height = node.offsetHeight || 60;
        var left = Math.max(4, Math.min(x + 14, plot.clientWidth - width - 4));
        var top = Math.max(4, Math.min(y - height / 2, plot.clientHeight - height - 4));
        node.style.left = left + 'px';
        node.style.top = top + 'px';
      },
      hide: function () { node.setAttribute('data-open', 'false'); }
    };
  }

  /**
   * A shared pointer/keyboard cursor over an indexed chart.
   *
   * The plot is one focus stop, not one per mark: arrow keys walk the index and
   * fire the same callback hover does, so keyboard users get the same readout
   * without a hundred tab stops.
   */
  function attachCursor(plot, count, onMove, onLeave) {
    var index = -1;

    function set(next) {
      index = Math.max(0, Math.min(count - 1, next));
      onMove(index, 'keyboard');
    }

    plot.setAttribute('tabindex', '0');
    plot.setAttribute('role', 'application');

    plot.addEventListener('keydown', function (event) {
      if (!count) return;
      if (event.key === 'ArrowRight') { set(index < 0 ? 0 : index + 1); event.preventDefault(); }
      else if (event.key === 'ArrowLeft') { set(index < 0 ? count - 1 : index - 1); event.preventDefault(); }
      else if (event.key === 'Home') { set(0); event.preventDefault(); }
      else if (event.key === 'End') { set(count - 1); event.preventDefault(); }
      else if (event.key === 'Escape') { index = -1; onLeave(); }
    });
    plot.addEventListener('blur', function () { index = -1; onLeave(); });
  }

  /* ------------------------------------------------------- stacked columns */

  var COLUMN_HEIGHT = 250;
  var SEGMENT_GAP = 2;       // surface gap — white does the separating
  var MAX_BAR = 24;          // never fill the band; leftover is air
  var CORNER = 4;

  function barPath(x, y, width, height, radius) {
    var r = Math.max(0, Math.min(radius, width / 2, height));
    return 'M' + x + ',' + (y + height) +
      'L' + x + ',' + (y + r) +
      'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
      'L' + (x + width - r) + ',' + y +
      'Q' + (x + width) + ',' + y + ' ' + (x + width) + ',' + (y + r) +
      'L' + (x + width) + ',' + (y + height) + 'Z';
  }

  function renderStackedColumns(plot, config) {
    clear(plot);
    var rows = config.rows;
    if (!rows.length) { plot.appendChild(h('div', { class: 'empty', text: 'No runs in this slice.' })); return; }

    var width = Math.max(plot.clientWidth || 520, 320);
    var margin = { top: 14, right: 12, bottom: 36, left: 46 };
    var innerW = width - margin.left - margin.right;
    var innerH = COLUMN_HEIGHT - margin.top - margin.bottom;

    var totals = rows.map(function (row) {
      return config.series.reduce(function (sum, series) { return sum + (row.values[series.key] || 0); }, 0);
    });
    var ticks = niceTicks(Math.max.apply(null, totals.concat([1])), 4);
    var yMax = ticks[ticks.length - 1];
    var band = innerW / rows.length;
    var barWidth = Math.min(MAX_BAR, Math.max(3, band - 6));

    var svg = s('svg', {
      viewBox: '0 0 ' + width + ' ' + COLUMN_HEIGHT,
      height: COLUMN_HEIGHT,
      role: 'img',
      'aria-label': config.ariaLabel
    });

    var yScale = function (value) { return margin.top + innerH - (value / yMax) * innerH; };

    ticks.forEach(function (tick) {
      var y = yScale(tick);
      svg.appendChild(s('line', {
        class: tick === 0 ? 'axisline' : 'gridline',
        x1: margin.left, x2: width - margin.right, y1: y, y2: y
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: margin.left - 8, y: y + 4, 'text-anchor': 'end', text: fmtInt(tick)
      }));
    });

    var hoverLayer = s('g', {});
    svg.appendChild(hoverLayer);

    rows.forEach(function (row, index) {
      var x = margin.left + index * band + (band - barWidth) / 2;
      var stackTop = margin.top + innerH;
      var topSeriesIndex = -1;
      config.series.forEach(function (series, si) {
        if ((row.values[series.key] || 0) > 0) topSeriesIndex = si;
      });

      config.series.forEach(function (series, si) {
        var value = row.values[series.key] || 0;
        if (value <= 0) return;
        var rawHeight = (value / yMax) * innerH;
        var height = Math.max(1, rawHeight - (si === topSeriesIndex ? 0 : 0));
        var y = stackTop - rawHeight;
        // Trim the top of every non-topmost segment to leave a 2px surface gap.
        var drawHeight = rawHeight;
        var drawY = y;
        if (si !== topSeriesIndex && drawHeight > SEGMENT_GAP + 1) {
          drawHeight -= SEGMENT_GAP;
        } else if (si !== topSeriesIndex) {
          drawHeight = Math.max(1, drawHeight);
        }
        svg.appendChild(s('path', {
          d: barPath(x, drawY, barWidth, drawHeight, si === topSeriesIndex ? CORNER : 0),
          fill: series.color
        }));
        stackTop -= rawHeight;
        void height;
      });
    });

    // X axis: hour labels, thinned to fit, with a date marker at each midnight.
    var labelEvery = Math.max(1, Math.ceil((rows.length * 22) / innerW));
    rows.forEach(function (row, index) {
      if (index % labelEvery !== 0) return;
      var x = margin.left + index * band + band / 2;
      svg.appendChild(s('text', {
        class: 'tick', x: x, y: COLUMN_HEIGHT - 18, 'text-anchor': 'middle', text: hourLabel(row.hour)
      }));
    });
    var columnX = function (index) { return margin.left + index * band + band / 2; };
    dayLabelIndices(rows, columnX).forEach(function (index) {
      svg.appendChild(s('text', {
        class: 'axis-title', x: columnX(index), y: COLUMN_HEIGHT - 4,
        'text-anchor': index === 0 ? 'start' : 'middle', text: dayLabel(rows[index].hour)
      }));
    });

    plot.appendChild(svg);
    var tooltip = makeTooltip(plot);

    var highlight = s('rect', {
      x: 0, y: margin.top, width: band, height: innerH,
      fill: 'var(--hover-wash)', opacity: 0, 'pointer-events': 'none'
    });
    hoverLayer.appendChild(highlight);

    function showIndex(index, source) {
      var row = rows[index];
      if (!row) return;
      highlight.setAttribute('x', margin.left + index * band);
      highlight.setAttribute('opacity', '1');
      var entries = config.series.map(function (series) {
        return {
          color: series.color, block: true, name: series.label,
          value: fmtInt(row.values[series.key] || 0)
        };
      });
      entries.push({ name: 'Total', value: fmtInt(totals[index]) });
      var x = source === 'keyboard'
        ? margin.left + index * band + band / 2
        : margin.left + index * band + band / 2;
      tooltip.show(x, margin.top + innerH / 2, entries, config.heading(row));
    }

    function hide() { highlight.setAttribute('opacity', '0'); tooltip.hide(); }

    var hit = s('rect', {
      class: 'hit', x: margin.left, y: margin.top, width: innerW, height: innerH
    });
    svg.appendChild(hit);
    hit.addEventListener('pointermove', function (event) {
      var box = svg.getBoundingClientRect();
      var scale = width / box.width;
      var localX = (event.clientX - box.left) * scale - margin.left;
      showIndex(Math.max(0, Math.min(rows.length - 1, Math.floor(localX / band))), 'pointer');
    });
    hit.addEventListener('pointerleave', hide);
    attachCursor(plot, rows.length, showIndex, hide);
  }

  /* ------------------------------------------------------------ line charts */

  var LINE_HEIGHT = 250;

  function renderLines(plot, config) {
    clear(plot);
    var rows = config.rows;
    if (!rows.length) { plot.appendChild(h('div', { class: 'empty', text: 'No runs in this slice.' })); return; }

    var width = Math.max(plot.clientWidth || 520, 320);
    var margin = { top: 16, right: 58, bottom: 36, left: 52 };
    var innerW = width - margin.left - margin.right;
    var innerH = LINE_HEIGHT - margin.top - margin.bottom;

    var allValues = [];
    config.series.forEach(function (series) {
      rows.forEach(function (row) {
        var value = series.get(row);
        if (value !== null && value !== undefined && !isNaN(value)) allValues.push(value);
      });
    });

    var maxValue = allValues.length ? Math.max.apply(null, allValues) : 1;
    var ticks = config.percent
      ? [0, 0.25, 0.5, 0.75, 1]
      : (config.timeAxis ? niceTimeTicks(maxValue, 4) : niceTicks(maxValue, 4));
    var yMax = config.percent ? 1 : ticks[ticks.length - 1];

    var step = rows.length > 1 ? innerW / (rows.length - 1) : 0;
    var xAt = function (index) {
      return rows.length > 1 ? margin.left + index * step : margin.left + innerW / 2;
    };
    var yAt = function (value) { return margin.top + innerH - (value / yMax) * innerH; };

    var svg = s('svg', {
      viewBox: '0 0 ' + width + ' ' + LINE_HEIGHT,
      height: LINE_HEIGHT,
      role: 'img',
      'aria-label': config.ariaLabel
    });

    ticks.forEach(function (tick) {
      var y = yAt(tick);
      svg.appendChild(s('line', {
        class: tick === 0 ? 'axisline' : 'gridline',
        x1: margin.left, x2: width - margin.right, y1: y, y2: y
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: margin.left - 8, y: y + 4, 'text-anchor': 'end',
        text: config.fmtTick(tick)
      }));
    });

    var labelEvery = Math.max(1, Math.ceil((rows.length * 26) / innerW));
    rows.forEach(function (row, index) {
      if (index % labelEvery !== 0) return;
      svg.appendChild(s('text', {
        class: 'tick', x: xAt(index), y: LINE_HEIGHT - 18, 'text-anchor': 'middle',
        text: hourLabel(row.hour)
      }));
    });
    dayLabelIndices(rows, xAt).forEach(function (index) {
      svg.appendChild(s('text', {
        class: 'axis-title', x: xAt(index), y: LINE_HEIGHT - 4,
        'text-anchor': index === 0 ? 'start' : 'middle', text: dayLabel(rows[index].hour)
      }));
    });

    // One polyline per series, broken at gaps so a quiet hour is not
    // interpolated over as if it had data.
    var endPoints = [];
    config.series.forEach(function (series) {
      var segment = [];
      var lastPoint = null;
      rows.forEach(function (row, index) {
        var value = series.get(row);
        if (value === null || value === undefined || isNaN(value)) {
          if (segment.length > 1) svg.appendChild(polyline(segment, series.color));
          else if (segment.length === 1) svg.appendChild(dot(segment[0], series.color));
          segment = [];
          return;
        }
        var point = [xAt(index), yAt(value)];
        segment.push(point);
        lastPoint = { point: point, value: value };
      });
      if (segment.length > 1) svg.appendChild(polyline(segment, series.color));
      else if (segment.length === 1) svg.appendChild(dot(segment[0], series.color));
      if (lastPoint) endPoints.push({ series: series, point: lastPoint.point, value: lastPoint.value });
    });

    function polyline(points, color) {
      return s('path', {
        d: 'M' + points.map(function (p) { return p[0] + ',' + p[1]; }).join('L'),
        fill: 'none', stroke: color, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'
      });
    }

    function dot(point, color) {
      return s('circle', {
        cx: point[0], cy: point[1], r: 4.5, fill: color,
        stroke: 'var(--surface-1)', 'stroke-width': 2
      });
    }

    // Direct labels on the endpoint only — selective, never one per point.
    // When endpoints converge, push them apart and draw a leader.
    endPoints.sort(function (a, b) { return a.point[1] - b.point[1]; });
    var placed = [];
    endPoints.forEach(function (entry) {
      var y = entry.point[1];
      placed.forEach(function (other) {
        if (Math.abs(y - other) < 14) y = other + 14;
      });
      placed.push(y);
      svg.appendChild(s('circle', {
        cx: entry.point[0], cy: entry.point[1], r: 4.5, fill: entry.series.color,
        stroke: 'var(--surface-1)', 'stroke-width': 2
      }));
      if (Math.abs(y - entry.point[1]) > 1) {
        svg.appendChild(s('line', {
          x1: entry.point[0] + 6, y1: entry.point[1], x2: entry.point[0] + 12, y2: y - 4,
          stroke: 'var(--axis)', 'stroke-width': 1
        }));
      }
      svg.appendChild(s('text', {
        class: 'point-label', x: entry.point[0] + 9, y: y, 'dominant-baseline': 'middle',
        text: config.fmtValue(entry.value)
      }));
    });

    plot.appendChild(svg);
    var tooltip = makeTooltip(plot);

    var crosshair = s('line', {
      class: 'crosshair', y1: margin.top, y2: margin.top + innerH, opacity: 0
    });
    svg.appendChild(crosshair);

    var cursorDots = config.series.map(function (series) {
      var node = s('circle', {
        r: 4.5, fill: series.color, stroke: 'var(--surface-1)', 'stroke-width': 2,
        opacity: 0, 'pointer-events': 'none'
      });
      svg.appendChild(node);
      return node;
    });

    function showIndex(index) {
      var row = rows[index];
      if (!row) return;
      var x = xAt(index);
      crosshair.setAttribute('x1', x);
      crosshair.setAttribute('x2', x);
      crosshair.setAttribute('opacity', '1');

      var entries = config.series.map(function (series, si) {
        var value = series.get(row);
        var known = value !== null && value !== undefined && !isNaN(value);
        cursorDots[si].setAttribute('opacity', known ? '1' : '0');
        if (known) {
          cursorDots[si].setAttribute('cx', x);
          cursorDots[si].setAttribute('cy', yAt(value));
        }
        return {
          color: series.color, name: series.label,
          value: known ? config.fmtValue(value) : '—'
        };
      });
      if (config.extraRows) entries = entries.concat(config.extraRows(row));
      tooltip.show(x, margin.top + innerH / 2, entries, config.heading(row));
    }

    function hide() {
      crosshair.setAttribute('opacity', '0');
      cursorDots.forEach(function (node) { node.setAttribute('opacity', '0'); });
      tooltip.hide();
    }

    var hit = s('rect', {
      class: 'hit', x: margin.left, y: margin.top, width: innerW, height: innerH
    });
    svg.appendChild(hit);
    hit.addEventListener('pointermove', function (event) {
      var box = svg.getBoundingClientRect();
      var scale = width / box.width;
      var localX = (event.clientX - box.left) * scale - margin.left;
      var index = step ? Math.round(localX / step) : 0;
      showIndex(Math.max(0, Math.min(rows.length - 1, index)));
    });
    hit.addEventListener('pointerleave', hide);
    attachCursor(plot, rows.length, showIndex, hide);
  }

  /* -------------------------------------------------------- horizontal bars */

  function renderPareto(plot, rows) {
    clear(plot);
    if (!rows.length) {
      plot.appendChild(h('div', { class: 'empty', text: 'No failures in this slice — nothing to rank.' }));
      return;
    }

    var width = Math.max(plot.clientWidth || 640, 360);
    var rowHeight = 30;
    var barHeight = 18;                       // ≤ 24px; the band keeps its air
    var margin = { top: 6, right: 92, bottom: 26, left: 0 };

    // Reserve exactly the width the longest (truncated) name needs, so labels
    // never collide with the plot and never get clipped.
    var font = '12px system-ui, -apple-system, sans-serif';
    var names = rows.map(function (row) { return truncate(row.test, 34); });
    var nameWidth = Math.min(
      280,
      Math.max.apply(null, names.map(function (name) { return measureText(name, font); })) + 14
    );
    margin.left = nameWidth;

    var height = margin.top + rows.length * rowHeight + margin.bottom;
    var innerW = width - margin.left - margin.right;
    var maxValue = Math.max.apply(null, rows.map(function (row) { return row.failures; }));
    var ticks = niceTicks(maxValue, 4);
    var xMax = ticks[ticks.length - 1];

    var svg = s('svg', {
      viewBox: '0 0 ' + width + ' ' + height, height: height, role: 'img',
      'aria-label': 'Failing tests ranked by number of runs affected'
    });

    ticks.forEach(function (tick) {
      var x = margin.left + (tick / xMax) * innerW;
      svg.appendChild(s('line', {
        class: tick === 0 ? 'axisline' : 'gridline',
        x1: x, x2: x, y1: margin.top, y2: margin.top + rows.length * rowHeight
      }));
      svg.appendChild(s('text', {
        class: 'tick', x: x, y: height - 8, 'text-anchor': 'middle', text: fmtInt(tick)
      }));
    });

    var tooltip = makeTooltip(plot);
    var highlight = s('rect', {
      x: 0, y: 0, width: width, height: rowHeight,
      fill: 'var(--hover-wash)', opacity: 0, 'pointer-events': 'none'
    });
    svg.appendChild(highlight);

    rows.forEach(function (row, index) {
      var y = margin.top + index * rowHeight;
      var barWidth = Math.max(2, (row.failures / xMax) * innerW);

      svg.appendChild(s('text', {
        class: 'tick', x: margin.left - 10, y: y + rowHeight / 2 + 4,
        'text-anchor': 'end', 'font-size': 12, text: names[index]
      }));

      // 4px rounded data-end, square where it meets the baseline.
      svg.appendChild(s('path', {
        d: 'M' + margin.left + ',' + (y + (rowHeight - barHeight) / 2) +
          'h' + (barWidth - CORNER) +
          'a' + CORNER + ',' + CORNER + ' 0 0 1 ' + CORNER + ',' + CORNER +
          'v' + (barHeight - 2 * CORNER) +
          'a' + CORNER + ',' + CORNER + ' 0 0 1 ' + (-CORNER) + ',' + CORNER +
          'H' + margin.left + 'Z',
        fill: 'var(--series-1)'
      }));

      // Value at the tip, in text ink — the mark beside it carries identity.
      svg.appendChild(s('text', {
        class: 'point-label', x: margin.left + barWidth + 8, y: y + rowHeight / 2 + 4,
        text: fmtInt(row.failures) + '  ·  ' + fmtPct(row.share, 0)
      }));
    });

    function showIndex(index) {
      var row = rows[index];
      if (!row) return;
      highlight.setAttribute('y', margin.top + index * rowHeight);
      highlight.setAttribute('opacity', '1');
      var entries = [
        { color: 'var(--series-1)', block: true, name: 'Runs affected', value: fmtInt(row.failures) },
        { name: 'Share of failures', value: fmtPct(row.share) },
        { name: 'Cumulative', value: fmtPct(row.cumulativeShare) },
        { name: 'Distinct DUTs', value: fmtInt(row.duts) }
      ];
      if (row.topCode) entries.push({ name: 'Top code', value: row.topCode });
      tooltip.show(margin.left + innerW / 2, margin.top + index * rowHeight + rowHeight / 2,
        entries, row.test);
    }

    function hide() { highlight.setAttribute('opacity', '0'); tooltip.hide(); }

    var hit = s('rect', {
      class: 'hit', x: 0, y: margin.top, width: width, height: rows.length * rowHeight
    });
    svg.appendChild(hit);
    hit.addEventListener('pointermove', function (event) {
      var box = svg.getBoundingClientRect();
      var scale = height / box.height;
      var localY = (event.clientY - box.top) * scale - margin.top;
      showIndex(Math.max(0, Math.min(rows.length - 1, Math.floor(localY / rowHeight))));
    });
    hit.addEventListener('pointerleave', hide);

    plot.appendChild(svg);
    attachCursor(plot, rows.length, showIndex, hide);
  }

  /* ---------------------------------------------------------------- legends */

  function renderLegend(node, series, kind) {
    clear(node);
    series.forEach(function (entry) {
      node.appendChild(h('span', { class: 'item' }, [
        h('span', {
          class: kind === 'line' ? 'key-line' : 'key-rect',
          style: 'background:' + entry.color
        }),
        h('span', { text: entry.label })
      ]));
    });
  }

  /* ----------------------------------------------------------------- tables */

  function renderTable(node, caption, columns, rows) {
    clear(node);
    var table = h('table');
    table.appendChild(h('caption', { text: caption }));
    var head = h('tr');
    columns.forEach(function (column) { head.appendChild(h('th', { scope: 'col', text: column.label })); });
    table.appendChild(h('thead', null, head));

    var body = h('tbody');
    rows.forEach(function (row) {
      var tr = h('tr');
      columns.forEach(function (column, index) {
        var content = column.render ? column.render(row) : String(column.get(row));
        var cell = h(index === 0 ? 'th' : 'td', index === 0 ? { scope: 'row' } : null);
        if (content instanceof Node) cell.appendChild(content);
        else cell.textContent = content;
        tr.appendChild(cell);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    node.appendChild(table);
  }

  function statusCell(status) {
    var glyphs = { pass: '✓', fail: '✕', error: '⚠', skip: '–', unknown: '?' };
    return h('span', { class: 'status ' + status }, [
      h('span', { class: 'glyph', 'aria-hidden': 'true', text: glyphs[status] || '?' }),
      h('span', { text: status })
    ]);
  }

  /* ------------------------------------------------------------ stat tiles */

  function sparkline(values, width, height) {
    var known = values.filter(function (v) { return v !== null && v !== undefined && !isNaN(v); });
    if (known.length < 2) return null;
    var min = Math.min.apply(null, known);
    var max = Math.max.apply(null, known);
    var span = max - min || 1;
    var step = width / (values.length - 1);
    var points = [];
    values.forEach(function (value, index) {
      if (value === null || value === undefined || isNaN(value)) return;
      points.push([index * step, height - ((value - min) / span) * (height - 4) - 2]);
    });
    if (points.length < 2) return null;

    var svg = s('svg', {
      class: 'spark', width: width, height: height,
      viewBox: '0 0 ' + width + ' ' + height, 'aria-hidden': 'true', focusable: 'false'
    });
    svg.appendChild(s('path', {
      d: 'M' + points.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join('L'),
      fill: 'none', stroke: 'var(--text-muted)', 'stroke-width': 1.5,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));
    var last = points[points.length - 1];
    svg.appendChild(s('circle', {
      cx: last[0], cy: last[1], r: 2.5, fill: 'var(--series-1)'
    }));
    return svg;
  }

  function renderTile(spec) {
    var delta = null;
    if (spec.previous !== null && spec.previous !== undefined &&
        spec.current !== null && spec.current !== undefined && spec.previous !== 0) {
      var change = (spec.current - spec.previous) / Math.abs(spec.previous);
      var rising = change > 0;
      var good = spec.higherIsBetter ? rising : !rising;
      var negligible = Math.abs(change) < 0.005;
      delta = h('span', {
        class: 'delta' + (negligible ? '' : good ? ' good' : ' bad'),
        title: 'vs the previous ' + spec.periodLabel
      }, [
        h('span', { class: 'cue', 'aria-hidden': 'true', text: negligible ? '→' : rising ? '↑' : '↓' }),
        ' ' + (negligible ? 'flat' : (Math.abs(change) * 100).toFixed(0) + '%')
      ]);
    }

    return h('div', { class: 'card tile' }, [
      h('div', { class: 'label', text: spec.label }),
      h('div', { class: 'value', text: spec.display }),
      h('div', { class: 'foot' }, [
        delta || h('span', { class: 'delta', text: spec.note || '' }),
        spec.spark
      ])
    ]);
  }

  /* ------------------------------------------------------------------ state */

  var state = { range: 'all', level: '', station: '', suite: '' };

  var refs = {
    meta: document.getElementById('meta'),
    banner: document.getElementById('demo-banner'),
    rangeGroup: document.getElementById('range-group'),
    level: document.getElementById('filter-level'),
    station: document.getElementById('filter-station'),
    suite: document.getElementById('filter-suite'),
    count: document.getElementById('slice-count'),
    heroValue: document.getElementById('hero-value'),
    heroUnit: document.getElementById('hero-unit'),
    tiles: document.getElementById('tiles'),
    footer: document.getElementById('footer-meta'),
    theme: document.getElementById('theme-toggle')
  };

  function matchesDimensions(run) {
    if (state.level && run.lv !== state.level) return false;
    if (state.station && run.st !== state.station) return false;
    if (state.suite && run.su !== state.suite) return false;
    return true;
  }

  function slice() {
    var byDimension = DATA.runs.filter(matchesDimensions);
    if (state.range === 'all' || !byDimension.length) {
      return { current: byDimension, previous: [], periodLabel: null };
    }
    var hours = parseInt(state.range, 10);
    var anchor = byDimension.reduce(function (max, run) { return Math.max(max, run.t); }, 0);
    var start = anchor - hours * 3600;
    var previousStart = start - hours * 3600;
    return {
      current: byDimension.filter(function (run) { return run.t >= start; }),
      previous: byDimension.filter(function (run) { return run.t >= previousStart && run.t < start; }),
      periodLabel: hours + ' hours'
    };
  }

  /* ----------------------------------------------------------------- render */

  var STATION_SLOTS = [
    'var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)',
    'var(--series-5)', 'var(--series-6)', 'var(--series-7)'
  ];

  /**
   * Station -> color, decided ONCE from the whole dataset and never
   * recomputed.
   *
   * If this were ranked within the current slice, filtering to a shorter range
   * would repaint the surviving stations and a reader who learned "ST-03 is
   * blue" would be misled. Color follows the entity, not its row number.
   * Stations past the eighth slot fold into a neutral "Other" — hues are never
   * cycled or generated.
   */
  var STATION_COLORS = (function () {
    var totals = Object.create(null);
    (DATA && DATA.runs ? DATA.runs : []).forEach(function (run) {
      totals[run.st] = (totals[run.st] || 0) + 1;
    });
    var ranked = Object.keys(totals).sort(function (a, b) {
      return totals[b] - totals[a] || a.localeCompare(b);
    });
    var assignment = { order: [], color: Object.create(null), other: [] };
    ranked.forEach(function (station, index) {
      if (index < STATION_SLOTS.length) {
        assignment.order.push(station);
        assignment.color[station] = STATION_SLOTS[index];
      } else {
        assignment.other.push(station);
      }
    });
    return assignment;
  })();

  function render() {
    var selection = slice();
    var runs = selection.current;
    var rows = hourlyRows(runs);
    var head = summarize(runs);
    var previousHead = selection.previous.length ? summarize(selection.previous) : null;

    refs.count.textContent = runs.length.toLocaleString() + ' runs · ' +
      head.units.toLocaleString() + ' units · ' + head.activeHours + ' active hours';

    renderHead(head, previousHead, rows, selection.periodLabel);
    renderOutcome(rows);
    renderYield(rows);
    renderCycle(rows);
    renderStations(rows, runs);
    renderParetoCard(runs);
    renderStationTable(runs);
    renderDutTable(runs);
  }

  function renderHead(head, previous, rows, periodLabel) {
    refs.heroValue.textContent = head.unitsPerHour === null ? '—' : fmtNum(head.unitsPerHour, 1);
    refs.heroUnit.textContent = 'units started per active hour · ' +
      fmtNum(head.runsPerHour, 1) + ' runs/h across ' + head.activeHours + ' hours';

    var last12 = rows.slice(-12);
    var label = periodLabel || 'period';

    var specs = [
      {
        label: 'First-pass yield', display: fmtPct(head.firstPassYield),
        current: head.firstPassYield, previous: previous && previous.firstPassYield,
        higherIsBetter: true, periodLabel: label,
        spark: sparkline(last12.map(function (r) { return r.firstPassYield; }), 68, 24),
        note: 'first attempt per DUT'
      },
      {
        label: 'Pass rate', display: fmtPct(head.passRate),
        current: head.passRate, previous: previous && previous.passRate,
        higherIsBetter: true, periodLabel: label,
        spark: sparkline(last12.map(function (r) { return r.passRate; }), 68, 24),
        note: 'all attempts'
      },
      {
        label: 'Cycle time (p50)', display: fmtDur(head.cycleTimeMedian),
        current: head.cycleTimeMedian, previous: previous && previous.cycleTimeMedian,
        higherIsBetter: false, periodLabel: label,
        spark: sparkline(last12.map(function (r) { return r.cycleTimeMedian; }), 68, 24),
        note: 'p90 ' + fmtDur(head.cycleTimeP90)
      },
      {
        label: 'Runs', display: fmtInt(head.runs),
        current: head.runs, previous: previous && previous.runs,
        higherIsBetter: true, periodLabel: label,
        spark: sparkline(last12.map(function (r) { return r.runs; }), 68, 24),
        note: fmtInt(head.units) + ' distinct units'
      },
      {
        label: 'Failed runs', display: fmtInt(head.failedRuns),
        current: head.failedRuns, previous: previous && previous.failedRuns,
        higherIsBetter: false, periodLabel: label,
        spark: sparkline(last12.map(function (r) { return r.failed + r.errored; }), 68, 24),
        note: fmtInt(head.testFailures) + ' test failures'
      }
    ];

    clear(refs.tiles);
    specs.forEach(function (spec) { refs.tiles.appendChild(renderTile(spec)); });
  }

  function heading(row) {
    return dayLabel(row.hour) + ' · ' + hourLabel(row.hour) + ':00–' +
      hourLabel(row.hour) + ':59';
  }

  function renderOutcome(rows) {
    // Status colors, not categorical slots — these segments *mean* pass/fail.
    var series = [
      { key: 'passed', label: 'Passed', color: 'var(--status-good)' },
      { key: 'errored', label: 'Errored', color: 'var(--status-serious)' },
      { key: 'failed', label: 'Failed', color: 'var(--status-critical)' }
    ];
    renderLegend(document.getElementById('legend-outcome'), series, 'rect');
    renderStackedColumns(document.getElementById('plot-outcome'), {
      rows: rows.map(function (row) {
        return { hour: row.hour, values: { passed: row.passed, errored: row.errored, failed: row.failed } };
      }),
      series: series,
      heading: heading,
      ariaLabel: 'Stacked columns of runs per hour split by pass, error and fail'
    });
    renderTable(document.getElementById('table-outcome'),
      'Runs per hour by outcome',
      [
        { label: 'Hour', get: function (r) { return r.hour.replace('T', ' ') + ':00'; } },
        { label: 'Runs', get: function (r) { return fmtInt(r.runs); } },
        { label: 'Passed', get: function (r) { return fmtInt(r.passed); } },
        { label: 'Errored', get: function (r) { return fmtInt(r.errored); } },
        { label: 'Failed', get: function (r) { return fmtInt(r.failed); } },
        { label: 'Units', get: function (r) { return fmtInt(r.units); } }
      ], rows);
  }

  function renderYield(rows) {
    var series = [
      { key: 'fpy', label: 'First-pass yield', color: 'var(--series-1)', get: function (r) { return r.firstPassYield; } },
      { key: 'pass', label: 'Pass rate', color: 'var(--series-2)', get: function (r) { return r.passRate; } }
    ];
    renderLegend(document.getElementById('legend-yield'), series, 'line');
    renderLines(document.getElementById('plot-yield'), {
      rows: rows, series: series, percent: true,
      fmtTick: function (v) { return (v * 100).toFixed(0) + '%'; },
      fmtValue: function (v) { return fmtPct(v, 0); },
      heading: heading,
      extraRows: function (row) {
        return [{ name: 'Runs', value: fmtInt(row.runs) }];
      },
      ariaLabel: 'Line chart of first-pass yield and pass rate per hour'
    });
    renderTable(document.getElementById('table-yield'),
      'Yield by hour',
      [
        { label: 'Hour', get: function (r) { return r.hour.replace('T', ' ') + ':00'; } },
        { label: 'First-pass yield', get: function (r) { return fmtPct(r.firstPassYield); } },
        { label: 'First attempts', get: function (r) { return fmtInt(r.firstAttempts); } },
        { label: 'Pass rate', get: function (r) { return fmtPct(r.passRate); } },
        { label: 'Runs', get: function (r) { return fmtInt(r.runs); } }
      ], rows);
  }

  function renderCycle(rows) {
    var series = [
      { key: 'p50', label: 'Median', color: 'var(--series-1)', get: function (r) { return r.cycleTimeMedian; } },
      { key: 'p90', label: '90th percentile', color: 'var(--series-2)', get: function (r) { return r.cycleTimeP90; } }
    ];
    renderLegend(document.getElementById('legend-cycle'), series, 'line');
    renderLines(document.getElementById('plot-cycle'), {
      rows: rows, series: series, percent: false, timeAxis: true,
      fmtTick: function (v) { return v >= 60 ? (v / 60) + 'm' : Math.round(v) + 's'; },
      fmtValue: function (v) { return fmtDur(v); },
      heading: heading,
      ariaLabel: 'Line chart of median and 90th percentile run duration per hour'
    });
    renderTable(document.getElementById('table-cycle'),
      'Cycle time by hour',
      [
        { label: 'Hour', get: function (r) { return r.hour.replace('T', ' ') + ':00'; } },
        { label: 'Median', get: function (r) { return fmtDur(r.cycleTimeMedian); } },
        { label: 'p90', get: function (r) { return fmtDur(r.cycleTimeP90); } },
        { label: 'Runs', get: function (r) { return fmtInt(r.runs); } }
      ], rows);
  }

  function renderStations(rows, runs) {
    // Only show stations present in this slice, but keep each one's dataset-wide
    // color and position — the survivors of a filter never get repainted.
    var present = Object.create(null);
    runs.forEach(function (run) { present[run.st] = true; });

    var named = STATION_COLORS.order.filter(function (station) { return present[station]; });
    var tail = STATION_COLORS.other.filter(function (station) { return present[station]; });

    var series = named.map(function (station) {
      return { key: station, label: station, color: STATION_COLORS.color[station] };
    });
    if (tail.length) {
      series.push({
        key: '__other__',
        label: 'Other (' + tail.length + ' station' + (tail.length === 1 ? '' : 's') + ')',
        color: 'var(--series-other)'
      });
    }

    renderLegend(document.getElementById('legend-station'), series, 'rect');
    renderStackedColumns(document.getElementById('plot-station'), {
      rows: rows.map(function (row) {
        var values = Object.create(null);
        named.forEach(function (station) { values[station] = row.stations[station] || 0; });
        if (tail.length) {
          values.__other__ = tail.reduce(function (sum, station) {
            return sum + (row.stations[station] || 0);
          }, 0);
        }
        return { hour: row.hour, values: values };
      }),
      series: series,
      heading: heading,
      ariaLabel: 'Stacked columns of runs per hour split by station'
    });

    var columns = [{ label: 'Hour', get: function (r) { return r.hour.replace('T', ' ') + ':00'; } }];
    series.forEach(function (entry) {
      columns.push({
        label: entry.label,
        get: function (r) {
          if (entry.key === '__other__') {
            return fmtInt(tail.reduce(function (sum, st) { return sum + (r.stations[st] || 0); }, 0));
          }
          return fmtInt(r.stations[entry.key] || 0);
        }
      });
    });
    renderTable(document.getElementById('table-station'), 'Runs per hour by station', columns, rows);
  }

  function renderParetoCard(runs) {
    var rows = paretoRows(runs, 12);
    renderPareto(document.getElementById('plot-pareto'), rows);
    renderTable(document.getElementById('table-pareto'),
      'Failing tests, ranked',
      [
        { label: 'Test', get: function (r) { return r.test; } },
        { label: 'Runs affected', get: function (r) { return fmtInt(r.failures); } },
        { label: 'Share', get: function (r) { return fmtPct(r.share); } },
        { label: 'Cumulative', get: function (r) { return fmtPct(r.cumulativeShare); } },
        { label: 'DUTs', get: function (r) { return fmtInt(r.duts); } },
        { label: 'Top code', get: function (r) { return r.topCode || '—'; } }
      ], rows);
  }

  function renderStationTable(runs) {
    renderTable(document.getElementById('table-stations-table'),
      'Per-station totals across the selection',
      [
        { label: 'Station', get: function (r) { return r.station; } },
        { label: 'Runs', get: function (r) { return fmtInt(r.runs); } },
        { label: 'Units', get: function (r) { return fmtInt(r.units); } },
        { label: 'Pass rate', get: function (r) { return fmtPct(r.passRate); } },
        { label: 'Cycle p50', get: function (r) { return fmtDur(r.cycleTimeMedian); } }
      ], stationRows(runs));
  }

  function renderDutTable(runs) {
    var rows = dutRows(runs, 20);
    var node = document.getElementById('table-duts');
    if (!rows.length) {
      clear(node);
      node.appendChild(h('div', { class: 'empty', text: 'No unit failed more than once in this slice.' }));
      return;
    }
    renderTable(node, 'Units with more than one failing run',
      [
        { label: 'DUT serial', get: function (r) { return r.dut; } },
        { label: 'Runs', get: function (r) { return fmtInt(r.runs); } },
        { label: 'Failures', get: function (r) { return fmtInt(r.failures); } },
        { label: 'Last result', render: function (r) { return statusCell(r.lastStatus); } },
        { label: 'Stations', get: function (r) { return r.stations; } }
      ], rows);
  }

  /* ------------------------------------------------------------------ wiring */

  function fillSelect(node, values, allLabel) {
    clear(node);
    node.appendChild(h('option', { value: '', text: allLabel }));
    values.forEach(function (value) {
      node.appendChild(h('option', { value: value, text: value }));
    });
  }

  function wire() {
    fillSelect(refs.level, DATA.levels || [], 'All levels');
    fillSelect(refs.station, DATA.stations || [], 'All stations');
    fillSelect(refs.suite, DATA.suites || [], 'All suites');

    ['level', 'station', 'suite'].forEach(function (key) {
      refs[key].addEventListener('change', function () {
        state[key] = refs[key].value;
        render();
      });
    });

    refs.rangeGroup.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-range]');
      if (!button) return;
      state.range = button.getAttribute('data-range');
      Array.prototype.forEach.call(refs.rangeGroup.querySelectorAll('button'), function (node) {
        node.setAttribute('aria-pressed', node === button ? 'true' : 'false');
      });
      render();
    });

    document.addEventListener('click', function (event) {
      var toggle = event.target.closest('.view-toggle');
      if (!toggle) return;
      var card = toggle.getAttribute('data-toggle');
      var table = document.getElementById('table-' + card);
      var plot = document.getElementById('plot-' + card);
      var showTable = toggle.getAttribute('aria-pressed') !== 'true';
      toggle.setAttribute('aria-pressed', showTable ? 'true' : 'false');
      toggle.textContent = showTable ? 'Chart' : 'Table';
      table.hidden = !showTable;
      plot.hidden = showTable;
    });

    var initialTheme = document.documentElement.getAttribute('data-theme');
    refs.theme.textContent = 'Theme: ' + (initialTheme || 'system');

    refs.theme.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme');
      var next = current === 'dark' ? 'light' : current === 'light' ? null : 'dark';
      if (next) document.documentElement.setAttribute('data-theme', next);
      else document.documentElement.removeAttribute('data-theme');
      refs.theme.textContent = 'Theme: ' + (next || 'system');
      render();   // re-resolve the CSS variables the SVG marks were painted with
    });

    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(render, 140);
    });
  }

  function boot() {
    if (!DATA || !DATA.runs) {
      document.getElementById('content').appendChild(h('div', { class: 'card empty' },
        'No data bundle found. Run `make demo` (synthetic) or `make collect build` (live API).'));
      return;
    }

    var window_ = DATA.window || {};
    refs.meta.textContent = (window_.from || '?') + ' → ' + (window_.to || '?') +
      '  ·  hours in ' + TZ;
    if (DATA.source === 'demo') refs.banner.hidden = false;

    var notes = DATA.notes || {};
    var footerBits = ['Built ' + (DATA.generatedAt || 'unknown') + ' from ' +
      DATA.runs.length.toLocaleString() + ' runs.'];
    if (notes.runsDroppedNoTimestamp) {
      footerBits.push(notes.runsDroppedNoTimestamp +
        ' run(s) were dropped for having no usable start time.');
    }
    if (notes.problems && notes.problems.length) {
      footerBits.push(notes.problems.length + ' collection problem(s) recorded in data/processed/runs.json.');
    }
    refs.footer.textContent = footerBits.join(' ');

    wire();
    render();
    void cssVar;
  }

  boot();
})();
