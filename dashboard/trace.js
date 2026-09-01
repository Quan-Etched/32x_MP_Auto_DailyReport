/* Where a serial sits, and everything that ever happened to it.
 *
 * WHY THIS SITS BESIDE dutsearch.js RATHER THAN INSIDE IT
 * dutsearch answers "what runs did the controllers record for this serial" —
 * a flat list, one system, no structure. The question underneath it is
 * "and what *is* this serial": what is it plugged into, what is plugged into
 * it, and what happened to each of those. That needs the SFIS genealogy, which
 * is a different bundle with a different shape and a different freshness.
 *
 * Keeping it separate means dutsearch keeps working untouched when trace.js has
 * no data, which is the common case on a published copy built before anyone ran
 * a mirror. One container, one script tag, no edits to 381 lines that already work.
 *
 * THE JOIN THIS PAGE DOES THAT THE BUNDLE CANNOT
 * The trace bundle deliberately ships no controller runs — customize.html has
 * already loaded every one of them for its other two views. So the records for a
 * node are the union of:
 *
 *   from the bundle   SFIS route/process events, EOS runs   (server-side)
 *   from this page    controller runs matching the serial   (client-side)
 *
 * and only the controller ones can carry a per-run deep link, because the
 * controller mints the id. EOS has no UI; OCP Logs has no per-run route. Those
 * records get the by-serial search links instead, which is what a person would
 * have to do by hand anyway.
 */
