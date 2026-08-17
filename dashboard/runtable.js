/* Raw run table — the drill-down behind every number on the station page.
 *
 * THE URL IS THE STATE
 * --------------------
 * Filters live in the hash (`runs.html#station=mlt&release=220&status=fail`) and
 * nowhere else, so any view of this table can be pasted into Slack and will open
 * the same rows for the next reader. Hash rather than query string because these
 * pages have to work over file:// as well as from GitHub Pages.
 *
 * FILTER SEMANTICS ARE THE STATION PAGE'S
 * ---------------------------------------
 * `status=abort` means status === 'error' (the line says abort, EOS says error)
 * and `status=graded` means the pass/fail/error triple — the same definitions
 * daily.py uses, because a drill-down that disagrees with the tile it came from
 * would be worse than no drill-down. See src/factory/build_runs.py.
 *
 * All label text (run IDs, DUT serials, suite and test names) comes from the API
 * and only ever reaches the DOM via textContent.
 *
 * Style note: plain ES5, no build step, no dependencies — same as the rest of
 * the dashboard.
 */
'use strict';

(function () {

  var DATA = window.__FACTORY_RUNS__ || { runs: [], testNames: [], testStatuses: [] };
  var RUNS = DATA.runs || [];
  var NAMES = DATA.testNames || [];
  var TSTATUS = DATA.testStatuses || ['pass', 'fail', 'error', 'skip', 'unknown'];
  var LINKS = DATA.links || {};

  /* Rows rendered before the "show all" prompt. The full set is always what
   * gets counted and copied — only the DOM is capped. */
  var PAGE = 400;

  /* --------------------------------------------------------------- helpers */

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
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

  function fmtInt(v) {
    return v === null || v === undefined ? '—' : Math.round(v).toLocaleString();
  }

  function fmtDur(secs) {
    if (secs === null || secs === undefined) return '—';
    if (secs < 60) return Math.round(secs) + 's';
    var mins = Math.round(secs / 60);
    if (mins < 60) return mins + 'm';
    return Math.floor(mins / 60) + 'h' + ('0' + (mins % 60)).slice(-2);
  }

  /* Times are shown in the factory's zone, not the reader's: "the 8/11 night
   * shift" has to mean the same thing on a laptop in another timezone. */
  var timeFmt = null;
  try {
    timeFmt = new Intl.DateTimeFormat(undefined, {
      timeZone: DATA.timezone, month: 'numeric', day: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false
    });
  } catch (e) { timeFmt = null; }

  function fmtStart(ts) {
    if (!ts) return '—';
    var date = new Date(ts * 1000);
    if (timeFmt) return timeFmt.format(date);
    return date.toISOString().slice(5, 16).replace('T', ' ');
  }

  function ago(iso) {
    if (!iso) return null;
    var mins = (Date.now() - Date.parse(iso)) / 60000;
    if (isNaN(mins)) return null;
    if (mins < 60) return Math.round(mins) + 'm ago';
    if (mins < 48 * 60) return Math.round(mins / 60) + 'h ago';
    return Math.round(mins / 1440) + 'd ago';
  }

  /* ----------------------------------------------------------------- state */

  /* Every recognised hash key, with the label its chip shows. Anything else in
   * the hash is ignored rather than silently treated as "no filter". */
  var FILTERS = [
    { key: 'station', label: 'station' },
    { key: 'day', label: 'day' },
    { key: 'release', label: 'release' },
    { key: 'status', label: 'status' },
    { key: 'attempt', label: 'attempt' },
    { key: 'dut', label: 'DUT' },
    { key: 'suite', label: 'suite' },
    { key: 'level', label: 'level' }
  ];

  var state = { filters: {}, sort: 't', dir: -1, expanded: {}, showAll: false };

  function readHash() {
    var raw = String(location.hash || '').replace(/^#/, '');
    var out = {};
    raw.split('&').forEach(function (pair) {
      if (!pair) return;
      var eq = pair.indexOf('=');
      if (eq < 0) return;
      var key = decodeURIComponent(pair.slice(0, eq));
      var value = decodeURIComponent(pair.slice(eq + 1).replace(/\+/g, ' '));
      if (!value) return;
      if (key === 'sort') { state.sort = value; return; }
      if (key === 'dir') { state.dir = value === 'asc' ? 1 : -1; return; }
      if (isFilter(key)) out[key] = value;
    });
    state.filters = out;
  }

  function isFilter(key) {
    for (var i = 0; i < FILTERS.length; i += 1) if (FILTERS[i].key === key) return true;
    return false;
  }

  function writeHash() {
    var parts = [];
    FILTERS.forEach(function (f) {
      var value = state.filters[f.key];
      if (value) parts.push(f.key + '=' + encodeURIComponent(value));
    });
    if (state.sort !== 't' || state.dir !== -1) {
      parts.push('sort=' + state.sort, 'dir=' + (state.dir === 1 ? 'asc' : 'desc'));
    }
    var next = '#' + parts.join('&');
    if (next !== location.hash) {
      // replaceState, not assignment: sorting a column should not stack up
      // history entries the reader has to press Back through.
      if (window.history && history.replaceState) history.replaceState(null, '', next);
      else location.hash = next;
    }
  }

  /* ---------------------------------------------------------------- filter */

  var GRADED = { pass: 1, fail: 1, error: 1 };

  function statusMatches(run, want) {
    if (want === 'abort') return run.s === 'error';       // line vocabulary
    if (want === 'graded') return !!GRADED[run.s];
    return run.s === want;
  }

  function matches(run) {
    var f = state.filters;
    if (f.station && f.station !== '__all__' && run.k !== f.station) return false;
    // "All stations" excludes the unclassified tail, exactly as the station
    // page's __all__ view does — otherwise this table would out-count the tile.
    if (f.station === '__all__' && run.k === 'unclassified') return false;
    if (f.day && run.day !== f.day) return false;
    if (f.release && String(run.r) !== String(f.release)) return false;
    if (f.status && !statusMatches(run, f.status)) return false;
    if (f.attempt === 'first' && run.a !== 1) return false;
    if (f.attempt === 'retest' && !(run.a > 1)) return false;
    if (f.dut && run.d !== f.dut) return false;
    if (f.suite && run.su !== f.suite) return false;
    if (f.level && run.l !== f.level) return false;
    return true;
  }

  function filtered() {
    var rows = RUNS.filter(matches);
    var key = state.sort;
    var dir = state.dir;
    rows.sort(function (a, b) {
      var av = a[key], bv = b[key];
      if (av === null || av === undefined) return 1;    // blanks last, always
      if (bv === null || bv === undefined) return -1;
      if (av < bv) return -dir;
      if (av > bv) return dir;
      return 0;
    });
    return rows;
  }

  /* ------------------------------------------------------------ test cases */

  /* Name indices that are parent nodes rather than real tests, decided at build
   * time by rootcause.is_container. */
  var CONTAINERS = {};
  (DATA.containerNames || []).forEach(function (i) { CONTAINERS[i] = true; });

  /**
   * The first real failing test. Container entries are skipped: EOS emits a
   * failing parent for every nest above a failure, so the first failing *entry*
   * is usually `chip1` or `server_setup` — true, but not a signature anyone can
   * act on. Falls back to the container name only if there is nothing else.
   */
  function firstFailure(run) {
    var tests = run.T || [];
    var fallback = null;
    for (var i = 0; i < tests.length; i += 1) {
      var status = TSTATUS[tests[i][1]];
      if (status !== 'fail' && status !== 'error') continue;
      if (CONTAINERS[tests[i][0]]) {
        if (!fallback) fallback = NAMES[tests[i][0]] || null;
        continue;
      }
      return NAMES[tests[i][0]] || '—';
    }
    return fallback;
  }

  function isContainer(nameIndex) { return !!CONTAINERS[nameIndex]; }

  /* --------------------------------------------------------------- sources */

  function expand(template, run) {
    var map = {
      base: LINKS.base || '', runId: run.i || '', level: run.l || '',
      dut: run.d || '', suite: run.su || '', version: run.v || '',
      release: run.r || '', day: run.day || ''
    };
    return String(template).replace(/\{(\w+)\}/g, function (whole, key) {
      return Object.prototype.hasOwnProperty.call(map, key)
        ? encodeURIComponent(map[key]).replace(/%2F/g, '/') : whole;
    });
  }

  /* A template is configuration, but it still ends up in an href — anything
   * that is not plain http(s) does not get to be a link. */
  function safeUrl(url) {
    return /^https?:\/\//i.test(url || '') ? url : null;
  }

  /* The controller that ran it, when the bundle came from the controllers.
   * That is a real per-run address; OCP Logs has none, and sending a reader
   * from the controller-sourced page to OCP's search box made them look up by
   * hand a run whose URL we already hold. */
  function pegaUrl(run) {
    var cfg = LINKS.pega;
    if (!cfg || !run.i) return null;
    var host = (cfg.hosts || {})[run.k];
    if (!host) return null;
    var id = String(run.i), slot = null, hash = id.indexOf('#slot');
    if (hash !== -1) { slot = id.slice(hash + 5); id = id.slice(0, hash); }
    var url = (slot === null ? cfg.runTemplateNoSlot : cfg.urlTemplate)
      .replace('{host}', host).replace('{run}', encodeURIComponent(id))
      .replace('{slot}', encodeURIComponent(slot || ''));
    return { url: url, host: host };
  }

  function sourceCell(run) {
    var pega = pegaUrl(run);
    if (pega) {
      return h('td', { class: 'src' }, [
        h('a', { href: pega.url, target: '_blank', rel: 'noopener',
                 title: pega.url + '  (ESVM login admin / admin)',
                 text: pega.host + ' \u2197' })
      ]);
    }
    var direct = LINKS.runTemplate ? safeUrl(expand(LINKS.runTemplate, run)) : null;
    if (direct) {
      return h('td', { class: 'src' }, [
        h('a', { href: direct, target: '_blank', rel: 'noopener',
                 title: 'Open this run in OCP Logs', text: 'OCP ↗' })
      ]);
    }
    // No per-run route known yet: open the tool, and hand over the run ID so the
    // reader can paste it into OCP's own filters. See src/factory/links.py.
    var cell = h('td', { class: 'src' });
    var base = safeUrl(LINKS.base);
    if (base) {
      cell.appendChild(h('a', {
        href: base, target: '_blank', rel: 'noopener',
        title: 'OCP Logs is not deep-linkable yet — this opens its search page',
        text: 'search ↗'
      }));
    }
    cell.appendChild(h('button', {
      type: 'button', class: 'copy-id', title: 'Copy this run ID',
      text: 'copy id',
      onclick: function (event) {
        event.stopPropagation();
        copy(run.i, event.currentTarget);
      }
    }));
    return cell;
  }

  function copy(text, button) {
    var done = function () {
      if (!button) return;
      var was = button.textContent;
      button.textContent = 'copied';
      setTimeout(function () { button.textContent = was; }, 1200);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
    } else fallbackCopy(text, done);
  }

  function fallbackCopy(text, done) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', 'readonly');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); done(); } catch (e) { /* nothing to do */ }
    document.body.removeChild(area);
  }

  /* ----------------------------------------------------------------- render */

  var refs = {
    meta: document.getElementById('meta'),
    bar: document.getElementById('filterbar'),
    notice: document.getElementById('notice'),
    count: document.getElementById('count'),
    head: document.getElementById('runs-head'),
    body: document.getElementById('runs-body'),
    more: document.getElementById('more'),
    footer: document.getElementById('footer-meta'),
    sourceNote: document.getElementById('source-note'),
    copyTsv: document.getElementById('copy-tsv'),
    theme: document.getElementById('theme-toggle')
  };

  var COLUMNS = [
    { key: 'i', label: 'Run ID', sortable: true },
    { key: 'd', label: 'DUT', sortable: true },
    { key: 'k', label: 'Station', sortable: true },
    { key: 't', label: 'Start', sortable: true, align: 'right' },
    { key: 'u', label: 'Duration', sortable: true, align: 'right' },
    { key: 's', label: 'Status', sortable: true },
    { key: 'a', label: 'Att', sortable: true, align: 'right',
      title: 'Attempt number for this unit at this station' },
    { key: 'r', label: 'Release', sortable: true },
    { key: 'firstFail', label: 'First fail', sortable: false },
    { key: 'src', label: 'Source', sortable: false }
  ];

  function stationLabel(key) {
    return (DATA.stationLabels || {})[key] || key || '—';
  }

  /* The chip row. Each chip's × removes exactly one hash key, which is also the
   * only way to widen the filter — there is no hidden state to get out of sync. */
  function renderFilters() {
    clear(refs.bar);
    var active = FILTERS.filter(function (f) { return state.filters[f.key]; });

    refs.bar.appendChild(h('span', { class: 'filter-lead', text: 'Runs' }));
    if (!active.length) {
      refs.bar.appendChild(h('span', { class: 'chip chip-static', text: 'no filter — every collected run' }));
    }
    active.forEach(function (f) {
      var value = state.filters[f.key];
      var shown = f.key === 'station' ? stationLabel(value) : value;
      refs.bar.appendChild(h('span', { class: 'chip' }, [
        h('span', { class: 'chip-k', text: f.label }),
        h('span', { class: 'chip-v', text: String(shown) }),
        h('button', {
          type: 'button', class: 'chip-x', 'aria-label': 'Remove ' + f.label + ' filter',
          text: '×',
          onclick: function () {
            delete state.filters[f.key];
            state.showAll = false;
            writeHash();
            render();
          }
        })
      ]));
    });
    if (active.length > 1) {
      refs.bar.appendChild(h('button', {
        type: 'button', class: 'chip chip-clear', text: 'clear all',
        onclick: function () {
          state.filters = {};
          state.showAll = false;
          writeHash();
          render();
        }
      }));
    }
  }

  function renderHead() {
    clear(refs.head);
    var row = h('tr');
    row.appendChild(h('th', { class: 'expander-col', 'aria-label': 'Expand' }));
    COLUMNS.forEach(function (col) {
      var active = state.sort === col.key;
      var attrs = { class: (col.align === 'right' ? 'num' : '') + (active ? ' sorted' : '') };
      if (col.title) attrs.title = col.title;
      if (active) attrs['aria-sort'] = state.dir === 1 ? 'ascending' : 'descending';
      var cell = h('th', attrs);
      if (col.sortable) {
        cell.appendChild(h('button', {
          type: 'button', class: 'sort-btn', text: col.label +
            (active ? (state.dir === 1 ? ' ▲' : ' ▼') : ''),
          onclick: function () {
            if (state.sort === col.key) state.dir = -state.dir;
            else { state.sort = col.key; state.dir = col.key === 't' ? -1 : 1; }
            writeHash();
            render();
          }
        }));
      } else {
        cell.appendChild(h('span', { text: col.label }));
      }
      row.appendChild(cell);
    });
    refs.head.appendChild(row);
  }

  function renderRows(rows) {
    clear(refs.body);
    if (!rows.length) {
      refs.body.appendChild(h('tr', null, [
        h('td', { class: 'empty', colspan: String(COLUMNS.length + 1),
                  text: 'No runs match this filter.' })
      ]));
      return;
    }

    var shown = state.showAll ? rows : rows.slice(0, PAGE);
    shown.forEach(function (run) {
      var open = !!state.expanded[run.i];
      var fail = firstFailure(run);

      var tr = h('tr', {
        class: 'run-row' + (open ? ' open' : ''),
        tabindex: '0',
        'data-run': run.i,
        'aria-expanded': open ? 'true' : 'false',
        onclick: function () { toggle(run.i); },
        onkeydown: function (event) {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            toggle(run.i);
          }
        }
      }, [
        h('td', { class: 'expander-col' }, [
          h('span', { class: 'caret', text: open ? '▼' : '▶', 'aria-hidden': 'true' })
        ]),
        h('td', { class: 'runid' }, [h('code', { text: run.i || '—' })]),
        h('td', { text: run.d || '—' }),
        h('td', { text: stationLabel(run.k) }),
        h('td', { class: 'num', text: fmtStart(run.t) }),
        h('td', { class: 'num', text: fmtDur(run.u) }),
        h('td', null, [h('span', { class: 'status ' + (run.s || 'unknown'), text: run.s || 'unknown' })]),
        h('td', { class: 'num', text: run.a === null || run.a === undefined ? '—' : String(run.a) }),
        h('td', { text: run.r ? String(run.r) : '—' }),
        h('td', { class: 'firstfail', text: fail || (run.s === 'pass' ? '—' : (run.T || []).length ? '—' : 'no test detail') }),
        sourceCell(run)
      ]);
      refs.body.appendChild(tr);
      if (open) refs.body.appendChild(testRow(run));
    });

    refs.more.hidden = state.showAll || rows.length <= PAGE;
    if (!refs.more.hidden) {
      clear(refs.more);
      refs.more.appendChild(h('span', {
        text: 'Showing the first ' + PAGE + ' of ' + fmtInt(rows.length) + ' runs. '
      }));
      refs.more.appendChild(h('button', {
        type: 'button', class: 'view-toggle', text: 'Show all ' + fmtInt(rows.length),
        onclick: function () { state.showAll = true; render(); }
      }));
    }
  }

  function toggle(runId) {
    if (state.expanded[runId]) delete state.expanded[runId];
    else state.expanded[runId] = true;
    render();
    // render() replaces the row that was just activated, which would drop focus
    // to the body — a keyboard reader expanding runs down a list would lose
    // their place on every Enter. Put it back on the equivalent new row.
    var row = refs.body.querySelector('[data-run="' + cssEscape(runId) + '"]');
    if (row) row.focus();
  }

  /* Run IDs are `[A-Za-z0-9._-]` in practice, but this string is going into a
   * selector, so quote it properly rather than trusting that. */
  function cssEscape(value) {
    return String(value).replace(/["\\]/g, '\\$&');
  }

  function testRow(run) {
    var tests = run.T || [];
    var inner;
    if (!tests.length) {
      inner = h('p', { class: 'tests-empty',
        text: 'No test-case detail collected for this run — the suite summary was '
            + 'missing or the run never reported one.' });
    } else {
      var body = h('tbody');
      tests.forEach(function (test, i) {
        var status = TSTATUS[test[1]] || 'unknown';
        var group = isContainer(test[0]);
        body.appendChild(h('tr', { class: group ? 'container-row' : '' }, [
          h('td', { class: 'num idx', text: String(i + 1) }),
          h('td', { class: 'tname', text: NAMES[test[0]] || '(unnamed)' }, [
            // Labelled, not hidden: the reader should be able to see that a
            // failing row is a nest and know why it is not the signature.
            group ? h('span', { class: 'group-tag', text: 'group' }) : null
          ]),
          h('td', null, [h('span', { class: 'status ' + status, text: status })]),
          h('td', { class: 'num', text: fmtDur(test[2]) })
        ]));
      });
      inner = h('table', { class: 'tests-table' }, [
        h('thead', null, [h('tr', null, [
          h('th', { class: 'num', text: '#' }),
          h('th', { text: 'Test case' }),
          h('th', { text: 'Status' }),
          h('th', { class: 'num', text: 'Duration' })
        ])]),
        body
      ]);
    }
    return h('tr', { class: 'tests-row' }, [
      h('td', { colspan: String(COLUMNS.length + 1) }, [
        h('div', { class: 'tests-box' }, [
          h('div', { class: 'tests-head' }, [
            h('code', { text: run.i || '' }),
            h('span', { class: 'tests-meta', text: run.su ? run.su + ' · ' + (run.v || '') : '' })
          ]),
          inner
        ])
      ])
    ]);
  }

  /* TSV rather than CSV: run IDs and test names never contain tabs, so this
   * needs no quoting rules, and it pastes straight into a spreadsheet. */
  function tsv(rows) {
    var head = ['run_id', 'dut', 'station', 'level', 'suite', 'version', 'release',
                'day', 'started_utc', 'duration_sec', 'status', 'attempt', 'first_fail'];
    var lines = [head.join('\t')];
    rows.forEach(function (run) {
      lines.push([
        run.i, run.d, run.k, run.l, run.su, run.v, run.r, run.day,
        run.t ? new Date(run.t * 1000).toISOString() : '',
        run.u === null || run.u === undefined ? '' : run.u,
        run.s, run.a, firstFailure(run) || ''
      ].join('\t'));
    });
    return lines.join('\n');
  }

  function renderMeta(rows) {
    var window_ = DATA.window || {};
    refs.meta.textContent = (window_.from || '') + ' → ' + (window_.to || '')
      + ' · ' + (DATA.timezone || '');

    var units = {};
    rows.forEach(function (run) { if (run.d) units[run.d] = 1; });
    clear(refs.count);
    refs.count.appendChild(h('strong', { text: fmtInt(rows.length) + ' run' + (rows.length === 1 ? '' : 's') }));
    refs.count.appendChild(h('span', {
      class: 'runs-sub',
      text: ' · ' + fmtInt(Object.keys(units).length) + ' distinct unit'
        + (Object.keys(units).length === 1 ? '' : 's')
        + ' · of ' + fmtInt(RUNS.length) + ' collected'
    }));

    refs.footer.textContent = 'Collected ' + (DATA.collectedAt || '—')
      + (ago(DATA.collectedAt) ? ' (' + ago(DATA.collectedAt) + ')' : '')
      + ' · bundle built ' + (DATA.generatedAt || '—') + ' · source ' + (DATA.source || '—');

    clear(refs.sourceNote);
    if (LINKS.pega) {
      refs.sourceNote.textContent =
        'Source column: every run opens on the controller that ran it. ' +
        (LINKS.pega.note || '');
    } else if (!LINKS.runLinksResolve) {
      refs.sourceNote.appendChild(h('span', {
        text: 'Source column: OCP Logs has no confirmed per-run URL yet, so it '
            + 'opens the search page and offers the run ID to paste. Filling in '
            + 'FACTORY_OCP_RUN_URL turns it into direct links — see '
      }));
      refs.sourceNote.appendChild(h('code', { text: 'src/factory/links.py' }));
      refs.sourceNote.appendChild(h('span', { text: '.' }));
    }
  }

  function render() {
    var rows = filtered();
    renderFilters();
    renderHead();
    renderRows(rows);
    renderMeta(rows);
  }

  /* ------------------------------------------------------------------ wire */

  function init() {
    if (!RUNS.length) {
      refs.notice.hidden = false;
      refs.notice.textContent = 'No run bundle loaded. Run `make build` to generate '
        + 'dashboard/data/runs.js.';
    }

    readHash();
    render();

    // Back/forward, and links pasted into the same tab, both arrive as a hash
    // change rather than a load.
    window.addEventListener('hashchange', function () {
      state.showAll = false;
      readHash();
      render();
    });

    refs.copyTsv.addEventListener('click', function (event) {
      copy(tsv(filtered()), event.currentTarget);
    });

    var initial = document.documentElement.getAttribute('data-theme');
    refs.theme.textContent = 'Theme: ' + (initial || 'system');
    refs.theme.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme');
      var next = cur === 'dark' ? 'light' : cur === 'light' ? null : 'dark';
      if (next) document.documentElement.setAttribute('data-theme', next);
      else document.documentElement.removeAttribute('data-theme');
      refs.theme.textContent = 'Theme: ' + (next || 'system');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
