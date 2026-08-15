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
  /* The verdicts of the rows that are showing.
   *
   * These used to come straight from the bundle, so filtering the table to one
   * build left the tile saying 61.5% over all 39 units — a number describing a
   * table nobody was looking at. Recomputed here from the same rows the body
   * renders, which is the only way the two can be guaranteed to agree.
   */
  function countsFor(tab, rows) {
    var out = {};
    Object.keys(tab.counts || {}).forEach(function (key) {
      var at = columnIndex(tab, key);
      var tally = { pass: 0, fail: 0, blank: 0,
                    title: (tab.counts[key] || {}).title,
                    sub: subFor(tab, key, rows) };
      rows.forEach(function (row) {
        var tone = (row[at] || {}).t;
        if (tone === 'pass' || tone === 'fail') tally[tone] += 1;
        else tally.blank += 1;
      });
      out[key] = tally;
    });
    return out;
  }

  /* The build line under a heading, over whichever rows are showing: filter to
   * one version and it names that version instead of counting several. */
  function subFor(tab, resultKey, rows) {
    var at = columnIndex(tab, resultKey);
    var columns = tab.columns || [];
    if (at < 0 || !columns[at + 1] || columns[at + 1].kind !== 'version') {
      return (tab.counts[resultKey] || {}).sub;
    }
    var seen = [];
    rows.forEach(function (row) {
      var value = textOf(row[at + 1]);
      if (value && seen.indexOf(value) === -1) seen.push(value);
    });
    if (!seen.length) return null;
    if (seen.length === 1) return seen[0];
    return seen.length + ' versions in this column';
  }

  function renderSummary(tab, rows) {
    el.summary.innerHTML = '';

    /* A derived tab must never be mistaken for the line's own record. It says
     * so before the numbers, not in a footnote under them. */
    if (tab.derived) {
      var from = tab.derivedFrom || {};
      /* Name the controller that actually answered. Hard-coding pega3 here
       * told the L10 page, which is built from pega4, that pega3 had been
       * unreachable — a confident sentence about the wrong machine. */
      var source = from.source || 'eos';
      var viaPega = source.indexOf('pega') === 0;
      el.summary.appendChild(h('div', { class: 'sheet-tile derived' }, [
        h('span', { class: 'tile-title', text: viaPega
          ? 'Rebuilt from ' + source + ' \u2014 not a hand-kept sheet'
          : 'Rebuilt from EOS \u2014 not the line\u2019s sheet' }),
        h('strong', { class: 'tile-value', text: from.runs + ' suite runs' }),
        h('span', { class: 'tile-sub', text: viaPega
          ? source + ' drives these stations, so it knows every unit by name ' +
            'and every test case that failed on it.'
          : 'The controller was unreachable, so this is graded from the ' +
            'per-chip test names in EOS. That gives verdicts but not serials.' }),
        /* "No HTT today" and "HTT ran five times and every one was a debug
         * bundle" are different facts, and an empty column says the first
         * while meaning the second. */
        excludedNote(from),
        debugNote(from)
      ]));
    }
    /* The tiles below now describe the filtered set, so the filter has to be
     * visible beside them. A 100% tile with no note is the screenshot that
     * gets quoted as the day's yield. */
    if (filtered()) {
      var names = Object.keys(view.filters).map(function (key) {
        var at = columnIndex(tab, key);
        return (tab.columns[at] || {}).title || key;
      });
      el.summary.appendChild(h('div', { class: 'sheet-tile filtered' }, [
        h('span', { class: 'tile-title', text: 'Filtered view' }),
        h('strong', { class: 'tile-value',
                      text: rows.length + ' of ' + tab.rows.length }),
        h('span', { class: 'tile-sub',
                    text: 'by ' + names.join(', ') +
                          ' — every figure here counts only these rows' })
      ]));
    }

    var counts = countsFor(tab, rows);
    Object.keys(counts).forEach(function (key) {
      var entry = counts[key];
      var graded = entry.pass + entry.fail;
      var rate = graded ? Math.round((entry.pass / graded) * 1000) / 10 : null;
      el.summary.appendChild(h('div', { class: 'sheet-tile' }, [
        h('span', { class: 'tile-title' }, [
          document.createTextNode(entry.title),
          /* The build on its own line. One line of "MLT Results
           * mlt_validation_2026.225.0-gitb937ca2c" was wide enough to push the
           * failure column off the screen, and it is two facts anyway. */
          entry.sub ? h('span', { class: 'tile-build', text: entry.sub }) : null
        ]),
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
    if (tab.claimedUnits && tab.claimedUnits !== tab.rows.length &&
        rows.length === tab.rows.length) {
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

  /* Counted, but a day whose only HTT was a debug bundle reads very
   * differently from a normal day. The version column already names the build
   * per row; this puts it where the yield tile is, which is where the number
   * gets read from. */
  function debugNote(from) {
    var builds = from.debugBuilds || {};
    var stations = Object.keys(builds);
    if (!stations.length) return null;
    var parts = stations.map(function (key) {
      return key.toUpperCase() + ': ' + builds[key].join(', ');
    });
    return h('span', { class: 'tile-sub tile-debug',
      text: 'Counted, and not a release build — ' + parts.join(' · ') +
            '. Filter the version column to see release-only numbers.' });
  }

  function excludedNote(from) {
    var excluded = from.excluded || {};
    var stations = Object.keys(excluded);
    if (!stations.length) return null;
    var parts = stations.map(function (key) {
      return key.toUpperCase() + ': ' + excluded[key].join(', ');
    });
    return h('span', { class: 'tile-sub tile-excluded',
      text: 'Engineering runs left out of this tab — ' + parts.join(' · ') +
            '. They ran on the line; they are not line units.' });
  }

  /* ----------------------------------------------------------------- table */

  /* Which rows are showing, and why.
   *
   * Excel's Data/Filter, because that is what the line already knows: click a
   * heading, tick the values you want, sort from the same menu. The values
   * offered in one column are computed with the *other* columns' filters
   * already applied, so a menu never offers a value that would leave the table
   * empty — Excel does the same, and the alternative reads as a broken filter.
   */
  var view = { filters: {}, sort: null };

  function textOf(cell) {
    return cell && cell.v != null ? String(cell.v) : '';
  }

  function label(value) { return value === '' ? '(blank)' : value; }

  /* Serials, dates and run ids all sort wrongly as plain strings — 10 before
   * 9 — so digits inside the text are compared as numbers. */
  function compare(left, right) {
    if (left === right) return 0;
    if (left === '') return 1;          /* blanks last, filtered or not */
    if (right === '') return -1;
    return left.localeCompare(right, undefined, { numeric: true });
  }

  function keep(tab, row, skipKey) {
    var columns = tab.columns || [];
    for (var i = 0; i < columns.length; i++) {
      var allowed = view.filters[columns[i].key];
      if (!allowed || columns[i].key === skipKey) continue;
      if (allowed.indexOf(textOf(row[i])) === -1) return false;
    }
    return true;
  }

  function shownRows(tab) {
    var rows = (tab.rows || []).filter(function (row) {
      return keep(tab, row, null);
    });
    if (view.sort) {
      var index = columnIndex(tab, view.sort.key);
      if (index >= 0) {
        var direction = view.sort.dir === 'desc' ? -1 : 1;
        /* Decorate with the original position so equal values keep the
         * builder's order — passes before failures — instead of whatever the
         * engine's sort happens to do with ties. */
        rows = rows.map(function (row, at) { return [row, at]; });
        rows.sort(function (a, b) {
          var by = compare(textOf(a[0][index]), textOf(b[0][index]));
          return by ? by * direction : a[1] - b[1];
        });
        rows = rows.map(function (pair) { return pair[0]; });
      }
    }
    return rows;
  }

  function columnIndex(tab, key) {
    var columns = tab.columns || [];
    for (var i = 0; i < columns.length; i++) {
      if (columns[i].key === key) return i;
    }
    return -1;
  }

  function valuesFor(tab, key) {
    var index = columnIndex(tab, key);
    var counts = {};
    (tab.rows || []).forEach(function (row) {
      if (!keep(tab, row, key)) return;
      var value = textOf(row[index]);
      counts[value] = (counts[value] || 0) + 1;
    });
    return Object.keys(counts).sort(compare).map(function (value) {
      return { value: value, count: counts[value] };
    });
  }

  function filtered() {
    return Object.keys(view.filters).length > 0;
  }

  /* ----------------------------------------------------------- filter menu */

  var menu = null;

  function closeMenu() {
    if (menu && menu.parentNode) menu.parentNode.removeChild(menu);
    menu = null;
  }

  function openMenu(tab, column, anchor) {
    closeMenu();
    var values = valuesFor(tab, column.key);
    var chosen = view.filters[column.key];
    var picked = {};
    values.forEach(function (entry) {
      picked[entry.value] = !chosen || chosen.indexOf(entry.value) !== -1;
    });

    menu = h('div', { class: 'filter-menu', role: 'dialog',
                      'aria-label': 'Filter ' + column.title });
    menu.appendChild(h('div', { class: 'fm-head', text: column.title }));

    function sortButton(text, dir) {
      var button = h('button', { type: 'button', class: 'fm-sort', text: text });
      if (view.sort && view.sort.key === column.key && view.sort.dir === dir) {
        button.className += ' on';
      }
      button.addEventListener('click', function () {
        view.sort = { key: column.key, dir: dir };
        closeMenu();
        renderTable(tab);
      });
      return button;
    }
    menu.appendChild(h('div', { class: 'fm-sorts' }, [
      sortButton('Sort A \u2192 Z', 'asc'),
      sortButton('Sort Z \u2192 A', 'desc')
    ]));

    var search = h('input', { class: 'fm-search', type: 'search',
                              placeholder: 'Search values' });
    menu.appendChild(search);

    var list = h('div', { class: 'fm-list' });
    var boxes = [];
    values.forEach(function (entry) {
      var box = h('input', { type: 'checkbox' });
      box.checked = picked[entry.value];
      box.addEventListener('change', function () {
        picked[entry.value] = box.checked;
      });
      var row = h('label', { class: 'fm-row' }, [
        box,
        h('span', { class: 'fm-value', text: label(entry.value) }),
        h('span', { class: 'fm-count', text: String(entry.count) })
      ]);
      if (entry.value === '') row.className += ' blank';
      boxes.push({ entry: entry, box: box, row: row });
      list.appendChild(row);
    });
    menu.appendChild(list);

    search.addEventListener('input', function () {
      var needle = search.value.toLowerCase();
      boxes.forEach(function (item) {
        item.row.hidden = needle &&
          label(item.entry.value).toLowerCase().indexOf(needle) === -1;
      });
    });

    function setAll(state) {
      boxes.forEach(function (item) {
        if (item.row.hidden) return;      /* only what the search is showing */
        item.box.checked = state;
        picked[item.entry.value] = state;
      });
    }

    var apply = h('button', { type: 'button', class: 'fm-apply', text: 'Apply' });
    apply.addEventListener('click', function () {
      var allowed = values.filter(function (entry) { return picked[entry.value]; })
                          .map(function (entry) { return entry.value; });
      if (allowed.length === values.length) delete view.filters[column.key];
      else view.filters[column.key] = allowed;
      closeMenu();
      renderTable(tab);
    });

    var clear = h('button', { type: 'button', class: 'fm-clear',
                              text: 'Clear' });
    clear.addEventListener('click', function () {
      delete view.filters[column.key];
      closeMenu();
      renderTable(tab);
    });

    menu.appendChild(h('div', { class: 'fm-actions' }, [
      h('button', { type: 'button', class: 'fm-all', text: 'All' }),
      h('button', { type: 'button', class: 'fm-none', text: 'None' }),
      h('span', { class: 'fm-gap' }),
      clear, apply
    ]));
    menu.querySelector('.fm-all').addEventListener('click', function () {
      setAll(true);
    });
    menu.querySelector('.fm-none').addEventListener('click', function () {
      setAll(false);
    });

    document.body.appendChild(menu);
    var box = anchor.getBoundingClientRect();
    var width = menu.offsetWidth;
    /* Anchored to the heading, nudged back inside the viewport rather than
     * hanging off the right edge on the last column. */
    var left = Math.min(box.left, window.innerWidth - width - 12);
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = (box.bottom + 4) + 'px';
    search.focus();
  }

  document.addEventListener('click', function (event) {
    if (!menu) return;
    if (menu.contains(event.target)) return;
    if (event.target.closest && event.target.closest('.col-filter')) return;
    closeMenu();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeMenu();
  });
  window.addEventListener('resize', closeMenu);

  /* ---------------------------------------------------------------- table */

  function renderTable(tab) {
    var columns = tab.columns || [];
    var rows = shownRows(tab);

    var head = h('tr', {});
    /* A row number, not a data column: it counts what is showing, so after a
     * filter the last number is the answer to "how many". */
    head.appendChild(h('th', { scope: 'col', class: 'col-index', text: '#' }));

    columns.forEach(function (column) {
      var on = !!view.filters[column.key];
      var sorted = view.sort && view.sort.key === column.key;
      var sub = column.sub == null ? null : subFor(tab, column.key, rows);
      var button = h('button', {
        type: 'button', class: 'col-filter',
        'aria-label': 'Filter and sort ' + column.title,
        text: on ? '\u25BC\u2022' : '\u25BC'
      });
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        if (menu) { closeMenu(); return; }
        openMenu(tab, column, button);
      });

      var cell = h('th', { scope: 'col' }, [
        h('span', { class: 'col-head' }, [
          h('span', { class: 'col-name', text: column.title }),
          button
        ]),
        sub ? h('span', { class: 'col-build', text: sub }) : null
      ]);
      cell.className = (column.kind ? 'col-' + column.kind + ' ' : '') +
        (on ? 'is-filtered ' : '') + (sorted ? 'is-sorted' : '');
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
    rows.forEach(function (row, index) {
      var tr = h('tr', { class: index % 2 ? 'odd' : 'even' });
      tr.appendChild(h('td', { class: 'col-index', text: String(index + 1) }));
      row.forEach(function (cell, position) {
        var td = renderCell(cell, columns[position], wraps[position]);
        /* The per-unit build. It is the column that answers "which release was
         * this unit actually on", so it reads as data, not as prose. */
        if ((columns[position] || {}).kind) {
          td.className = ((td.className || '') + ' col-' +
                          columns[position].kind).trim();
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    el.body.innerHTML = '';
    el.body.appendChild(body);

    renderSummary(tab, rows);
    renderCaption(tab, rows.length);
  }

  function renderCaption(tab, showing) {
    var total = (tab.rows || []).length;
    var source = tab.derived
      ? (tab.day || tab.label) + ', rebuilt from ' +
        (((tab.derivedFrom || {}).source === 'pega3') ? 'pega3' : 'EOS')
      : (tab.day || tab.label) + ', as recorded by the line';

    el.caption.innerHTML = '';
    if (showing === total) {
      el.caption.appendChild(document.createTextNode(
        total + ' units — ' + source));
      return;
    }

    /* A filtered table that does not say so is a table someone will screenshot
     * and quote as the day's total. */
    el.caption.appendChild(h('strong', { class: 'cap-filtered',
      text: showing + ' of ' + total + ' units' }));
    el.caption.appendChild(document.createTextNode(' — ' + source + ' · '));
    var reset = h('button', { type: 'button', class: 'cap-reset',
                              text: 'clear filters' });
    reset.addEventListener('click', function () {
      view.filters = {};
      renderTable(tab);
    });
    el.caption.appendChild(reset);
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
    var previous = current;
    current = pick(hashDay());
    if (!current) return;
    if (!previous || previous.day !== current.day) {
      /* Filters belong to the table they were set on. Carrying them across a
       * tab switch hides rows for a reason that is no longer on the screen. */
      view.filters = {};
      view.sort = null;
      closeMenu();
    }
    renderTabs();
    renderTable(current);          /* renders the summary from the same rows */
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
