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

  var view = { day: null, only: 'deltas' };

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

  var COLUMNS = [
    { key: 'sn', title: 'DUT SN' },
    { key: 'where', title: 'Shown in' },
    { key: 'station', title: 'Stage' },
    { key: 'local', title: 'Local sheet' },
    { key: 'online', title: 'Online' },
    { key: 'kind', title: 'Delta' },
    { key: 'asks', title: 'Question for' }
  ];

  function whereChip(where) {
    var text = { both: 'both', local: 'sheet only', online: 'dashboard only' }[where]
               || where;
    return h('span', { class: 'where w-' + where, text: text });
  }

  function caseList(names) {
    if (!names || !names.length) return h('span', { class: 'blank', text: '—' });
    var wrap = h('span', { class: 'cases' });
    names.forEach(function (name) {
      wrap.appendChild(h('code', { text: name }));
    });
    return wrap;
  }

  function verdict(value) {
    if (!value || value === 'blank') {
      return h('span', { class: 'blank', text: 'not run' });
    }
    return h('span', { class: 'v-' + value, text: value });
  }

  function rowsFor(day) {
    var out = [];
    (day.units || []).forEach(function (unit) {
      if (view.only === 'deltas' && !unit.deltas.length) return;
      if (!unit.deltas.length) {
        out.push({ unit: unit, delta: null });
        return;
      }
      unit.deltas.forEach(function (delta) {
        out.push({ unit: unit, delta: delta });
      });
    });
    return out;
  }

  function renderTable(day) {
    var head = byId('table-head'), body = byId('table-body');
    head.innerHTML = '';
    body.innerHTML = '';

    var tr = h('tr', {});
    COLUMNS.forEach(function (column) {
      tr.appendChild(h('th', { text: column.title }));
    });
    head.appendChild(tr);

    var rows = rowsFor(day);
    rows.forEach(function (entry) {
      var unit = entry.unit, delta = entry.delta;
      var line = h('tr', { class: delta ? 'has-delta' : 'agrees' });
      line.appendChild(snCell(day, unit));
      line.appendChild(h('td', {}, [whereChip(unit.where)]));

      if (!delta) {
        line.appendChild(h('td', { class: 'dim', text: 'MLT · HTT' }));
        line.appendChild(h('td', { class: 'dim' }, [verdict(unit.mlt.local),
                                                    document.createTextNode(' · '),
                                                    verdict(unit.htt.local)]));
        line.appendChild(h('td', { class: 'dim' }, [verdict(unit.mlt.online),
                                                    document.createTextNode(' · '),
                                                    verdict(unit.htt.online)]));
        line.appendChild(h('td', {}, [h('span', { class: 'kind-ok', text: 'agrees' })]));
        line.appendChild(h('td', { class: 'dim', text: '—' }));
        body.appendChild(line);
        return;
      }

      var meta = kindOf(delta.kind);
      var isCase = delta.kind.indexOf('case') === 0;
      line.appendChild(h('td', { text: delta.field }));

      if (isCase) {
        line.appendChild(h('td', {}, [caseList(delta.local)]));
        line.appendChild(h('td', {}, [caseList(delta.online)]));
      } else if (delta.kind === 'population') {
        line.appendChild(h('td', {}, [h('span', {
          class: delta.local === 'present' ? 'v-pass' : 'blank',
          text: delta.local })]));
        line.appendChild(h('td', {}, [h('span', {
          class: delta.online === 'present' ? 'v-pass' : 'blank',
          text: delta.online })]));
      } else {
        line.appendChild(h('td', {}, [verdict(delta.local)]));
        line.appendChild(h('td', {}, [verdict(delta.online)]));
      }

      line.appendChild(h('td', {}, [
        h('span', { class: 'kind k-' + delta.kind, text: meta.label,
                    title: meta.note }),
        delta.fixture
          ? h('span', { class: 'kind-extra',
                        text: delta.fixture.join(', ') + ' — no slot' })
          : null
      ]));
      line.appendChild(h('td', { class: 'asks',
                                 text: SIDE_LABEL[meta.side] || meta.side }));
      body.appendChild(line);
    });

    var withDelta = (day.units || []).filter(function (u) {
      return u.deltas.length;
    }).length;
    byId('table-sub').textContent =
      withDelta + ' of ' + plural((day.units || []).length, 'unit') +
      ' differ between the two readings, over ' +
      plural(rows.filter(function (r) { return r.delta; }).length, 'delta') + '.';
  }

  function renderFilters(day) {
    var host = byId('filters');
    host.innerHTML = '';
    [['deltas', 'Only the deltas'], ['all', 'Every unit']].forEach(function (pair) {
      var button = h('button', {
        type: 'button', class: 'view-toggle' + (view.only === pair[0] ? ' on' : ''),
        'aria-pressed': view.only === pair[0] ? 'true' : 'false', text: pair[1]
      });
      button.addEventListener('click', function () {
        view.only = pair[0];
        renderFilters(day);
        renderTable(day);
      });
      host.appendChild(button);
    });
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
    renderFilters(day);
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