(function () {
  'use strict';

  /* The bundle is fetched, not script-tagged. At production scale it is 1.3 MB
   * for 31 units and 3,426 nodes, and most visits to this page are somebody
   * pulling a CSV who never opens the tree at all -- so it costs nothing until
   * a serial is actually being looked at. (It was a blocking tag briefly, and
   * before inheritance moved client-side it was 17.2 MB of one: the page went
   * from four minutes of blocked parsing to worse. Both are fixed, and this is
   * the half that keeps it fixed.) */
  var T = window.__FACTORY_TRACE__ || null;
  var BUNDLE_URL = 'data/trace.js';
  var loadState = T ? 'ready' : 'idle';   // idle | loading | ready | failed
  var loadError = '';

  var host = document.getElementById('trace');
  if (!host) return;

  /* Read lazily, never cached at load: this module runs BEFORE the 9.5 MB run
   * bundle so the tree paints in seconds instead of minutes, and the controller
   * rows appear on the re-render once that bundle has finished arriving. */
  function runRows() { return (window.__FACTORY_RUNS__ || {}).runs || []; }
  function runLabels() { return (window.__FACTORY_RUNS__ || {}).stationLabels || {}; }
  function runsReady() { return !!(window.__FACTORY_RUNS__ || {}).runs; }

  var DEFAULT_FIELDS = ['ts', 'station', 'result', 'source', 'kind', 'run',
                        'release', 'sk'];
  /* Read through T rather than captured at load: T does not exist yet. */
  function fields() { return (T && T.recordFields) || DEFAULT_FIELDS; }

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else if (key === 'class') node.className = attrs[key];
      else if (key === 'html') node.innerHTML = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  function link(text, href, title) {
    return h('a', { text: text, href: href, target: '_blank',
                    rel: 'noopener', title: title || href });
  }

  /* Templates are expanded here rather than shipped per node: 2,000 nodes
   * carrying five near-identical URLs each is megabytes of the same text. */
  function serialLinks(sn) {
    var tpl = (T && T.linkTemplates) || {};
    var out = {};
    Object.keys(tpl).forEach(function (key) {
      if (key === 'suite_run') return;
      out[key] = tpl[key].replace('{sn}', encodeURIComponent(sn));
    });
    return out;
  }

  /* The one per-run URL that exists. `#slot` is this repo's own encoding for
   * "unit N of a fixture run" (see shopfloor/links.py); the controller wants it
   * back as a query parameter. */
  function suiteRunUrl(runId, stationKey) {
    if (!runId || !T) return '';
    var hosts = T.controllers || {};
    var esvm = hosts[stationKey];
    if (!esvm) return '';
    var slot = null, id = runId;
    var cut = runId.indexOf('#slot');
    if (cut >= 0) { id = runId.slice(0, cut); slot = runId.slice(cut + 5); }
    var url = (T.linkTemplates.suite_run || 'http://{host}:3000/suite_run/{run}')
      .replace('{host}', esvm).replace('{run}', encodeURIComponent(id));
    if (slot) url += '?slot_number=' + encodeURIComponent(slot);
    return url;
  }

  function node(sn) { return (T && T.nodes && T.nodes[sn]) || null; }

  /* Up from a serial to the unit it belongs to. Guarded against a cycle: the
   * genealogy is a tree by construction but this reads a generated file, and a
   * page that hangs is worse than one that shows a short path. */
  function chain(sn) {
    var path = [], seen = {}, cur = sn;
    while (cur && !seen[cur]) {
      seen[cur] = 1;
      path.unshift(cur);
      var n = node(cur);
      cur = n && n.p;
    }
    return path;
  }

  function controllerRecords(sn) {
    var out = [];
    var rows = runRows(), labels = runLabels();
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (String(r.d) !== String(sn)) continue;
      out.push({
        ts: r.t ? new Date(r.t * 1000).toISOString().replace('.000Z', 'Z') : '',
        station: labels[r.k] || r.k || '?',
        result: r.s || 'unknown',
        source: 'controller',
        kind: 'test',
        run: r.i || '',
        release: r.v || r.su || '',
        sk: r.k || ''
      });
    }
    return out;
  }

  function bundleRecords(rows) {
    var names = fields();
    return (rows || []).map(function (row) {
      var rec = {};
      names.forEach(function (name, i) { rec[name] = row[i]; });
      return rec;
    });
  }

  /* Inheritance, re-derived rather than shipped. Same rule as
   * shopfloor.graph.build: only an ancestor's *tests* carry down (an assembly
   * scan on the parent says nothing about the child), and only those that ran
   * after this part was linked into it -- otherwise a swapped-in part collects
   * the history of the one it replaced.
   *
   * Better than the server's version in one way: an ancestor's controller runs
   * are joined here too, and those are never in the bundle. */
  function inheritedRecords(sn) {
    var start = node(sn);
    if (!start) return [];
    var since = start.l || '';
    var out = [], seen = {}, cur = start.p;
    while (cur && !seen[cur]) {
      seen[cur] = 1;
      var ancestor = node(cur);
      if (!ancestor) break;
      var rows = bundleRecords(ancestor.r).concat(controllerRecords(cur));
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        if (r.kind !== 'test') continue;
        if (since && (r.ts || '') < since) continue;
        out.push({ ts: r.ts, station: r.station, result: r.result,
                   source: r.source, kind: r.kind, run: r.run, release: r.release,
                   sk: r.sk, on: cur, via: 'installed_in' });
      }
      cur = ancestor.p;
    }
    out.sort(function (a, b) { return (a.ts || '').localeCompare(b.ts || ''); });
    return out;
  }

  function allRecords(sn) {
    var n = node(sn);
    var rows = bundleRecords(n && n.r).concat(controllerRecords(sn));
    rows.sort(function (a, b) { return (a.ts || '').localeCompare(b.ts || ''); });
    return rows;
  }

  function when(ts) { return (ts || '').replace('T', ' ').replace('Z', '').slice(0, 16); }

  function statusClass(result) {
    if (result === 'pass') return 'status pass';
    if (result === 'fail' || result === 'error') return 'status fail';
    return 'status';
  }

  var COVERAGE_NOTE = {
    tested: 'a test names this serial directly',
    process_only: 'route and assembly events only — installed, not tested',
    inherited_only: 'nothing tests it by serial; its parent was tested while it was fitted',
    none_expected: 'a vendor part no station tests by serial — not a gap',
    not_observed: 'the snapshot never fetched this part; its records are unknown, not empty',
    unit: 'the top-level unit'
  };

  function recordTable(rows, sn) {
    if (!rows.length) return h('p', { class: 'trace-empty', text: 'No records.' });
    var body = h('tbody', {});
    rows.forEach(function (r) {
      var raw = r.source === 'controller' ? suiteRunUrl(r.run, r.sk) : '';
      body.appendChild(h('tr', {}, [
        h('td', { text: when(r.ts) }),
        h('td', { text: r.station }),
        h('td', { class: statusClass(r.result), text: r.result }),
        h('td', {}, [h('span', { class: 'src-tag', text: r.source })]),
        h('td', { text: r.kind || '' }),
        h('td', { text: r.release || '' }),
        h('td', {}, [raw ? link('raw ↗', raw, 'The controller’s own page for this run')
                         : h('span', { class: 'trace-dim', text: '—' })])
      ]));
    });
    return h('div', { class: 'table-wrap' }, [
      h('table', { class: 'cz-table' }, [
        h('thead', {}, [h('tr', {}, ['when (UTC)', 'station', 'result', 'source', 'kind', 'release', 'raw data']
          .map(function (t) { return h('th', { text: t }); }))]),
        body
      ])
    ]);
  }

  function partsTable(sn, onPick) {
    var n = node(sn);
    var kids = (n && n.k) || [];
    if (!kids.length) return null;
    var body = h('tbody', {});
    kids.forEach(function (kid) {
      var k = node(kid) || {};
      var count = ((k.r || []).length) + controllerRecords(kid).length;
      var name = h('a', { href: '#', text: kid, class: 'trace-pick' });
      name.addEventListener('click', function (e) { e.preventDefault(); onPick(kid); });
      body.appendChild(h('tr', {}, [
        h('td', { text: k.s || '' }),
        h('td', {}, [name]),
        h('td', { text: k.t || '' }),
        h('td', { text: k.n || '' }),
        h('td', {}, [
          h('span', { class: 'trace-cov trace-cov-' + (k.c || 'unknown'), text: k.c || '?' }),
          k.g ? h('span', { class: 'trace-gap', text: 'gap',
                            title: 'Pega serialized this part but has no route history for it' }) : null
        ]),
        h('td', { text: count ? String(count) : '—' })
      ]));
    });
    return h('div', { class: 'table-wrap' }, [
      h('table', { class: 'cz-table' }, [
        h('thead', {}, [h('tr', {}, ['slot', 'serial', 'type', 'name', 'coverage', 'records']
          .map(function (t) { return h('th', { text: t }); }))]),
        body
      ])
    ]);
  }

  /* A plain link to the file the builder wrote, not a Blob of text carried in
   * the bundle. The text is identical -- both come from render.to_text -- but
   * this way it costs nothing until somebody clicks. */
  function download(unit) {
    var units = T.yamlUnits || [];
    if (!T.yamlPath || units.indexOf(unit) < 0) return null;
    return h('a', { class: 'view-toggle', download: unit + '.yaml',
                    href: T.yamlPath.replace('{sn}', encodeURIComponent(unit)),
                    text: 'Download ' + unit + '.yaml' });
  }

  function render(sn) {
    host.innerHTML = '';
    if (!sn) return;

    var n = node(sn);
    var card = h('section', { class: 'card full trace-card' });
    var head = h('div', { class: 'card-head' }, [
      h('div', {}, [
        h('h2', { text: 'Traceability' }),
        h('p', { class: 'sub', text: n
          ? 'Where ' + sn + ' sits, and every record for it.'
          : sn + ' is not in the traceability snapshot.' })
      ]),
      h('span', { class: 'spacer' })
    ]);
    card.appendChild(head);

    if (!n) {
      /* Not mirrored is not the same as does not exist. The by-serial links are
       * template-derived, so they resolve regardless — and jumping straight to
       * the SFIS UI is exactly what somebody would do next. */
      card.appendChild(h('p', { class: 'trace-empty', text:
        'No genealogy for this serial in snapshot ' + ((T.snapshot || {}).id || '?') +
        '. It may not have been mirrored yet — run `make sfis-mirror SN=' + sn +
        '`. The searches below work either way:' }));
      var ls = serialLinks(sn);
      card.appendChild(h('p', { class: 'trace-links' }, [
        link('SFIS ↗', ls.sfis), link('Sheet ↗', ls.sfis_sheet),
        link('Controller history ↗', ls.controller_history), link('SPLM ↗', ls.splm)
      ]));
      host.appendChild(card);
      return;
    }

    var unit = n.u || sn;
    var dl = download(unit);
    if (dl) head.appendChild(h('div', { class: 'quick' }, [dl]));

    /* The path is the answer to "what is this plugged into", and it is the part
     * people screenshot. Every hop is clickable so walking up is one click, not
     * a new search. */
    var path = chain(sn);
    var breadcrumb = h('p', { class: 'trace-path' });
    path.forEach(function (step, i) {
      var s = node(step) || {};
      if (i) breadcrumb.appendChild(h('span', { class: 'trace-sep', text: ' › ' }));
      if (s.s) breadcrumb.appendChild(h('span', { class: 'trace-slot', text: s.s + ' ' }));
      if (step === sn) {
        breadcrumb.appendChild(h('strong', { text: step }));
      } else {
        var a = h('a', { href: '#', text: step, class: 'trace-pick' });
        a.addEventListener('click', function (e) { e.preventDefault(); show(step); });
        breadcrumb.appendChild(a);
      }
    });
    card.appendChild(breadcrumb);

    var facts = [];
    if (n.t) facts.push(n.t);
    if (n.n) facts.push(n.n);
    if (n.m) facts.push('MPN ' + n.m);
    if (n.e) facts.push('EPN ' + n.e);
    if (n.l) facts.push('linked ' + when(n.l));
    if (n.a && n.a.length) facts.push('MAC ' + n.a.join(', '));
    card.appendChild(h('p', { class: 'trace-facts', text: facts.join(' · ') }));

    card.appendChild(h('p', { class: 'trace-coverage' }, [
      h('span', { class: 'trace-cov trace-cov-' + (n.c || 'unknown'), text: n.c || '?' }),
      h('span', { class: 'trace-dim', text: ' ' + (COVERAGE_NOTE[n.c] || '') }),
      n.g ? h('span', { class: 'trace-gap', text: 'traceability gap' }) : null
    ]));

    if (n.also && n.also.length > 1) {
      card.appendChild(h('p', { class: 'trace-note', text:
        'This serial appears under more than one unit: ' + n.also.join(', ') +
        '. Shown under ' + unit + '.' }));
    }

    var ls = serialLinks(sn);
    card.appendChild(h('p', { class: 'trace-links' }, [
      link('SFIS ↗', ls.sfis, 'The shopfloor genealogy UI'),
      link('Sheet ↗', ls.sfis_sheet),
      link('XLSX ↗', ls.sfis_xlsx),
      link('Controller history ↗', ls.controller_history, 'Every suite run the controller saw for this serial'),
      link('SPLM ↗', ls.splm)
    ]));

    var records = allRecords(sn);
    card.appendChild(h('h3', { class: 'trace-h3',
      text: 'Test records (' + records.length + ')' }));
    if (!runsReady()) {
      /* Said plainly rather than left to look like "there are none". The run
       * bundle is 9.5 MB and on the VPN it takes minutes; this card does not
       * wait for it, so for those minutes the controller rows really are absent. */
      card.appendChild(h('p', { class: 'trace-warn', text:
        'Still loading the controller run bundle — controller records and their ' +
        'raw-data links will appear when it arrives.' }));
    }
    card.appendChild(recordTable(records, sn));

    var inherited = inheritedRecords(sn);
    if (inherited.length) {
      var det = h('details', { class: 'trace-details' }, [
        h('summary', { text: 'Inherited from what it was installed in (' + inherited.length + ')' }),
        h('p', { class: 'trace-dim', text:
          'No test names this part. These ran on a parent while this part was ' +
          'fitted to it — an ancestor\u2019s tests, from when this part was ' +
          'linked in onwards.' }),
        recordTable(inherited, sn)
      ]);
      card.appendChild(det);
    }

    var kids = partsTable(sn, show);
    if (kids) {
      card.appendChild(h('h3', { class: 'trace-h3',
        text: 'Parts under it (' + (n.k || []).length + ')' }));
      card.appendChild(kids);
    }

    var snap = T.snapshot || {};
    card.appendChild(h('p', { class: 'trace-foot', text:
      'Snapshot ' + (snap.id || '?') + ' taken ' + when(snap.takenAt) +
      ' · SFIS payloads through ' + when(snap.sfisPayloadsThrough) +
      ' · controller runs from the page bundle' }));
    (T.warnings || []).forEach(function (w) {
      card.appendChild(h('p', { class: 'trace-warn', text: '! ' + w }));
    });

    host.appendChild(card);
  }

  /* The serial lives in the address bar so a view is a link somebody can paste,
   * the same contract runs.html makes. */
  function show(sn) {
    var hash = window.location.hash.replace(/^#/, '');
    var parts = hash.split('&').filter(function (p) { return p && p.indexOf('trace=') !== 0; });
    parts.push('trace=' + encodeURIComponent(sn));
    window.location.hash = parts.join('&');
  }

  /* Which serial to show, in order of how deliberate it is.
   *
   * The serial box was the missing one, and it is the one people actually use:
   * dutsearch.js READS `dut=` out of the hash but never writes it, so typing a
   * serial and pressing SEARCH leaves the address bar at `#mode=dut` with the
   * serial only in the textarea. Reading the hash alone meant the card silently
   * never appeared for the normal way of using the page. */
  function current() {
    var hash = window.location.hash.replace(/^#/, '');
    var fromHash = '', fromDut = '';
    hash.split('&').forEach(function (part) {
      var bits = part.split('=');
      if (bits[0] === 'trace') fromHash = decodeURIComponent(bits[1] || '');
      if (bits[0] === 'dut') {
        fromDut = decodeURIComponent(bits[1] || '').split(/[\s,]+/)[0] || '';
      }
    });
    if (fromHash) return fromHash;
    if (fromDut) return fromDut;

    var box = document.getElementById('dut-input');
    if (box && box.value) {
      var first = box.value.split(/[\s,\t\n]+/).filter(function (s) { return s; })[0];
      if (first) return first;
    }
    return '';
  }

  /* Fetch the bundle the first time a serial is actually being shown. */
  function ensureBundle(then) {
    if (loadState === 'ready') { then(); return; }
    if (loadState === 'loading') return;
    loadState = 'loading';
    paintLoading();
    fetch(BUNDLE_URL, { cache: 'force-cache' }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.text();
    }).then(function (text) {
      var open = text.indexOf('{');
      T = JSON.parse(text.slice(open).replace(/;\s*$/, ''));
      window.__FACTORY_TRACE__ = T;
      loadState = 'ready';
      then();
    }).catch(function (err) {
      /* A 404 is the ordinary case on a copy published before anyone ran
       * `make sfis-dashboard`, and it is not an error worth shouting about --
       * the rest of the page is unaffected. Anything else is worth saying. */
      loadState = 'failed';
      loadError = String((err && err.message) || err);
      host.innerHTML = '';
      if (loadError.indexOf('404') < 0) {
        host.appendChild(h('p', { class: 'trace-empty', text:
          'Traceability data could not be loaded: ' + loadError }));
      }
    });
  }

  function paintLoading() {
    host.innerHTML = '';
    host.appendChild(h('section', { class: 'card full trace-card' }, [
      h('div', { class: 'card-head' }, [
        h('div', {}, [
          h('h2', { text: 'Traceability' }),
          h('p', { class: 'sub', text: 'Loading the genealogy…' })
        ])
      ]),
      h('div', { class: 'bd-bar bd-bar-idle' }, [h('div', { class: 'bd-fill' })])
    ]));
  }

  function tick() {
    var sn = current();
    if (!sn) { if (loadState !== 'loading') host.innerHTML = ''; return; }
    if (loadState === 'failed') return;
    ensureBundle(function () { render(sn); });
  }

  window.addEventListener('hashchange', tick);

  /* The serial box is not in the address bar, so nothing else tells us it
   * changed. `change` fires on blur, and the SEARCH button lives in #dut-run —
   * both are the moment somebody has committed to a serial, which is when it is
   * worth fetching a 1.3 MB bundle. Not on `input`: that would fetch it while
   * they are still typing the first digit. */
  function watchSerialBox() {
    var box = document.getElementById('dut-input');
    if (box && !box.__traceWatched) {
      box.__traceWatched = true;
      box.addEventListener('change', tick);
    }
    var runHost = document.getElementById('dut-run');
    if (runHost && !runHost.__traceWatched) {
      runHost.__traceWatched = true;
      /* Delegated, because dutsearch re-creates the button on every render. */
      runHost.addEventListener('click', function () {
        window.setTimeout(tick, 0);
      });
    }
  }
  /* Twice on purpose: now, from the trace bundle alone, so the tree is on screen
   * in seconds; and again at DOMContentLoaded, which is after every blocking
   * script -- including the run bundle -- has executed, to fold in the
   * controller rows. */
  function start() { watchSerialBox(); tick(); }
  start();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  }
})();
