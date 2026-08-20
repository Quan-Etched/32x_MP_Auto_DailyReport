/* The line's tracker tab against this repo's reading of the same day.
 *
 * The page exists because two views of one day were both being quoted as "the
 * tracker" without anyone having put them side by side. They do not agree, and
 * the interesting part is not the size of the gap but its shape: most of it is
 * a cut time, some of it is the sheet carrying root causes the controllers
 * never recorded, and a small hard core of it is one side being wrong.
 *
 * So the cut time leads, the three readings sit beside each other without ever
 * being added together, and every row says which side each figure came from and
 * why they differ. A row that cannot be settled from the controllers says that
 * rather than picking a winner.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_DELTA__ || {};

  /* What each delta class means, and where the question lands. `side` is the
   * side that has to answer it — not the side that is "wrong", because for a
   * nest-only failure the sheet is the one holding the useful fact. */
  var KINDS = {
    'population': {
      label: 'Only on one side', side: 'either',
      note: 'The unit appears in one reading and not the other. Check the cut ' +
            'time first: a sheet put down at 23:00 cannot hold a run that ' +
            'started at 01:00, and that is not the sheet being wrong.'
    },
    'status': {
      label: 'Verdict differs', side: 'both',
      note: 'The pass/fail verdicts disagree, blank included. The class that ' +
            'moves a yield, and the one worth resolving first.'
    },
    'case-missing': {
      label: 'No case named', side: 'sheet',
      note: 'The sheet says the unit failed and names nothing. An empty ' +
            'failure cell beside "Failed" is the one thing that column must ' +
            'never say — the controller has the name.'
    },
    'case-prose': {
      label: 'Prose, not a case', side: 'sheet',
      note: 'The sheet names something that is not a test case ("chip not ' +
            'enumerated by RPC proxy"). More use than a class name to whoever ' +
            'wrote it, but it cannot be counted, grouped or linked.'
    },
    'case-fixture': {
      label: 'Fixture failure on a unit row', side: 'sheet',
      note: 'The controller recorded this failure with no slot at all — it ' +
            'belongs to the whole tray. PcieSetupTestCase failing once for ' +
            'eight units is not eight units failing PcieSetupTestCase.'
    },
    'case-nest-only': {
      label: 'Controller has only the wrapper', side: 'dashboard',
      note: 'For this slot the controller recorded nothing but the nesting ' +
            'wrapper, so the dashboard cell says SltModuleNestedTestCase and ' +
            'means "something failed here". The sheet often carries the real ' +
            'leaf, read out of the run log — which is a source this dashboard ' +
            'does not read.'
    },
    'case-subset': {
      label: 'Sheet has fewer', side: 'sheet',
      note: 'The sheet’s cases are all in the controller’s list and ' +
            'the controller has more. Usually the first failure recorded where ' +
            'the run had several.'
    },
    'case-extra': {
      label: 'Sheet has more', side: 'either',
      note: 'The sheet lists cases the controller does not. Either read from ' +
            'the log, or attributed from elsewhere.'
    },
    'case-overlap': {
      label: 'Lists partly agree', side: 'both',
      note: 'The two lists share some cases and each has its own. Not settled ' +
            'from the controllers.'
    },
    'case-conflict': {
      label: 'Lists disagree', side: 'both',
      note: 'No case in common, and the controller does not explain it. Left ' +
            'for a person.'
    }
  };

  var SIDE_LABEL = { sheet: 'the sheet', dashboard: 'the dashboard',
                     both: 'both', either: 'either' };

  /* Per-stage view state — which rows, which sort, which column filters.
   * Kept apart so sorting MLT does not disturb HTT. */
  var view = { stages: {} };

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
  function byId(id) { return document.getElementById(id); }
  function add(parent, node) { if (node) parent.appendChild(node); return node; }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  function kindOf(key) {
    return KINDS[key] || { label: key, side: 'either', note: '' };
  }

  function days() { return DATA.days || []; }
  function current() {
    var all = days();
    if (!all.length) return null;
    var match = /day=([0-9-]+)/.exec(location.hash || '');
    if (match) {
      var found = all.filter(function (d) { return d.day === match[1]; })[0];
      if (found) return found;
    }
    return all[all.length - 1];
  }

  /* ------------------------------------------------------------ deep links */

  function sheetUrl(day, row) {
    /* The form the sheet's own links use: gid twice, once as a query and once
     * in the fragment, because Google needs both to land on the tab. `range`
     * is what makes a row link a row link rather than a tab link. */
    var base = (DATA.source || {}).sheetUrl;
    if (!base) return null;
    if (!day.gid) return base;
    var at = base + '?gid=' + day.gid + '#gid=' + day.gid;
    var column = (day.columns || {}).sn || 'B';
    return row ? at + '&range=' + column + row : at + '&range=' + column + '1';
  }

  function snCell(day, unit) {
    var url = unit.row ? sheetUrl(day, unit.row) : null;
    var text = unit.sn;
    if (!url) return h('td', { class: 'mono', text: text });
    return h('td', { class: 'mono' }, [
      h('a', { href: url, target: '_blank', rel: 'noopener noreferrer',
               title: 'row ' + unit.row + ' of ' + day.tab + ' in the sheet',
               text: text })
    ]);
  }

  /* --------------------------------------------------------------- yields  */

  function yieldTile(title, sub, counts, tone) {
    var rate = counts && counts['yield'];
    return h('div', { class: 'sheet-tile' + (tone ? ' ' + tone : '') }, [
      h('span', { class: 'tile-title' }, [
        document.createTextNode(title),
        sub ? h('span', { class: 'tile-build', text: sub }) : null
      ]),
      h('strong', { class: 'tile-value',
                    text: rate === null || rate === undefined ? '—' : rate + '%' }),
      h('span', { class: 'tile-sub tile-verdicts' }, [
        h('span', { class: 'tone-pass', text: (counts.pass || 0) + ' passed' }),
        h('span', { text: ' · ' }),
        h('span', { class: 'tone-fail', text: (counts.fail || 0) + ' failed' })
      ]),
      counts.blank
        ? h('span', { class: 'tile-sub', text: counts.blank + ' not run' }) : null,
      h('span', { class: 'tile-sub',
                  text: plural(counts.graded || 0, 'unit') + ' graded' })
    ]);
  }

  function reportedCounts(said) {
    if (!said) return null;
    var p = said.pass || 0, f = said.fail || 0;
    return { pass: p, fail: f, blank: 0, graded: p + f,
             'yield': p + f ? Math.round(1000 * p / (p + f)) / 10 : null };
  }

  function renderYields(day) {
    var host = byId('yields');
    host.innerHTML = '';
    var counts = day.counts || {};
    var said = day.reported || {};

    [['mlt', 'MLT'], ['htt', 'HTT']].forEach(function (pair) {
      var key = pair[0], label = pair[1];
      var group = h('div', { class: 'delta-group' });
      group.appendChild(h('h3', { class: 'delta-group-head', text: label }));
      var strip = h('div', { class: 'sheet-summary' });
      /* Reported first — it is the number people acted on. */
      var r = reportedCounts(said[key]);
      if (r) {
        add(strip, yieldTile('Reported', said.by ? 'by ' + said.by : null,
                             r, 'reported'));
      }
      add(strip, yieldTile('Local sheet', day.tab, (counts.local || {})[key] || {},
                           'local'));
      add(strip, yieldTile('Online', ((day.onlineTab || {}).derived
                             ? 'rebuilt from ' +
                               (((day.onlineTab || {}).derivedFrom || {}).source || 'the controllers')
                             : 'from the sheet'),
                           (counts.online || {})[key] || {}, 'online'));
      strip && group.appendChild(strip);
      host.appendChild(group);
    });

    byId('yield-sub').textContent =
      'Three readings, never added together. ' +
      plural((counts.local || {}).rows || 0, 'unit') + ' on the sheet, ' +
      plural((counts.online || {}).rows || 0, 'unit') + ' in the dashboard' +
      (said.units ? ', ' + said.units + ' reported at the cut' : '') + '.';
  }

  function renderReconcile(day) {
    var host = byId('reconcile');
    host.innerHTML = '';
    var deltas = day.reportedDelta || {};
    var keys = Object.keys(deltas);
    if (!keys.length) return;

    var lines = keys.map(function (key) {
      var d = deltas[key];
      if (d.agrees) {
        return d.label + ' still matches the posted figures exactly (' +
               d.reportedPass + ' pass / ' + d.reportedFail + ' fail), so that ' +
               'column has not been touched since the cut.';
      }
      var parts = [];
      if (d.passDelta) parts.push((d.passDelta > 0 ? '+' : '') + d.passDelta + ' pass');
      if (d.failDelta) parts.push((d.failDelta > 0 ? '+' : '') + d.failDelta + ' fail');
      return d.label + ' has moved since the cut: the post said ' +
             d.reportedPass + ' / ' + d.reportedFail + ' and the tab now holds ' +
             d.sheetPass + ' / ' + d.sheetFail + ' (' + parts.join(', ') +
             '), which dates the sheet’s last edit better than its file ' +
             'timestamp does.';
    });
    host.appendChild(h('p', { class: 'delta-note',
                              text: lines.join(' ') }));

    /* A version in the post that the tab and the Jira both contradict. Shown,
     * not silently preferred away. */
    keys.forEach(function (key) {
      var d = deltas[key];
      var online = (((day.onlineTab || {}).derivedFrom || {}).versions || {})[key];
      if (d.reportedVersion && online &&
          d.reportedVersion.indexOf(online) === -1 &&
          online.indexOf(d.reportedVersion) === -1) {
        host.appendChild(h('p', { class: 'delta-warn', text:
          d.label + ': the post says version ' + d.reportedVersion +
          ', while the tab heading and the controllers both say ' + online +
          '. One of the three is a typo, and it is worth knowing which before ' +
          'the figure is quoted against a release.' }));
      }
    });
  }

  /* ---------------------------------------------------------------- table  */

  /* One table per stage, six columns, sortable and filterable per column.
   *
   * Two tables rather than one because a unit reaches MLT and HTT separately.
   * On 08-20 the sheet holds 78 MLT verdicts and 49 HTT ones, so "is this unit
   * in Excel" has two different answers and a single row cannot give both
   * without qualifying every cell. Each table lists the units either side has a
   * verdict for at that stage, and carries its own CSV.
   *
   * Column meanings, per stage:
   *   Excel      the sheet records a verdict for this unit at this stage
   *   Dashboard  the controllers do
   *   Fresh      first visit to this stage, or back again — the dashboard's
   *              answer, since the sheet has no column for it
   *   Location   the run to open, or the sheet cell where there is no run
   *   Action_Item blank only where the two agree on everything
   */
  var STAGES = [{ key: 'mlt', label: 'MLT' }, { key: 'htt', label: 'HTT' }];

  var COLUMNS = [
    { key: 'sn',        title: 'DUT_SN',      kind: 'text' },
    { key: 'excel',     title: 'Excel',       kind: 'yesno' },
    { key: 'dashboard', title: 'Dashboard',   kind: 'yesno' },
    { key: 'fresh',     title: 'Fresh',       kind: 'yesno' },
    { key: 'location',  title: 'Location',    kind: 'text' },
    { key: 'action',    title: 'Action_Item', kind: 'text' }
  ];

  /* A verdict the sheet or the controller actually recorded, as opposed to a
   * stage the unit has not reached. "Blank" is not a result. */
  function graded(value) {
    return value === 'pass' || value === 'fail' || value === 'abort';
  }

  /* Excel's own A1 notation, so a location can be read out loud and typed into
   * the Name Box. The tab name is included because the workbook has twenty. */
  function cellRef(day, unit) {
    if (!unit.row) return '';
    var column = (day.columns || {}).sn || 'B';
    return day.tab + '!' + column + unit.row;
  }

  /* What this stage's row is asking for, in the words the ask came in. */
  function actionFor(unit, stage) {
    var side = unit[stage.key] || {};
    var inExcel = graded(side.local);
    var inDash = graded(side.online);

    if (inExcel && !inDash) {
      return 'Deep dive on why there is excel record? Mistake in Excel or Dash?';
    }
    if (!inExcel && inDash) {
      /* Two different situations, and conflating them would waste somebody's
       * afternoon: a unit the sheet never lists at all, versus one it lists
       * with this stage still blank because the stage had not run when the
       * sheet was written. */
      return unit.where === 'online'
        ? 'Deep dive on why there is dash record? Mistake in Dash or Excel?'
        : 'On the Excel row but this stage is blank there. Deep dive on why ' +
          'there is dash record? Mistake in Dash or Excel?';
    }
    /* Both recorded a verdict. Anything left is a disagreement about what it
     * was, or about which case failed. */
    var mine = (unit.deltas || []).filter(function (delta) {
      return delta.station === stage.key;
    });
    if (!mine.length) return '';
    return mine.map(function (delta) {
      var meta = kindOf(delta.kind);
      var local = Array.isArray(delta.local)
        ? (delta.local.join(' + ') || 'blank') : (delta.local || 'blank');
      var online = Array.isArray(delta.online)
        ? (delta.online.join(' + ') || 'blank') : (delta.online || 'blank');
      return delta.field + ': Excel says ' + local + ', Dashboard says ' +
             online + ' — ' + meta.label.toLowerCase() + ', question for ' +
             (SIDE_LABEL[meta.side] || meta.side);
    }).join('. ');
  }

  /* The rows for one stage, in the shape both the table and its CSV use. Built
   * once so the file somebody downloads cannot disagree with the page they
   * downloaded it from. */
  function rowsFor(day, stage) {
    var out = [];
    (day.units || []).forEach(function (unit) {
      var side = unit[stage.key] || {};
      var inExcel = graded(side.local);
      var inDash = graded(side.online);
      /* Neither side has a verdict here, so there is nothing for this stage to
       * compare. The unit is not missing; it has not reached this stage. */
      if (!inExcel && !inDash) return;
      out.push({
        unit: unit,
        sn: unit.sn,
        excel: inExcel,
        dashboard: inDash,
        fresh: side.fresh !== false,
        seen: side.seen || '',
        attempts: side.attempts || 0,
        /* The run to open. This stage's run, never the other stage's — a row
         * about HTT that opens the MLT run wastes the click. */
        url: inDash ? (side.url || '') : '',
        cell: cellRef(day, unit),
        sheetUrl: unit.row ? sheetUrl(day, unit.row) : '',
        action: actionFor(unit, stage)
      });
    });
    return out;
  }

  /* ----------------------------------------------------- sort and filter ---
   *
   * Click a heading to sort, click again to reverse, click a third time to go
   * back to serial order — which is the one ordering that is not an opinion.
   * The three YES/NO columns also carry a small select, which is the Excel data
   * filter in the form that fits a heading cell.
   *
   * Both live in `view` per stage, so sorting MLT does not disturb HTT. */
  function stageView(stage) {
    view.stages = view.stages || {};
    if (!view.stages[stage.key]) {
      view.stages[stage.key] = { only: 'deltas', sort: null, filters: {} };
    }
    return view.stages[stage.key];
  }

  function sortValue(row, column) {
    switch (column.key) {
      case 'sn': return row.sn;
      case 'excel': return row.excel ? 0 : 1;
      case 'dashboard': return row.dashboard ? 0 : 1;
      case 'fresh': return row.fresh ? 0 : 1;
      case 'location': return row.url || row.cell || '';
      /* Blank last whichever way it is sorted: the rows with an action are the
       * reason the table exists, and burying them under the quiet ones would
       * defeat the sort. */
      case 'action': return row.action || '￿';
      default: return '';
    }
  }

  function applyView(rows, state) {
    var out = rows.filter(function (row) {
      if (state.only === 'deltas' && !row.action) return false;
      return Object.keys(state.filters).every(function (key) {
        var want = state.filters[key];
        if (!want) return true;
        return (row[key] ? 'YES' : 'NO') === want;
      });
    });
    if (state.sort) {
      var column = COLUMNS.filter(function (c) {
        return c.key === state.sort.key;
      })[0];
      var dir = state.sort.dir === 'desc' ? -1 : 1;
      /* Stable: equal rows keep serial order, so a YES/NO sort does not
       * scramble the serials inside each group. */
      out = out.map(function (row, at) { return { row: row, at: at }; })
        .sort(function (a, b) {
          var av = sortValue(a.row, column), bv = sortValue(b.row, column);
          if (av < bv) return -dir;
          if (av > bv) return dir;
          return a.at - b.at;
        })
        .map(function (pair) { return pair.row; });
    }
    return out;
  }

  function headerCell(stage, column, rows) {
    var state = stageView(stage);
    var sorted = state.sort && state.sort.key === column.key;
    var cell = h('th', { class: 'c-' + column.key + (sorted ? ' sorted' : '') });

    var label = h('button', {
      type: 'button', class: 'sort-btn',
      title: 'sort by ' + column.title +
             (sorted && state.sort.dir === 'asc' ? ' (descending)'
              : sorted ? ' (back to serial order)' : '')
    }, [
      document.createTextNode(column.title),
      h('span', { class: 'sort-mark',
                  text: sorted ? (state.sort.dir === 'asc' ? '▲' : '▼') : '' })
    ]);
    label.addEventListener('click', function () {
      if (!sorted) state.sort = { key: column.key, dir: 'asc' };
      else if (state.sort.dir === 'asc') state.sort.dir = 'desc';
      else state.sort = null;
      renderStage(stage);
    });
    cell.appendChild(label);

    if (column.kind === 'yesno') {
      /* Only the values actually present, so the menu never offers a filter
       * that empties the table. */
      var present = {};
      rows.forEach(function (row) { present[row[column.key] ? 'YES' : 'NO'] = true; });
      var select = h('select', { class: 'col-filter',
                                 'aria-label': 'filter ' + column.title });
      [['', 'All']].concat(Object.keys(present).sort().map(function (v) {
        return [v, v];
      })).forEach(function (pair) {
        var option = h('option', { value: pair[0], text: pair[1] });
        if ((state.filters[column.key] || '') === pair[0]) {
          option.setAttribute('selected', 'selected');
        }
        select.appendChild(option);
      });
      select.addEventListener('change', function (event) {
        state.filters[column.key] = event.target.value;
        renderStage(stage);
      });
      cell.appendChild(select);
    }
    return cell;
  }

  function freshCell(row) {
    /* "NO ×8" rather than a bare NO: how many times a unit has been here is the
     * next thing anybody asks, and it is already in hand. */
    var cell = h('td', { class: 'c-fresh' });
    cell.appendChild(h('span', {
      class: row.fresh ? 'yes' : 'no',
      title: row.fresh ? 'first visit to this stage'
             : 'last seen ' + (row.seen || 'earlier') + ', ' +
               row.attempts + ' prior attempt' + (row.attempts === 1 ? '' : 's'),
      text: row.fresh ? 'YES' : 'NO'
    }));
    if (!row.fresh && row.attempts) {
      cell.appendChild(h('span', { class: 'attempts', text: '×' + row.attempts }));
    }
    return cell;
  }

  function yesNo(value) {
    return h('span', { class: value ? 'yes' : 'no', text: value ? 'YES' : 'NO' });
  }

  function renderStage(stage) {
    var day = current();
    if (!day) return;
    var state = stageView(stage);
    var all = rowsFor(day, stage);
    var rows = applyView(all, state);

    var head = byId('head-' + stage.key), body = byId('body-' + stage.key);
    head.innerHTML = '';
    body.innerHTML = '';

    var tr = h('tr', {});
    COLUMNS.forEach(function (column) {
      tr.appendChild(headerCell(stage, column, all));
    });
    head.appendChild(tr);

    rows.forEach(function (row) {
      var line = h('tr', { class: row.action ? 'has-delta' : 'agrees' });
      line.appendChild(h('td', { class: 'mono' }, [
        row.sheetUrl
          ? h('a', { href: row.sheetUrl, target: '_blank',
                     rel: 'noopener noreferrer', title: row.cell, text: row.sn })
          : document.createTextNode(row.sn)
      ]));
      line.appendChild(h('td', { class: 'c-excel' }, [yesNo(row.excel)]));
      line.appendChild(h('td', { class: 'c-dashboard' }, [yesNo(row.dashboard)]));
      line.appendChild(freshCell(row));

      var location = h('td', { class: 'c-location' });
      if (row.url) {
        location.appendChild(h('a', {
          href: row.url, target: '_blank', rel: 'noopener noreferrer',
          class: 'fi-link', title: row.url, text: 'FI_Link'
        }));
      } else if (row.cell) {
        location.appendChild(row.sheetUrl
          ? h('a', { href: row.sheetUrl, target: '_blank',
                     rel: 'noopener noreferrer', class: 'mono-sm', text: row.cell })
          : h('span', { class: 'mono-sm', text: row.cell }));
      } else {
        location.appendChild(h('span', { class: 'blank', text: '—' }));
      }
      line.appendChild(location);
      line.appendChild(h('td', { class: 'c-action', text: row.action }));
      body.appendChild(line);
    });

    var asking = all.filter(function (row) { return row.action; }).length;
    var fresh = all.filter(function (row) { return row.fresh; }).length;
    byId('sub-' + stage.key).textContent =
      all.length + ' units reached ' + stage.label + ' on either side — ' +
      fresh + ' fresh, ' + (all.length - fresh) + ' back again. ' +
      asking + ' with something to chase' +
      (rows.length === all.length ? '' : '; showing ' + rows.length) + '.';

    renderViewButtons(stage);
    renderDownload(day, stage, rows);
  }

  function renderViewButtons(stage) {
    var host = byId('view-' + stage.key);
    var state = stageView(stage);
    host.innerHTML = '';
    [['deltas', 'Only what needs chasing'],
     ['all', 'Every unit']].forEach(function (pair) {
      var button = h('button', {
        type: 'button',
        class: 'view-toggle' + (state.only === pair[0] ? ' on' : ''),
        'aria-pressed': state.only === pair[0] ? 'true' : 'false', text: pair[1]
      });
      button.addEventListener('click', function () {
        state.only = pair[0];
        renderStage(stage);
      });
      host.appendChild(button);
    });
  }

  function renderTable(day) {
    STAGES.forEach(function (stage) { renderStage(stage); });
  }

  /* --------------------------------------------------------------- the CSV */

  /* One CSV per stage, from the same rows that stage's table was rendered from
   * — same order, same filter, same sort.
   *
   * Generated in the browser rather than written out by the build, because it
   * has to follow what is on screen and a file on disk could only ever match
   * one view of it. */
  var CSV_COLUMNS = [
    ['DUT_SN', function (row) { return row.sn; }],
    ['Excel', function (row) { return row.excel ? 'YES' : 'NO'; }],
    ['Dashboard', function (row) { return row.dashboard ? 'YES' : 'NO'; }],
    ['Fresh', function (row) { return row.fresh ? 'YES' : 'NO'; }],
    /* A number rather than "×8" in the cell: this is the column somebody will
     * sort and filter on in Excel, and "×8" does neither. */
    ['Prior_Attempts', function (row) { return row.fresh ? 0 : row.attempts; }],
    ['Last_Seen', function (row) { return row.seen || ''; }],
    /* The URL itself, not the words "FI_Link" — a spreadsheet cell reading
     * "FI_Link" with no link in it is worse than useless. */
    ['Location', function (row) { return row.url || row.cell || ''; }],
    ['Action_Item', function (row) { return row.action; }]
  ];

  function csvFor(rows) {
    var lines = [CSV_COLUMNS.map(function (pair) { return pair[0]; })];
    rows.forEach(function (row) {
      lines.push(CSV_COLUMNS.map(function (pair) { return pair[1](row); }));
    });
    return lines.map(function (line) {
      return line.map(function (cell) {
        var text = String(cell === null || cell === undefined ? '' : cell);
        return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
      }).join(',');
    }).join('\r\n');
  }

  function renderDownload(day, stage, rows) {
    var host = byId('download-' + stage.key);
    if (!host) return;
    host.innerHTML = '';
    /* A BOM, because this is opened in Excel by the people who keep the sheet,
     * and without one Excel reads UTF-8 as its local codepage. */
    var blob = new Blob(['﻿' + csvFor(rows)],
                        { type: 'text/csv;charset=utf-8' });
    var state = stageView(stage);
    var name = 'delta-' + day.day + '-' + stage.key +
               (state.only === 'deltas' ? '-to-chase' : '-all') + '.csv';
    host.appendChild(h('a', {
      class: 'view-toggle', download: name, href: URL.createObjectURL(blob),
      title: 'the ' + rows.length + ' ' + stage.label +
             ' rows below, exactly as filtered and sorted'
    }, [document.createTextNode('Download ' + stage.label + ' CSV')]));
  }

  /* --------------------------------------------------------------- legend  */

  function renderLegend(day) {
    var host = byId('legend');
    host.innerHTML = '';
    var seen = day.kinds || {};
    var table = h('table', { class: 'delta-legend' });
    table.appendChild(h('tr', {}, [
      h('th', { text: 'Delta' }), h('th', { class: 'num', text: 'Count' }),
      h('th', { text: 'Question for' }), h('th', { text: 'What it means' })
    ]));
    Object.keys(KINDS).forEach(function (key) {
      var meta = KINDS[key];
      var count = seen[key] || 0;
      table.appendChild(h('tr', { class: count ? '' : 'dim' }, [
        h('td', {}, [h('span', { class: 'kind k-' + key, text: meta.label })]),
        h('td', { class: 'num', text: count ? String(count) : '—' }),
        h('td', { text: SIDE_LABEL[meta.side] || meta.side }),
        h('td', { text: meta.note })
      ]));
    });
    host.appendChild(table);
  }

  /* ----------------------------------------------------------------- chrome */

  function renderCut(day) {
    var said = day.reported || {};
    var banner = byId('cut');
    if (!said.cutAt) { banner.hidden = true; return; }
    banner.hidden = false;
    banner.innerHTML = '';
    var onlineOnly = (day.units || []).filter(function (u) {
      return u.where === 'online';
    }).length;
    banner.appendChild(h('strong', {
      text: 'The sheet was cut at ' + said.cutAt.replace('T', ' ') + '.' }));
    banner.appendChild(h('span', { text: ' ' +
      (said.stillRunningUntil
        ? 'The line kept testing until ' +
          said.stillRunningUntil.replace('T', ' ') + ', so '
        : 'So ') +
      'the controllers legitimately hold units the sheet cannot' +
      (onlineOnly ? ' — ' + onlineOnly + ' of them here' : '') +
      '. Read the population gap as work that came in after the sheet was put ' +
      'down, not as rows the sheet lost.' +
      (said.note ? ' Reported at the time: “' + said.note + '”' : '') }));
  }

  function renderDays() {
    var host = byId('daytabs');
    host.innerHTML = '';
    var all = days();
    if (all.length < 2) return;
    all.forEach(function (day) {
      var cell = h('button', {
        type: 'button',
        class: 'daycal-day' + (day === current() ? ' on' : ''),
        text: day.day
      });
      cell.addEventListener('click', function () {
        location.hash = 'day=' + day.day;
      });
      host.appendChild(cell);
    });
  }

  function renderFooter(day) {
    var source = DATA.source || {};
    byId('footer-meta').textContent =
      'Sheet: ' + (source.workbook || '?') +
      (source.modifiedAt ? ', exported ' + source.modifiedAt.replace('T', ' ') : '') +
      '. Dashboard: ' +
      ((day.onlineTab || {}).derived
        ? 'rebuilt from ' + (((day.onlineTab || {}).derivedFrom || {}).source
                             || 'the controllers') +
          ' — the published workbook (' + (source.publishedWorkbook || '?') +
          ', exported ' +
          String(source.publishedModifiedAt || '?').replace('T', ' ') +
          ') has no tab for this day, which is why there is one to compare ' +
          'against at all.'
        : 'the published workbook’s own tab for this day.') +
      ' Built ' + String(DATA.generatedAt || '').replace('T', ' ') + '.';

    var caveats = [];
    if (day.numericSerials) {
      caveats.push('The sheet stores DUT SN as a number, not text, on ' +
        plural(day.numericSerials, 'row') + ' — so the cell reads ' +
        '2.68525E+14 to whoever opens it, and a sixteen-digit serial would ' +
        'lose its last digit with nothing to show that it had. Formatting ' +
        'that column as text costs nothing and removes the risk.');
    }
    if (day.trailing) {
      caveats.push(plural(day.trailing, 'row') + ' at the bottom of the tab ' +
        'carry a row number and no unit. Counted here as waiting rather than ' +
        'as blank results, which is what treating them as units would invent.');
    }
    caveats.push('A delta is not a defect. Where the controllers can settle ' +
      'one this page says so; where they cannot it says that instead, and the ' +
      'row stays open.');
    byId('footer-caveats').textContent = caveats.join(' ');
  }

  /* -------------------------------------------------------------------- run */

  function render() {
    var day = current();
    if (!day) {
      var notice = byId('notice');
      notice.hidden = false;
      notice.textContent = DATA.days
        ? 'No day in the hand-kept workbook lines up with a day the dashboard ' +
          'has. Put the export in diff/ and run `make delta`.'
        : 'Not built — run `make delta` where the hand-kept export is.';
      return;
    }
    byId('meta').textContent = day.day + ' · ' + day.tab;
    var build = (DATA.build || {});
    byId('build').textContent = build.release
      ? build.release + ' · ' + build.commit : '';
    byId('back').setAttribute('href', 'dailyexcel.html#day=' + day.day);

    var link = byId('sheet-link');
    var url = sheetUrl(day, null);
    if (url) { link.hidden = false; link.setAttribute('href', url); }

    if (day.missing) {
      var notice2 = byId('notice');
      notice2.hidden = false;
      notice2.textContent = day.missing;
    }

    renderDays();
    renderCut(day);
    renderYields(day);
    renderReconcile(day);
    renderTable(day);
    renderLegend(day);
    renderFooter(day);
  }

  function init() {
    if (!byId('table-body')) return;
    render();
    window.addEventListener('hashchange', render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
