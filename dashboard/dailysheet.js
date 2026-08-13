/* The daily MLT/HTT tracker page.
 *
 * WHAT IT IS
 * A reproduction of the line's spreadsheet tab, column for column, in the
 * dashboard's own chrome. The sheet's meaning travels in the bundle as roles
 * ('pass', 'fail') rather than as the hex the spreadsheet happens to use, so
 * the page can render a designed dark theme instead of a pasted light one.
 *
 * WHAT IT ADDS THAT THE SPREADSHEET CANNOT
 * A DUT serial links into runs.html when — and only when — the collected run
 * table actually holds that serial. The builder decides; this file just renders
 * what it was told, because a link that 404s teaches the reader the drill-down
 * is broken rather than that EOS is missing the line's volume.
 *
 * Which day is showing lives in the URL hash (#day=2026-08-12), so a tab is a
 * link someone can paste — same contract as runs.html.
 *
 * Plain ES5, no build step, no dependencies, works over file://.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_DAILY_EXCEL__ || {};
  var TABS = DATA.tabs || [];

  var el = {};
  var current = null;

  /* ------------------------------------------------------------------ dom */

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  function byId(id) { return document.getElementById(id); }

  /* ----------------------------------------------------------------- hash */

  function hashDay() {
    var match = /day=([0-9-]+)/.exec(location.hash || '');
    return match ? match[1] : null;
  }

  function pick(day) {
    for (var i = 0; i < TABS.length; i++) {
      if (TABS[i].day === day) return TABS[i];
    }
    return TABS.length ? TABS[TABS.length - 1] : null;   /* newest by default */
  }

  /* ------------------------------------------------------------------ tabs */

  function renderTabs() {
    el.tabbar.innerHTML = '';
    TABS.forEach(function (tab) {
      var active = current && tab.day === current.day;
      /* Same markup the station bar uses — button + .n count — so the two
       * navigations look and behave alike rather than merely similar. */
      var button = h('button', {
        type: 'button',
        'aria-pressed': active ? 'true' : 'false'
      }, [
        document.createTextNode(tab.label),
        h('span', { class: 'n', text: tab.derived
          ? tab.rows.length + ' units · ' +
            (((tab.derivedFrom || {}).source === 'pega3') ? 'pega3' : 'derived')
          : tab.rows.length + ' units' })
      ]);
      button.addEventListener('click', function () {
        location.hash = 'day=' + tab.day;
      });
      el.tabbar.appendChild(button);
    });
  }

  /* --------------------------------------------------------------- summary */

  /* The sheet's own tallies, counted from its own colouring — deliberately not
   * recomputed from EOS. If these disagree with the station page, that is a
   * finding about the two sources, and flattening it here would hide it. */
  function renderSummary(tab) {
    el.summary.innerHTML = '';

    /* A derived tab must never be mistaken for the line's own record. It says
     * so before the numbers, not in a footnote under them. */
    if (tab.derived) {
      var from = tab.derivedFrom || {};
      var viaPega = from.source === 'pega3';
      el.summary.appendChild(h('div', { class: 'sheet-tile derived' }, [
        h('span', { class: 'tile-title', text: viaPega
          ? 'Rebuilt from pega3 — not the line\u2019s sheet'
          : 'Rebuilt from EOS — not the line\u2019s sheet' }),
        h('strong', { class: 'tile-value', text: from.runs + ' suite runs' }),
        h('span', { class: 'tile-sub', text: viaPega
          ? 'pega3 assigns the slots, so every unit is named. Rebuilding a day ' +
            'the line has already tracked reproduces its tab exactly — 08-12 ' +
            'came back 51 of 51 units with no verdict disagreeing.'
          : 'pega3 was unreachable, so this is graded from the per-chip test ' +
            'names in EOS. That gives verdicts but not serials.' })
      ]));
    }
    var counts = tab.counts || {};
    Object.keys(counts).forEach(function (key) {
      var entry = counts[key];
      var graded = entry.pass + entry.fail;
      var rate = graded ? Math.round((entry.pass / graded) * 1000) / 10 : null;
      el.summary.appendChild(h('div', { class: 'sheet-tile' }, [
        h('span', { class: 'tile-title', text: entry.title }),
        h('strong', { class: 'tile-value', text: rate === null ? '—' : rate + '%' }),
        h('span', { class: 'tile-sub' }, [
          h('span', { class: 'tone-pass', text: entry.pass + ' passed' }),
          h('span', { text: ' · ' }),
          h('span', { class: 'tone-fail', text: entry.fail + ' failed' }),
          entry.blank
            ? h('span', { class: 'tile-blank', text: ' · ' + entry.blank + ' not run' })
            : null
        ])
      ]));
    });

    /* The tab name carries the line's own unit count. If it disagrees with the
     * rows present, the export is mid-edit or a row was dropped — say so. */
    if (tab.claimedUnits && tab.claimedUnits !== tab.rows.length) {
      el.summary.appendChild(h('div', { class: 'sheet-tile warn' }, [
        h('span', { class: 'tile-title', text: 'Row count' }),
        h('strong', { class: 'tile-value', text: tab.rows.length }),
        h('span', {
          class: 'tile-sub',
          text: 'the tab is named for ' + tab.claimedUnits
        })
      ]));
    }
  }

  /* ----------------------------------------------------------------- table */

  function renderTable(tab) {
    var columns = tab.columns || [];

    var head = h('tr', {});
    columns.forEach(function (column) {
      var cell = h('th', { scope: 'col', text: column.title });
      if (column.width) {
        /* Excel widths are in characters; ~7px each plus the cell padding
         * keeps the proportions of the original without pinning it to a
         * pixel width that would break on a narrow screen. */
        cell.style.minWidth = Math.round(column.width * 7 + 12) + 'px';
      }
      head.appendChild(cell);
    });
    el.head.innerHTML = '';
    el.head.appendChild(head);

    /* A column the sheet made wide is a column meant to hold prose — failure
     * test cases, the Jira note. Those wrap; the short ones never do. */
    var wraps = columns.map(function (column) {
      return !!(column.width && column.width >= 20);
    });

    var body = document.createDocumentFragment();
    tab.rows.forEach(function (row, index) {
      var tr = h('tr', { class: index % 2 ? 'odd' : 'even' });
      row.forEach(function (cell, position) {
        tr.appendChild(renderCell(cell, columns[position], wraps[position]));
      });
      body.appendChild(tr);
    });
    el.body.innerHTML = '';
    el.body.appendChild(body);

    el.caption.textContent = tab.derived
      ? tab.rows.length + ' units across ' + (tab.derivedFrom || {}).runs +
        ' suite runs — ' + (tab.day || tab.label) + ', rebuilt from ' +
        (((tab.derivedFrom || {}).source === 'pega3') ? 'pega3' : 'EOS')
      : tab.rows.length + ' units — ' + (tab.day || tab.label) +
        ', as recorded by the line';
  }

  function renderCell(cell, column, wrap) {
    var td = h('td', {});
    var classes = [];
    if (cell.t) classes.push('tone-' + cell.t);
    if (wrap) classes.push('wrap');
    if (column && column.key === 'B') classes.push('serial');
    td.className = classes.join(' ');
    var value = cell.v == null ? '' : String(cell.v);

    if (!value) return td;

    if (cell.h) {
      /* The sheet's own link: short run id as text, pega3 suite_run as target.
       * rel=noreferrer because pega3 is an internal tool on plain HTTP. */
      td.appendChild(h('a', {
        class: 'sheet-link', href: cell.h, target: '_blank',
        rel: 'noopener noreferrer',
        title: cell.h + '  (pega3 asks for an ESVM login)'
      }, [document.createTextNode(value)]));
      return td;
    }

    if (cell.j) {
      td.appendChild(jiraCell(value, cell.j));
      return td;
    }

    if (cell.d) {
      /* Present in the collected run table, so the drill-down will resolve. */
      td.appendChild(h('a', {
        class: 'sheet-link dut-link',
        href: 'runs.html#dut=' + encodeURIComponent(cell.d),
        title: cell.title || 'Every collected run for this DUT'
      }, [document.createTextNode(value)]));
      return td;
    }

    td.textContent = value;
    return td;
  }

  function jiraCell(value, keys) {
    var base = (DATA.links && DATA.links.jiraBase) || '';
    var wrap = h('span', { class: 'jira' });
    if (!base) {
      /* No confirmed Jira URL from here, so the key is shown as a key. Set
       * FACTORY_JIRA_BASE and these become links with no other change. */
      wrap.appendChild(h('span', { class: 'jira-key', text: keys.join(' · ') }));
      var rest = value.replace(/^\s*[A-Z][A-Z0-9]+-\d+\s*:?\s*/, '');
      if (rest) wrap.appendChild(document.createTextNode(' ' + rest));
      return wrap;
    }
    keys.forEach(function (key, index) {
      if (index) wrap.appendChild(document.createTextNode(' · '));
      wrap.appendChild(h('a', {
        class: 'sheet-link jira-key', href: base + '/' + key,
        target: '_blank', rel: 'noopener noreferrer'
      }, [document.createTextNode(key)]));
    });
    var tail = value.replace(/^\s*[A-Z][A-Z0-9]+-\d+\s*:?\s*/, '');
    if (tail) wrap.appendChild(document.createTextNode(' ' + tail));
    return wrap;
  }


  /* Which build of the repo made this page. Published copies are rsynced by
   * hand, so a reader cannot otherwise tell whether they are looking at the
   * version that lists every failure on a unit or the one that listed the
   * first — and those answer the same question differently. */
  function renderBuild() {
    var build = DATA.build || {};
    if (!build.commit && !build.release) return;
    var slot = byId('build');
    if (!slot) return;

    if (build.release) {
      slot.appendChild(link(build.release, build.releaseUrl, 'release'));
      if (build.commitsSinceRelease) {
        slot.appendChild(h('span', { class: 'build-ahead',
          text: '+' + build.commitsSinceRelease }));
      }
    }
    if (build.commit) {
      slot.appendChild(link(build.commit, build.commitUrl, 'commit'));
    }
    if (build.dirty) {
      /* Built from a tree that is not any commit — worth saying out loud. */
      slot.appendChild(h('span', { class: 'build-dirty', title:
        'The working tree had uncommitted changes when this was built',
        text: 'uncommitted' }));
    }
    if (build.repo) {
      slot.appendChild(link('repo', build.repo, 'repo'));
    }
  }

  function link(text, href, kind) {
    if (!href) return h('span', { class: 'build-' + kind, text: text });
    return h('a', { class: 'build-' + kind, href: href, target: '_blank',
                    rel: 'noopener noreferrer', text: text });
  }

  /* ----------------------------------------------------------------- notes */

  function renderNotes() {
    var source = DATA.source || {};
    var cross = DATA.crossref || {};

    byId('meta').textContent = source.workbook || '';
    renderBuild();

    byId('footer-meta').textContent =
      'Exported ' + (source.modifiedAt || 'unknown').replace('T', ' ').replace('+00:00', ' UTC') +
      ' · built ' + (DATA.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC') +
      ' · ' + (source.tabsInWorkbook || '?') + ' tabs in the workbook, ' +
      TABS.length + ' published.';

    var note = byId('crossref-note');
    if (cross.duts) {
      note.textContent =
        'DUT serials link into the run table where EOS has the run: ' +
        cross.matched + ' of ' + cross.duts + ' do. The rest are not errors ' +
        'here — the line records more module tests on these days than the API ' +
        'returns, which is itself worth knowing.';
    }

    if (source.url) {
      var link = byId('source-note');
      link.appendChild(document.createTextNode('Source: '));
      link.appendChild(h('a', {
        href: source.url, target: '_blank', rel: 'noopener noreferrer',
        text: 'the tracker sheet on Google Drive'
      }));
      link.appendChild(document.createTextNode(
        ' — this page is a snapshot of an export, not a live view of it.'));
    }

    var warnings = DATA.warnings || [];
    if (warnings.length) {
      var banner = byId('notice');
      banner.hidden = false;
      banner.textContent = warnings.join(' · ');
    }
  }

  /* ------------------------------------------------------------------ wire */

  function show() {
    current = pick(hashDay());
    if (!current) return;
    renderTabs();
    renderSummary(current);
    renderTable(current);
    document.title = 'Daily tracker — ' + (current.day || current.label);
  }

  function init() {
    el.tabbar = byId('tabbar');
    el.summary = byId('summary');
    el.head = byId('sheet-head');
    el.body = byId('sheet-body');
    el.caption = byId('sheet-caption');

    if (!TABS.length) {
      var banner = byId('notice');
      banner.hidden = false;
      banner.textContent =
        'No tracker data. Export the sheet to daily/ and run `make dailyexcel`.';
      return;
    }

    renderNotes();
    show();
    window.addEventListener('hashchange', show);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
