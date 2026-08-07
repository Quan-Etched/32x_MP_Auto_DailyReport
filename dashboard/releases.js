/* Test items by release, and the compatibility diff between releases.
 *
 * Two formats, per the brief: a graph layer (what changed / coverage per
 * release) and a table layer (the release list, and the full item catalogue
 * inside the drawer). Clicking a release opens a drawer holding everything for
 * that release, with each change group and each item independently expandable.
 *
 * The index bundle carries the release table, the diffs and the numeric trends.
 * Each release's full item signature list is a separate JSON file fetched on
 * open — ~700 items x 21 releases inline would be a 1.5 MB landing page.
 *
 * Item names, units and step names come from the API and reach the DOM only via
 * textContent.
 */
'use strict';

(function () {

  var DATA = window.__FACTORY_RELEASES__;
  var SVG = 'http://www.w3.org/2000/svg';

  /* ---------------------------------------------------------------- helpers */

  function h(tag, attrs, kids) { return build(document.createElement(tag), attrs, kids); }
  function s(tag, attrs, kids) { return build(document.createElementNS(SVG, tag), attrs, kids); }

  function build(node, attrs, kids) {
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'text') node.textContent = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    });
    if (kids) (Array.isArray(kids) ? kids : [kids]).forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
    });
    return node;
  }

  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function fmtInt(v) { return v === null || v === undefined ? '—' : Math.round(v).toLocaleString(); }

  /** Significant-figure formatting: these values span BER (1e-11) to Hz (1e9). */
  function fmtNum(v) {
    if (v === null || v === undefined || v === '') return '—';
    var n = Number(v);
    if (isNaN(n)) return String(v);
    if (n === 0) return '0';
    var a = Math.abs(n);
    if (a >= 1e6 || a < 1e-3) return n.toExponential(3).replace('e', 'e');
    if (a >= 100) return n.toFixed(0);
    if (a >= 1) return n.toFixed(2);
    return n.toPrecision(3);
  }

  function fmtPct(v) {
    return (v === null || v === undefined) ? '—' : (v * 100).toFixed(0) + '%';
  }

  function fmtDay(ts) {
    if (!ts) return '—';
    var d = new Date(ts * 1000);
    return d.toISOString().slice(5, 10).replace('-', '/');
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

  function tooltipFor(plot) {
    var node = h('div', { class: 'tooltip', role: 'status' });
    plot.appendChild(node);
    return {
      show: function (x, y, rows, head) {
        clear(node);
        if (head) node.appendChild(h('div', { class: 'tt-head', text: head }));
        rows.forEach(function (r) {
          node.appendChild(h('div', { class: 'tt-row' }, [
            r.color ? h('span', { class: 'tt-key block', style: 'background:' + r.color }) : null,
            h('span', { class: 'tt-name', text: r.name }),
            h('span', { class: 'tt-value', text: r.value })
          ]));
        });
        node.setAttribute('data-open', 'true');
        var w = node.offsetWidth || 190, ht = node.offsetHeight || 60;
        node.style.left = Math.max(4, Math.min(x + 14, plot.clientWidth - w - 4)) + 'px';
        node.style.top = Math.max(4, Math.min(y - ht / 2, plot.clientHeight - ht - 4)) + 'px';
      },
      hide: function () { node.setAttribute('data-open', 'false'); }
    };
  }

  var CORNER = 4, GAP = 2;

  function barPath(x, y, w, hh, r) {
    var rr = Math.max(0, Math.min(r, w / 2, hh));
    return 'M' + x + ',' + (y + hh) + 'L' + x + ',' + (y + rr) +
      'Q' + x + ',' + y + ' ' + (x + rr) + ',' + y +
      'L' + (x + w - rr) + ',' + y +
      'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + rr) +
      'L' + (x + w) + ',' + (y + hh) + 'Z';
  }

  /* ------------------------------------------------------------------ state */

  var state = { station: null };

  var refs = {
    meta: document.getElementById('meta'),
    notice: document.getElementById('notice'),
    bar: document.getElementById('stationbar'),
    footer: document.getElementById('footer-meta'),
    theme: document.getElementById('theme-toggle'),
    drawer: document.getElementById('drawer'),
    backdrop: document.getElementById('backdrop'),
    drawerTitle: document.getElementById('drawer-title'),
    drawerSub: document.getElementById('drawer-sub'),
    drawerBody: document.getElementById('drawer-body'),
    drawerClose: document.getElementById('drawer-close')
  };

  function stationsWithData() {
    var seen = [];
    (DATA.releases || []).forEach(function (r) {
      if (seen.indexOf(r.station) < 0) seen.push(r.station);
    });
    return seen;
  }

  function label(station) {
    return (DATA.stationLabels || {})[station] || station;
  }

  function releasesFor(station) {
    return (DATA.releases || []).filter(function (r) { return r.station === station; });
  }

  function diffsFor(station) {
    return (DATA.diffs || []).filter(function (d) { return d.station === station; });
  }

  function diffTo(station, release) {
    return diffsFor(station).filter(function (d) { return d.to === release; })[0] || null;
  }

  /* -------------------------------------------- graph 1: churn per release */

  // Three series, not seven: added / removed / edited. The seven change KINDS
  // would be an unreadable stack and would blow past the "~7 colour classes"
  // ceiling; the kind breakdown lives in the drawer, where it can be read.
  var CHURN = [
    { key: 'added', label: 'added', color: 'var(--status-good)' },
    { key: 'changed', label: 'edited', color: 'var(--status-warning)' },
    { key: 'removed', label: 'removed', color: 'var(--status-critical)' }
  ];

  function renderChurn() {
    var plot = document.getElementById('plot-churn');
    clear(plot);
    var diffs = diffsFor(state.station);
    if (!diffs.length) {
      plot.appendChild(h('div', { class: 'empty',
        text: 'Only one release collected for this station — nothing to compare yet.' }));
      renderChurnTable(diffs);
      return;
    }

    var width = Math.max(plot.clientWidth || 560, 320);
    var height = 312;
    var m = { top: 26, right: 12, bottom: 68, left: 46 };
    var iw = width - m.left - m.right, ih = height - m.top - m.bottom;

    var totals = diffs.map(function (d) {
      return d.totals.added + d.totals.changed + d.totals.removed;
    });
    var ticks = niceTicks(Math.max.apply(null, totals.concat([1])), 4);
    var yMax = ticks[ticks.length - 1];
    var band = iw / diffs.length;
    var bw = Math.min(38, Math.max(6, band - 12));
    var yAt = function (v) { return m.top + ih - (v / yMax) * ih; };

    var svg = s('svg', { viewBox: '0 0 ' + width + ' ' + height, height: height,
      role: 'img', 'aria-label': 'Items added, edited and removed per release' });

    ticks.forEach(function (t) {
      var y = yAt(t);
      svg.appendChild(s('line', { class: t === 0 ? 'axisline' : 'gridline',
        x1: m.left, x2: width - m.right, y1: y, y2: y }));
      svg.appendChild(s('text', { class: 'tick', x: m.left - 8, y: y + 4,
        'text-anchor': 'end', text: fmtInt(t) }));
    });

    var hi = s('rect', { x: 0, y: m.top, width: band, height: ih,
      fill: 'var(--hover-wash)', opacity: 0, 'pointer-events': 'none' });
    svg.appendChild(hi);

    diffs.forEach(function (d, i) {
      var x = m.left + i * band + (band - bw) / 2;
      var bottom = m.top + ih;
      var top = -1;
      CHURN.forEach(function (ser, si) { if (d.totals[ser.key] > 0) top = si; });

      CHURN.forEach(function (ser, si) {
        var v = d.totals[ser.key] || 0;
        if (v <= 0) return;
        var raw = (v / yMax) * ih, y = bottom - raw;
        var dh = si === top ? raw : Math.max(1, raw - GAP);
        svg.appendChild(s('path', { d: barPath(x, y, bw, dh, si === top ? CORNER : 0),
          fill: ser.color, opacity: d.confidence === 'low' ? 0.55 : 1 }));
        bottom -= raw;
      });

      var total = d.totals.added + d.totals.changed + d.totals.removed;
      if (total > 0) {
        svg.appendChild(s('text', { class: 'bar-value', x: x + bw / 2,
          y: Math.max(11, yAt(total) - 6), 'text-anchor': 'middle', text: String(total) }));
      }
      var cx = m.left + i * band + band / 2;
      svg.appendChild(s('text', { class: 'tick', x: cx, y: height - 50,
        'text-anchor': 'middle', text: d.to }));
      svg.appendChild(s('text', { class: 'x-sub', x: cx, y: height - 38,
        'text-anchor': 'middle', text: 'from ' + d.from }));
      // A low-confidence comparison must look different, not just read
      // differently in a tooltip.
      if (d.confidence === 'low') {
        svg.appendChild(s('text', { class: 'x-sub', x: cx, y: height - 26,
          'text-anchor': 'middle', fill: 'var(--status-warning)', text: 'low conf' }));
      }
    });

    svg.appendChild(s('text', { class: 'x-sub', x: m.left + iw / 2, y: height - 1,
      'text-anchor': 'middle', text: 'RELEASE (vs PREVIOUS)' }));

    plot.appendChild(svg);
    var tip = tooltipFor(plot);
    var hit = s('rect', { class: 'hit', x: m.left, y: m.top, width: iw, height: ih });
    svg.appendChild(hit);

    function show(i) {
      var d = diffs[i];
      if (!d) return;
      hi.setAttribute('x', m.left + i * band);
      hi.setAttribute('opacity', '1');
      var rows = CHURN.map(function (ser) {
        return { color: ser.color, name: ser.label, value: fmtInt(d.totals[ser.key]) };
      });
      rows.push({ name: 'unchanged', value: fmtInt(d.totals.unchanged) });
      if (d.confidence === 'low') rows.push({ name: 'confidence', value: 'low' });
      tip.show(m.left + i * band + band / 2, m.top + ih / 2, rows,
        d.from + ' → ' + d.to);
    }
    function hide() { hi.setAttribute('opacity', '0'); tip.hide(); }

    hit.addEventListener('pointermove', function (e) {
      var box = svg.getBoundingClientRect();
      var lx = (e.clientX - box.left) * (width / box.width) - m.left;
      show(Math.max(0, Math.min(diffs.length - 1, Math.floor(lx / band))));
    });
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('click', function (e) {
      var box = svg.getBoundingClientRect();
      var lx = (e.clientX - box.left) * (width / box.width) - m.left;
      var d = diffs[Math.max(0, Math.min(diffs.length - 1, Math.floor(lx / band)))];
      if (d) openRelease(state.station, d.to);
    });

    renderChurnTable(diffs);
  }

  function renderChurnTable(diffs) {
    renderTable(document.getElementById('table-churn'),
      [{ label: 'From → to' }, { label: 'Added' }, { label: 'Edited' },
       { label: 'Removed' }, { label: 'Unchanged' }, { label: 'Confidence' },
       { label: 'Kinds' }],
      diffs.map(function (d) {
        return [d.from + ' → ' + d.to, fmtInt(d.totals.added), fmtInt(d.totals.changed),
          fmtInt(d.totals.removed), fmtInt(d.totals.unchanged), d.confidence,
          Object.keys(d.counts).sort().map(function (k) {
            return k + '=' + d.counts[k];
          }).join(', ') || '—'];
      }));
  }

  /* ------------------------------------------ graph 2: coverage per release */

  function renderCoverage() {
    var plot = document.getElementById('plot-coverage');
    clear(plot);
    var rels = releasesFor(state.station);
    if (!rels.length) { plot.appendChild(h('div', { class: 'empty', text: 'No data.' })); return; }

    var width = Math.max(plot.clientWidth || 560, 320);
    var height = 312;
    var m = { top: 26, right: 12, bottom: 68, left: 52 };
    var iw = width - m.left - m.right, ih = height - m.top - m.bottom;

    var ticks = niceTicks(Math.max.apply(null, rels.map(function (r) { return r.items; })), 4);
    var yMax = ticks[ticks.length - 1];
    var band = iw / rels.length;
    var bw = Math.min(38, Math.max(6, band - 12));
    var yAt = function (v) { return m.top + ih - (v / yMax) * ih; };

    var svg = s('svg', { viewBox: '0 0 ' + width + ' ' + height, height: height,
      role: 'img', 'aria-label': 'Distinct test items measured per release' });

    ticks.forEach(function (t) {
      var y = yAt(t);
      svg.appendChild(s('line', { class: t === 0 ? 'axisline' : 'gridline',
        x1: m.left, x2: width - m.right, y1: y, y2: y }));
      svg.appendChild(s('text', { class: 'tick', x: m.left - 8, y: y + 4,
        'text-anchor': 'end', text: fmtInt(t) }));
    });

    var hi = s('rect', { x: 0, y: m.top, width: band, height: ih,
      fill: 'var(--hover-wash)', opacity: 0, 'pointer-events': 'none' });
    svg.appendChild(hi);

    rels.forEach(function (r, i) {
      var x = m.left + i * band + (band - bw) / 2;
      var y = yAt(r.items);
      svg.appendChild(s('path', { d: barPath(x, y, bw, m.top + ih - y, CORNER),
        fill: 'var(--series-1)', opacity: r.confident ? 1 : 0.55 }));
      svg.appendChild(s('text', { class: 'bar-value', x: x + bw / 2, y: Math.max(11, y - 6),
        'text-anchor': 'middle', text: String(r.items) }));
      var cx = m.left + i * band + band / 2;
      svg.appendChild(s('text', { class: 'tick', x: cx, y: height - 50,
        'text-anchor': 'middle', text: r.release }));
      svg.appendChild(s('text', { class: 'x-sub', x: cx, y: height - 38,
        'text-anchor': 'middle', text: r.runs + (r.runs === 1 ? ' run' : ' runs') }));
      if (!r.confident) {
        svg.appendChild(s('text', { class: 'x-sub', x: cx, y: height - 26,
          'text-anchor': 'middle', fill: 'var(--status-warning)', text: 'thin' }));
      }
    });

    svg.appendChild(s('text', { class: 'x-sub', x: m.left + iw / 2, y: height - 1,
      'text-anchor': 'middle', text: 'RELEASE · RUNS COLLECTED' }));

    plot.appendChild(svg);
    var tip = tooltipFor(plot);
    var hit = s('rect', { class: 'hit', x: m.left, y: m.top, width: iw, height: ih });
    svg.appendChild(hit);

    function show(i) {
      var r = rels[i];
      if (!r) return;
      hi.setAttribute('x', m.left + i * band);
      hi.setAttribute('opacity', '1');
      tip.show(m.left + i * band + band / 2, m.top + ih / 2, [
        { color: 'var(--series-1)', name: 'distinct items', value: fmtInt(r.items) },
        { name: 'instances', value: fmtInt(r.instances) },
        { name: 'measurements', value: fmtInt(r.samples) },
        { name: 'runs / DUTs', value: r.runs + ' / ' + r.duts },
        !r.confident ? { name: 'coverage', value: 'thin — under ' +
          DATA.thresholds.minRunsConfident + ' runs' } : null
      ].filter(Boolean), 'Release ' + r.release);
    }
    function hide() { hi.setAttribute('opacity', '0'); tip.hide(); }

    hit.addEventListener('pointermove', function (e) {
      var box = svg.getBoundingClientRect();
      var lx = (e.clientX - box.left) * (width / box.width) - m.left;
      show(Math.max(0, Math.min(rels.length - 1, Math.floor(lx / band))));
    });
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('click', function (e) {
      var box = svg.getBoundingClientRect();
      var lx = (e.clientX - box.left) * (width / box.width) - m.left;
      var r = rels[Math.max(0, Math.min(rels.length - 1, Math.floor(lx / band)))];
      if (r) openRelease(r.station, r.release);
    });

    renderTable(document.getElementById('table-coverage'),
      [{ label: 'Release' }, { label: 'Items' }, { label: 'Instances' },
       { label: 'Measurements' }, { label: 'Runs' }, { label: 'DUTs' }],
      rels.map(function (r) {
        return [r.release, fmtInt(r.items), fmtInt(r.instances), fmtInt(r.samples),
          fmtInt(r.runs), fmtInt(r.duts)];
      }));
  }

  /* ------------------------------------------------------- release table --- */

  function renderReleaseTable() {
    var node = document.getElementById('table-releases');
    clear(node);
    var rels = releasesFor(state.station).slice().reverse();   // newest first
    var table = h('table');
    var head = h('tr');
    ['Release', 'Dates', 'Runs', 'DUTs', 'Items', 'Instances',
     'Added', 'Edited', 'Removed', 'Confidence'].forEach(function (c) {
      head.appendChild(h('th', { scope: 'col', text: c }));
    });
    table.appendChild(h('thead', null, head));

    var body = h('tbody');
    rels.forEach(function (r) {
      var d = diffTo(r.station, r.release);
      var tr = h('tr', {
        class: 'clickable', tabindex: '0', role: 'button',
        'aria-label': 'Open release ' + r.release,
        onclick: function () { openRelease(r.station, r.release); },
        onkeydown: function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openRelease(r.station, r.release); }
        }
      });
      tr.appendChild(h('th', { scope: 'row', text: r.release }));
      [fmtDay(r.first_ts) + ' – ' + fmtDay(r.last_ts), fmtInt(r.runs), fmtInt(r.duts),
       fmtInt(r.items), fmtInt(r.instances),
       d ? fmtInt(d.totals.added) : '—', d ? fmtInt(d.totals.changed) : '—',
       d ? fmtInt(d.totals.removed) : '—'].forEach(function (v) {
        tr.appendChild(h('td', { text: v }));
      });
      var td = h('td');
      td.appendChild(h('span', {
        class: 'conf ' + (r.confident ? 'ok' : 'low'),
        text: r.confident ? 'ok' : 'thin',
        title: r.confident ? '' : 'Under ' + DATA.thresholds.minRunsConfident +
          ' runs — add/remove claims cannot be supported'
      }));
      tr.appendChild(td);
      body.appendChild(tr);
    });
    table.appendChild(body);
    node.appendChild(table);
  }

  function renderTable(node, columns, rows) {
    clear(node);
    if (!rows.length) { node.appendChild(h('div', { class: 'empty', text: 'Nothing to show.' })); return; }
    var table = h('table');
    var head = h('tr');
    columns.forEach(function (c) { head.appendChild(h('th', { scope: 'col', text: c.label })); });
    table.appendChild(h('thead', null, head));
    var body = h('tbody');
    rows.forEach(function (cells) {
      var tr = h('tr');
      cells.forEach(function (v, i) {
        tr.appendChild(h(i === 0 ? 'th' : 'td', i === 0 ? { scope: 'row', text: v } : { text: v }));
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    node.appendChild(table);
  }

  /* ------------------------------------------------------------- drawer --- */

  var detailCache = {};
  var lastFocus = null;

  function openRelease(station, release) {
    lastFocus = document.activeElement;
    refs.backdrop.hidden = false;
    refs.drawer.hidden = false;
    refs.drawer.focus();

    var rel = releasesFor(station).filter(function (r) { return r.release === release; })[0];
    refs.drawerTitle.textContent = label(station) + ' — release ' + release;
    clear(refs.drawerSub);
    if (rel) {
      refs.drawerSub.appendChild(document.createTextNode(
        fmtDay(rel.first_ts) + ' – ' + fmtDay(rel.last_ts) + ' · ' +
        rel.runs + ' runs · ' + rel.duts + ' DUTs · ' +
        fmtInt(rel.items) + ' items · ' + fmtInt(rel.samples) + ' measurements'));
    }

    clear(refs.drawerBody);
    refs.drawerBody.appendChild(h('div', { class: 'loading', text: 'Loading item detail…' }));

    fetchDetail(station, release).then(function (detail) {
      renderDrawer(station, release, rel, detail);
    }).catch(function (err) {
      clear(refs.drawerBody);
      renderDrawer(station, release, rel, null, err);
    });
  }

  function fetchDetail(station, release) {
    var key = station + '|' + release;
    if (detailCache[key]) return Promise.resolve(detailCache[key]);
    var rel = releasesFor(station).filter(function (r) { return r.release === release; })[0];
    if (!rel || !rel.detail) return Promise.reject(new Error('no detail file recorded'));
    return fetch('data/releases/' + rel.detail).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (json) {
      detailCache[key] = json;
      return json;
    });
  }

  function closeDrawer() {
    refs.drawer.hidden = true;
    refs.backdrop.hidden = true;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function renderDrawer(station, release, rel, detail, err) {
    var body = refs.drawerBody;
    clear(body);

    var d = diffTo(station, release);

    // ---- summary chips
    if (d) {
      var chips = h('div', { class: 'chips' });
      [['added', d.totals.added], ['edited', d.totals.changed],
       ['removed', d.totals.removed], ['unchanged', d.totals.unchanged]].forEach(function (p) {
        chips.appendChild(h('div', { class: 'chip' }, [
          h('span', { class: 'n', text: fmtInt(p[1]) }),
          h('span', { class: 'k', text: p[0] })
        ]));
      });
      body.appendChild(h('h3', { text: 'Compatibility vs release ' + d.from }));
      body.appendChild(chips);
      if (d.confidence === 'low') {
        body.appendChild(h('div', { class: 'station-note' }, [
          h('b', { text: 'Low confidence. ' }),
          h('span', { text: d.confidenceReason || '' })
        ]));
      }
      body.appendChild(renderChangeGroups(d));
    } else {
      body.appendChild(h('h3', { text: 'Compatibility' }));
      body.appendChild(h('p', { class: 'h3sub',
        text: 'This is the earliest collected release for this station, so there is nothing to diff against.' }));
    }

    // ---- versions behind the release number
    if (rel && rel.versions && rel.versions.length) {
      body.appendChild(h('h3', { text: 'Build versions' }));
      body.appendChild(h('p', { class: 'h3sub',
        text: 'One release number can ship under several build hashes.' }));
      var ul = h('div', { class: 'kv' });
      rel.versions.forEach(function (v, i) {
        ul.appendChild(h('dt', { text: i === 0 ? 'versions' : '' }));
        ul.appendChild(h('dd', { text: v }));
      });
      body.appendChild(ul);
    }

    // ---- full item catalogue
    body.appendChild(h('h3', { text: 'All test items in this release' }));
    body.appendChild(h('p', { class: 'h3sub',
      text: 'Every base-level item measured. Expand a row for its statistics and '
          + 'its history across releases. Limits are not published by EOS, so no '
          + 'spec column exists — see the note in the page footer.' }));

    if (!detail) {
      body.appendChild(h('div', { class: 'fetchfail' }, [
        h('div', { text: 'Could not load the item detail file' +
          (err ? ' (' + err.message + ')' : '') + '.' }),
        h('div', { text: 'The per-release detail is fetched on demand, which needs '
          + 'the page to be served over HTTP. Opening the file directly from disk '
          + 'blocks it.' }),
        h('div', null, [document.createTextNode('Run '), h('code', { text: 'make serve' }),
          document.createTextNode(' and reopen, or use the published site.')])
      ]));
      return;
    }

    body.appendChild(renderItemCatalogue(station, detail, d));
  }

  function kindBadge(kind, weak) {
    var glyph = { removed: '−', added: '+', 'type-changed': '!', 'unit-changed': '!',
                  'coverage-changed': '±', 'step-moved': '→', 'distribution-shift': '~' };
    return h('span', { class: 'kind ' + kind + (weak ? ' weak' : ''),
                       title: (DATA.kindMeaning || {})[kind] || '' }, [
      h('span', { class: 'glyph', 'aria-hidden': 'true', text: glyph[kind] || '•' }),
      h('span', { text: kind + (weak ? ' (unconfirmed)' : '') })
    ]);
  }

  function renderChangeGroups(d) {
    var wrap = h('div');
    var names = DATA.items || [];

    // Bucket every entry by kind, in the severity order the backend defines.
    var buckets = {};
    function push(kind, entry, bucket) {
      (buckets[kind] || (buckets[kind] = [])).push({ e: entry, bucket: bucket });
    }
    d.added.forEach(function (e) { push('added', e, 'added'); });
    d.removed.forEach(function (e) { push('removed', e, 'removed'); });
    d.changed.forEach(function (e) {
      e.kinds.forEach(function (k) { push(k, e, 'changed'); });
    });

    (DATA.severity || Object.keys(buckets)).forEach(function (kind) {
      var rows = buckets[kind];
      if (!rows || !rows.length) return;
      var group = h('details', { class: 'kgroup' });
      var weakCount = rows.filter(function (r) { return r.e.weak; }).length;
      group.appendChild(h('summary', null, [
        kindBadge(kind, false),
        h('span', { text: rows.length + (rows.length === 1 ? ' item' : ' items') }),
        weakCount ? h('span', { class: 'why',
          text: '· ' + weakCount + ' unconfirmed' }) : null,
        h('span', { class: 'why', text: (DATA.kindMeaning || {})[kind] || '' })
      ]));
      var inner = h('div', { class: 'body' });
      rows.forEach(function (r) {
        inner.appendChild(itemChangeRow(names[r.e.i], r.e, kind));
      });
      group.appendChild(inner);
      wrap.appendChild(group);
    });

    if (!Object.keys(buckets).length) {
      wrap.appendChild(h('p', { class: 'h3sub',
        text: 'No item was added, removed or edited between these releases.' }));
    }
    return wrap;
  }

  function itemChangeRow(name, entry, kind) {
    var row = h('details', { class: 'irow' });
    var desc = entry.d || {};
    row.appendChild(h('summary', null, [
      h('span', { class: 'iname', text: name }),
      entry.weak ? h('span', { class: 'kind weak', text: 'unconfirmed' }) : null,
      h('span', { class: 'imeta', text: [desc.t, desc.u, desc.n ? desc.n + ' inst' : null]
        .filter(Boolean).join(' · ') })
    ]));

    var detail = h('div', { class: 'detail' });
    var notes = entry.notes || {};
    var kv = h('div', { class: 'kv' });

    function beforeAfter(labelText, pair, fmt) {
      kv.appendChild(h('dt', { text: labelText }));
      kv.appendChild(h('dd', null, h('span', { class: 'beforeafter' }, [
        h('span', { class: 'was', text: fmt(pair[0]) }),
        h('span', { class: 'arrow', 'aria-hidden': 'true', text: '→' }),
        h('span', { class: 'now', text: fmt(pair[1]) })
      ])));
    }

    if (notes.vtype) beforeAfter('value type', notes.vtype, function (v) { return v || '—'; });
    if (notes.unit) beforeAfter('unit', notes.unit, function (v) { return v || '(none)'; });
    if (notes.instances) beforeAfter('instances', notes.instances, fmtInt);
    if (notes.chips) beforeAfter('chips', notes.chips, function (v) {
      return (v && v.length) ? v.join(',') : '—';
    });
    if (notes.steps) beforeAfter('test step', notes.steps, function (v) {
      var steps = DATA.steps || [];
      return (v && v.length) ? v.map(function (i) {
        return typeof i === 'number' ? (steps[i] || i) : i;
      }).join(', ') : '—';
    });
    if (notes.shift) {
      var sh = notes.shift;
      beforeAfter('median', [sh.medianBefore, sh.medianAfter], fmtNum);
      kv.appendChild(h('dt', { text: 'move' }));
      kv.appendChild(h('dd', { text:
        (sh.sigma !== null && sh.sigma !== undefined ? sh.sigma.toFixed(2) + 'σ' : 'σ n/a') +
        (sh.ratio !== null && sh.ratio !== undefined ? '  ·  ×' + fmtNum(sh.ratio) : '') +
        '  ·  n=' + (sh.n || []).join(' → ') }));
    }
    if (kind === 'added' || kind === 'removed') {
      kv.appendChild(h('dt', { text: 'type / unit' }));
      kv.appendChild(h('dd', { text: [desc.t, desc.u || '(no unit)'].filter(Boolean).join(' · ') }));
      kv.appendChild(h('dt', { text: 'instances / samples' }));
      kv.appendChild(h('dd', { text: fmtInt(desc.n) + ' / ' + fmtInt(desc.s) }));
    }
    detail.appendChild(kv);

    var trend = trendChart(state.station, entry.i);
    if (trend) {
      detail.appendChild(h('div', { class: 'h3sub', text: 'median across releases' }));
      detail.appendChild(trend);
    }
    row.appendChild(detail);
    return row;
  }

  /* --------------------------------------------------- item catalogue --- */

  function renderItemCatalogue(station, detail, diff) {
    var names = DATA.items || [];
    var sig = detail.sig || {};
    var indices = Object.keys(sig);

    // Which items changed, so the catalogue can mark them without a second pass.
    var changedKinds = {};
    if (diff) {
      diff.changed.forEach(function (e) { changedKinds[e.i] = e.kinds; });
      diff.added.forEach(function (e) { changedKinds[e.i] = ['added']; });
    }

    var wrap = h('div');
    var search = h('input', { type: 'search', placeholder: 'Filter items…',
      'aria-label': 'Filter items' });
    var typeSel = h('select', { 'aria-label': 'Value type' }, [
      h('option', { value: '', text: 'All types' }),
      h('option', { value: 'num', text: 'Numeric only' }),
      h('option', { value: 'bool', text: 'Boolean' }),
      h('option', { value: 'str', text: 'Text' })
    ]);
    var onlyChanged = h('label', { style: 'font-size:12.5px;display:flex;gap:6px;align-items:center' }, [
      h('input', { type: 'checkbox' }), h('span', { text: 'changed only' })
    ]);
    var count = h('span', { class: 'count' });
    var list = h('div');

    wrap.appendChild(h('div', { class: 'filterrow' }, [search, typeSel, onlyChanged, count]));
    wrap.appendChild(list);

    function draw() {
      var q = search.value.trim().toLowerCase();
      var want = typeSel.value;
      var changedOnly = onlyChanged.querySelector('input').checked;
      clear(list);
      var shown = 0;
      indices.map(function (i) { return { i: i, sig: sig[i], name: names[i] || String(i) }; })
        .filter(function (row) {
          if (q && row.name.toLowerCase().indexOf(q) < 0) return false;
          if (want && row.sig.vtype !== want) return false;
          if (changedOnly && !changedKinds[row.i]) return false;
          return true;
        })
        .sort(function (a, b) { return a.name.localeCompare(b.name); })
        .forEach(function (row) {
          shown += 1;
          if (shown <= 400) list.appendChild(itemCatalogueRow(row, changedKinds[row.i]));
        });
      count.textContent = shown.toLocaleString() + ' of ' +
        indices.length.toLocaleString() + ' items' +
        (shown > 400 ? ' (showing first 400 — narrow the filter)' : '');
    }

    search.addEventListener('input', draw);
    typeSel.addEventListener('change', draw);
    onlyChanged.querySelector('input').addEventListener('change', draw);
    draw();
    return wrap;
  }

  function itemCatalogueRow(row, kinds) {
    var sig = row.sig;
    var stats = sig.stats;
    var node = h('details', { class: 'irow' });
    var meta = [sig.vtype, sig.unit, sig.instances + ' inst', sig.samples + ' samples'];
    if (stats) meta.push('median ' + fmtNum(stats.median));

    node.appendChild(h('summary', null, [
      h('span', { class: 'iname', text: row.name }),
      (kinds || []).length ? kindBadge(kinds[0], false) : null,
      h('span', { class: 'imeta', text: meta.filter(Boolean).join(' · ') })
    ]));

    var detail = h('div', { class: 'detail' });
    var kv = h('div', { class: 'kv' });
    function kvp(k, v) {
      kv.appendChild(h('dt', { text: k }));
      kv.appendChild(h('dd', { text: v }));
    }
    kvp('value type', sig.vtype + (sig.mixedType ? '  (mixed across samples)' : ''));
    kvp('unit', sig.unit || '(none)');
    kvp('instances', fmtInt(sig.instances) + ' distinct measurement names');
    kvp('samples', fmtInt(sig.samples));
    kvp('DUTs', fmtInt(sig.duts));
    kvp('prevalence', fmtPct(sig.prevalence) + ' of this release’s runs (' +
      fmtInt(sig.runsPresent) + ' runs)');
    if (sig.chips && sig.chips.length) kvp('chips', sig.chips.join(', '));
    if (sig.steps && sig.steps.length) {
      kvp('test step', sig.steps.map(function (i) {
        return (DATA.steps || [])[i] || i;
      }).join(', '));
    }
    if (stats) {
      kvp('min / max', fmtNum(stats.min) + '  …  ' + fmtNum(stats.max));
      kvp('p25 / median / p75', fmtNum(stats.p25) + ' · ' + fmtNum(stats.median) +
        ' · ' + fmtNum(stats.p75));
      kvp('p99', fmtNum(stats.p99));
      kvp('std dev', fmtNum(stats.sd));
    }
    detail.appendChild(kv);

    var trend = trendChart(state.station, row.i);
    if (trend) {
      detail.appendChild(h('div', { class: 'h3sub', text: 'median across releases (p25–p75 band)' }));
      detail.appendChild(trend);
    }
    node.appendChild(detail);
    return node;
  }

  /* ------------------------------------------------- per-item trend graph */

  /**
   * Median across releases with a p25–p75 band. This is the graph that answers
   * "did this item's behaviour drift between releases", which a single release's
   * numbers cannot show.
   *
   * Values span BER (1e-11) to Hz (1e9), so the y-scale is log when the data is
   * strictly positive and spans more than two decades — on a linear axis a BER
   * series is a flat line on zero.
   */
  function trendChart(station, itemIndex) {
    var series = ((DATA.trends || {})[station] || {})[String(itemIndex)];
    if (!series || series.length < 2) return null;

    var width = 560, height = 132;
    var m = { top: 12, right: 44, bottom: 26, left: 58 };
    var iw = width - m.left - m.right, ih = height - m.top - m.bottom;

    var lows = series.map(function (p) { return p[3]; });
    var highs = series.map(function (p) { return p[4]; });
    var all = lows.concat(highs).concat(series.map(function (p) { return p[2]; }))
      .filter(function (v) { return v !== null && v !== undefined && !isNaN(v); });
    if (!all.length) return null;

    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var positive = lo > 0;
    var useLog = positive && (hi / lo) > 100;

    var tf = useLog ? function (v) { return Math.log10(v); } : function (v) { return v; };
    var tLo = useLog ? tf(lo) : Math.min(0, lo);
    var tHi = useLog ? tf(hi) : hi;
    if (tHi === tLo) { tHi = tLo + 1; }

    var step = series.length > 1 ? iw / (series.length - 1) : 0;
    var xAt = function (i) { return m.left + i * step; };
    var yAt = function (v) {
      if (v === null || v === undefined || isNaN(v)) return null;
      if (useLog && v <= 0) return null;
      return m.top + ih - ((tf(v) - tLo) / (tHi - tLo)) * ih;
    };

    var svg = s('svg', { viewBox: '0 0 ' + width + ' ' + height, height: height,
      style: 'width:100%;max-width:' + width + 'px',
      role: 'img', 'aria-label': 'Median of this item across releases' });

    [0, 0.5, 1].forEach(function (f) {
      var y = m.top + ih - f * ih;
      svg.appendChild(s('line', { class: f === 0 ? 'axisline' : 'gridline',
        x1: m.left, x2: width - m.right, y1: y, y2: y }));
      var v = useLog ? Math.pow(10, tLo + f * (tHi - tLo)) : tLo + f * (tHi - tLo);
      svg.appendChild(s('text', { class: 'tick', x: m.left - 6, y: y + 3.5,
        'text-anchor': 'end', text: fmtNum(v) }));
    });

    // p25–p75 band as a wash under the median line.
    var top = [], bottom = [];
    series.forEach(function (p, i) {
      var y1 = yAt(p[3]), y2 = yAt(p[4]);
      if (y1 === null || y2 === null) return;
      top.push(xAt(i) + ',' + y2);
      bottom.unshift(xAt(i) + ',' + y1);
    });
    if (top.length > 1) {
      svg.appendChild(s('path', { d: 'M' + top.join('L') + 'L' + bottom.join('L') + 'Z',
        fill: 'var(--series-1)', opacity: 0.12 }));
    }

    var pts = [];
    series.forEach(function (p, i) {
      var y = yAt(p[2]);
      if (y === null) return;
      pts.push([xAt(i), y, p]);
    });
    if (pts.length > 1) {
      svg.appendChild(s('path', {
        d: 'M' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join('L'),
        fill: 'none', stroke: 'var(--series-1)', 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    }
    pts.forEach(function (p) {
      var g = s('g', {});
      g.appendChild(s('circle', { cx: p[0], cy: p[1], r: 4, fill: 'var(--series-1)',
        stroke: 'var(--surface-1)', 'stroke-width': 2 }));
      g.appendChild(s('title', { text: 'release ' + p[2][0] + ' · median ' +
        fmtNum(p[2][2]) + ' · n=' + p[2][1] }));
      svg.appendChild(g);
    });

    series.forEach(function (p, i) {
      if (series.length > 8 && i % 2) return;
      svg.appendChild(s('text', { class: 'tick', x: xAt(i), y: height - 8,
        'text-anchor': 'middle', text: p[0] }));
    });

    if (useLog) {
      svg.appendChild(s('text', { class: 'x-sub', x: width - m.right + 4,
        y: m.top + 8, text: 'log' }));
    }
    return svg;
  }

  /* ------------------------------------------------------------- wiring --- */

  function renderStationBar() {
    clear(refs.bar);
    stationsWithData().forEach(function (station) {
      var n = releasesFor(station).length;
      refs.bar.appendChild(h('button', {
        type: 'button',
        'aria-pressed': station === state.station ? 'true' : 'false',
        onclick: function () { state.station = station; render(); }
      }, [
        h('span', { text: label(station) }),
        h('span', { class: 'n', text: n + (n === 1 ? ' release' : ' releases') })
      ]));
    });
  }

  function render() {
    renderStationBar();
    renderChurn();
    renderCoverage();
    renderReleaseTable();
  }

  function wire() {
    document.addEventListener('click', function (e) {
      var t = e.target.closest('.view-toggle');
      if (!t) return;
      var card = t.getAttribute('data-toggle');
      var table = document.getElementById('table-' + card);
      var plot = document.getElementById('plot-' + card);
      var show = t.getAttribute('aria-pressed') !== 'true';
      t.setAttribute('aria-pressed', show ? 'true' : 'false');
      t.textContent = show ? 'Chart' : 'Table';
      table.hidden = !show;
      if (plot) plot.hidden = show;
    });

    refs.drawerClose.addEventListener('click', closeDrawer);
    refs.backdrop.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !refs.drawer.hidden) closeDrawer();
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
      timer = setTimeout(function () { renderChurn(); renderCoverage(); }, 140);
    });
  }

  function boot() {
    if (!DATA || !DATA.releases || !DATA.releases.length) {
      document.getElementById('content').appendChild(h('div', { class: 'card empty' },
        'No release data. Run `make items` to build the test-item store, then `make build`.'));
      return;
    }
    // Default to the station with the most items — the alphabetically first
    // station is not necessarily the one worth looking at.
    state.station = stationsWithData().slice().sort(function (a, b) {
      var mx = function (st) {
        return Math.max.apply(null, releasesFor(st).map(function (r) { return r.items; }));
      };
      return mx(b) - mx(a);
    })[0];
    refs.meta.textContent = DATA.releases.length + ' release/station pairs · ' +
      (DATA.items || []).length.toLocaleString() + ' distinct items';
    refs.footer.textContent = 'Built ' + (DATA.generatedAt || 'unknown') +
      '. Shift threshold: ' + DATA.thresholds.shiftSigma + 'σ or ×' +
      DATA.thresholds.shiftRatio + ', minimum ' + DATA.thresholds.minSamplesForShift +
      ' samples each side. A release under ' + DATA.thresholds.minRunsConfident +
      ' runs cannot support add/remove claims.';
    wire();
    render();
  }

  boot();
})();
