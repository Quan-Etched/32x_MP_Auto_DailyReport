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

  /* Which units the tiles count.
   *
   * 'new' by default: a day's yield is read as "how did today's build go",
   * and a unit that failed last Monday and is re-run today answers a
   * different question — whether a fix worked, not how the fresh material is
   * doing. On 08-16 that distinction is the whole story: the tab reads 87.5%
   * at MLT and every one of those sixteen units was a returning one, so the
   * figure is not a build yield at all.
   */
  var countMode = 'new';

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
  /* The same tile, over release builds alone.
   *
   * The tab counts validation and debug runs deliberately — they are real
   * units on real stations, and the version column names them. But the
   * percentage above the table must not quietly become a mixture: on 08-14 the
   * MLT tile read 61.5% including a validation campaign and 53.3% without it,
   * and somebody reading the first as the day's line yield is how this comes
   * back as a correction later.
   */
  function releaseOnly(entry) {
    var rel = (countMode === 'new' && entry.newRelease)
      ? entry.newRelease : entry.release;
    if (!rel || !(entry.nonRelease || []).length) return null;
    var graded = rel.pass + rel.fail;
    var rate = graded ? Math.round((rel.pass / graded) * 1000) / 10 + '%' : null;
    return h('span', { class: 'tile-sub tile-release' }, [
      h('strong', { text: rate === null
        ? 'No release build ran here.'
        : 'Release builds only: ' + rate }),
      h('span', { text: rate === null
        ? ' Everything above is ' + entry.nonRelease.join(', ') + '.'
        : '  (' + rel.pass + ' passed · ' + rel.fail + ' failed). Above ' +
          'includes ' + entry.nonRelease.join(', ') + '.' })
    ]);
  }

  /* The verdicts of the rows that are showing.
   *
   * These used to come straight from the bundle, so filtering the table to one
   * build left the tile saying 61.5% over all 39 units — a number describing a
   * table nobody was looking at. Recomputed here from the same rows the body
   * renders, which is the only way the two can be guaranteed to agree.
   */
  function countsFor(tab, rows) {
    var out = {};
    var columns = tab.columns || [];
    Object.keys(tab.counts || {}).forEach(function (key) {
      var at = columnIndex(tab, key);
      var station = (columns[at] || {}).station;
      var versionAt = (columns[at + 1] || {}).kind === 'version' ? at + 1 : -1;
      var serialAt = columnIndex(tab, 'B');

      function tally() { return { pass: 0, fail: 0, blank: 0 }; }
      var every = tally(), everyRelease = tally();
      var fresh = tally(), freshRelease = tally();
      var nonRelease = [], returning = 0;

      rows.forEach(function (row) {
        var tone = (row[at] || {}).t;
        var bucket = (tone === 'pass' || tone === 'fail' || tone === 'abort')
          ? tone : 'blank';
        var isNew = !isReturning(row, serialAt, station);
        if (!isNew && bucket !== 'blank') returning += 1;

        every[bucket] += 1;
        if (isNew) fresh[bucket] += 1;

        var version = versionAt >= 0 ? (row[versionAt] || {}) : {};
        var build = version.v || '';
        if (build && NON_RELEASE.test(build)) {
          if (nonRelease.indexOf(build) === -1) nonRelease.push(build);
          /* The unit may still have run a release build earlier the same day;
           * count that verdict rather than dropping the unit. */
          var status = version.relStatus;
          if (status === 'pass' || status === 'fail') {
            everyRelease[status] += 1;
            if (isNew) freshRelease[status] += 1;
          }
          return;
        }
        everyRelease[bucket] += 1;
        if (isNew) freshRelease[bucket] += 1;
      });

      out[key] = {
        pass: every.pass, fail: every.fail, blank: every.blank,
        release: everyRelease, new: fresh, newRelease: freshRelease,
        returning: returning, nonRelease: nonRelease.sort(),
        lookback: (tab.counts[key] || {}).lookback || 10,
        title: (tab.counts[key] || {}).title,
        sub: subFor(tab, key, rows)
      };
    });
    return out;
  }

  /* Anything that is not a plain release build. Mirrors NON_RELEASE in
   * build_dailyexcel.py; the two must agree, and both are one expression. */
  var NON_RELEASE = /(^|_)debug|_dbg|validation/i;

  function isReturning(row, serialAt, station) {
    if (serialAt < 0 || !station) return false;
    var serial = row[serialAt] || {};
    return !!(serial.seen && serial.seen[station]);
  }

  /* Count new means completely new: no attempt at any station, anywhere in the
   * lookback window.
   *
   * The rule was "new at *any* station it ran that day", which kept a unit
   * that was returning to MLT and fresh to HTT. That unit then sat in Count
   * new carrying its MLT attempts in the Test History column — and a mode the
   * line reads as "today's fresh material" is not fresh material if the rows
   * in it have a history. One F1 on screen makes the whole population suspect,
   * which is the opposite of what the mode is for.
   *
   * The cost is real. The tiles judge each column on its own and are computed
   * from the unfiltered rows, so a day can headline an HTT yield over units
   * this table no longer lists: 08-16 showed 16 rows under the old rule and
   * shows none under this one. That is not a bug to fix by loosening the rule
   * back — the caption says how many were left out, the note under the table
   * says why, and Count all still shows every one of them. */
  function rowIsNew(tab, row) {
    var serialAt = columnIndex(tab, 'B');
    if (serialAt < 0) return true;
    var serial = row[serialAt] || {};
    return !Object.keys(serial.seen || {}).length;
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

  function renderSummary(tab, rows, els) {
    els = els || el;
    els.summary.innerHTML = '';

    /* Nothing about provenance here. The tile that used to open a derived
     * tab — first with its suite-run count, then with the caveats that
     * outlived it — is gone: the count answered no question anyone asks,
     * and each caveat is already said closer to the numbers it qualifies.
     * releaseOnly() prints the non-release builds on the station tile that
     * counted them, which is where a reader is looking when it matters, and
     * renderCaption names the source under every table. The strip now opens
     * on the yields. */

    /* The tiles below now describe the filtered set, so the filter has to be
     * visible beside them. A 100% tile with no note is the screenshot that
     * gets quoted as the day's yield. */
    if (filtered()) {
      var names = Object.keys(view.filters).map(function (key) {
        var at = columnIndex(tab, key);
        return (tab.columns[at] || {}).title || key;
      });
      els.summary.appendChild(h('div', { class: 'sheet-tile filtered' }, [
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
      var shownCounts = (countMode === 'new' && entry.new) ? entry.new : entry;
      var graded = shownCounts.pass + shownCounts.fail;
      /* The other population's figure, computed separately and shown beside
       * this one. Both are wanted daily and neither should need a button
       * press to read: the headline follows the mode, the second line is
       * always the other one. */
      var otherKey = countMode === 'new' ? 'all' : 'new';
      var other = countMode === 'new' ? entry : (entry.new || entry);
      var otherGraded = other.pass + other.fail;
      var rate = graded ? Math.round((shownCounts.pass / graded) * 1000) / 10 : null;
      els.summary.appendChild(h('div', { class: 'sheet-tile' }, [
        h('span', { class: 'tile-title' }, [
          document.createTextNode(entry.title),
          /* The build on its own line. One line of "MLT Results
           * mlt_validation_2026.225.0-gitb937ca2c" was wide enough to push the
           * failure column off the screen, and it is two facts anyway. */
          entry.sub ? h('span', { class: 'tile-build', text: entry.sub }) : null
        ]),
        h('strong', { class: 'tile-value', text: rate === null ? '—' : rate + '%' }),
        /* Passed and failed alone on the first line under the rate. They are
         * what the tile is read for, and they used to share a line with the
         * not-run count, the mode note and the other population's figure —
         * four facts reflowing into one grey paragraph in which the two that
         * matter were the hardest to pick out. Everything else sits below now,
         * one fact per line. */
        h('span', { class: 'tile-sub tile-verdicts' }, [
          h('span', { class: 'tone-pass', text: shownCounts.pass + ' passed' }),
          h('span', { text: ' · ' }),
          h('span', { class: 'tone-fail', text: shownCounts.fail + ' failed' })
        ]),
        /* Aborted before "not run", because they are opposite claims: one rack
           tried and gave up, the other never started. Both are the absence of a
           verdict, so they share a line under the verdicts — and the line is
           dropped rather than left empty when there is neither. */
        (shownCounts.abort || shownCounts.blank)
          ? h('span', { class: 'tile-sub tile-unrun' }, [
              shownCounts.abort
                ? h('span', { class: 'tone-abort',
                              text: shownCounts.abort + ' aborted' })
                : null,
              (shownCounts.abort && shownCounts.blank)
                ? h('span', { text: ' · ' })
                : null,
              shownCounts.blank
                ? h('span', { class: 'tile-blank',
                              text: shownCounts.blank + ' not run' })
                : null
            ])
          : null,
        h('span', { class: 'tile-sub tile-mode', text: countMode === 'new'
          ? 'new input only — ' + entry.returning + ' returning unit' +
            (entry.returning === 1 ? '' : 's') + ' left out'
          : 'every unit, including ' + entry.returning + ' returning' }),
        h('span', { class: 'tile-sub tile-other' }, [
          h('strong', { text: otherKey === 'all' ? 'All units: ' : 'New input: ' }),
          document.createTextNode(otherGraded
            ? (Math.round((other.pass / otherGraded) * 1000) / 10) + '%  (' +
              other.pass + ' passed · ' + other.fail + ' failed)'
            : 'nothing to count')
        ]),
        releaseOnly(entry)
      ]));
    });

    /* The tab name carries the line's own unit count. If it disagrees with the
     * rows present, the export is mid-edit or a row was dropped — say so. */
    if (tab.claimedUnits && tab.claimedUnits !== tab.rows.length &&
        rows.length === tab.rows.length) {
      els.summary.appendChild(h('div', { class: 'sheet-tile warn' }, [
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

  /* Which rows are showing, and why.
   *
   * Excel's Data/Filter, because that is what the line already knows: click a
   * heading, tick the values you want, sort from the same menu. The values
   * offered in one column are computed with the *other* columns' filters
   * already applied, so a menu never offers a value that would leave the table
   * empty — Excel does the same, and the alternative reads as a broken filter.
   */
  var view = { filters: {}, sort: null };

  /* Whether the table being drawn right now has a Test History column, so the
   * DUT SN cell knows not to repeat what that column already says. Set by
   * renderTable before its rows are built and read by renderCell inside the
   * same synchronous pass — the three tables on the page each set it for their
   * own rows. */
  var historyColumn = false;

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

  /* ----------------------------------------------------------- table zoom */

  /* The sheet is thirteen columns wide and stays wider than the screen. Until
   * now the only way to reach the HTT column was the horizontal scrollbar,
   * which the line reports as the single most awkward thing about reading this
   * page: in Excel you press a key and the whole table shrinks until you can
   * see it.
   *
   * So: one zoom for every table on the page, on the Excel gesture.
   *
   * WHY Cmd+Shift+± AND NOT Cmd+±
   * Cmd+± is the browser's own page zoom, and it already works — it shrinks
   * the tiles and the prose along with the table, which is sometimes what a
   * reader wants. Taking it over would remove that, and would also mean this
   * page fighting a shortcut every browser reserves. Cmd+Shift+± is the
   * gesture the line actually asked for, it is free, and it leaves the two
   * zooms independent: page zoom for everything, this for the tables.
   */

  //: Excel-ish stops. Not a free-running multiplier — a percentage that lands
  //: on a round number is one a reader can report back over Slack.
  var ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.5];
  var ZOOM_MIN = ZOOM_STEPS[0];
  var ZOOM_MAX = ZOOM_STEPS[ZOOM_STEPS.length - 1];

  /* Kept across reloads. Somebody who found the level at which their day fits
   * on one screen should not have to find it again every morning. */
  var ZOOM_STORE = 'factory.daily.zoom';

  var zoom = 1;

  function storedZoom() {
    try {
      var saved = parseFloat(window.localStorage.getItem(ZOOM_STORE));
      /* Anything outside the range is a value this code never wrote — a stale
       * key, a hand-edited store — and 100% is the safe reading of it. */
      return (saved >= ZOOM_MIN && saved <= ZOOM_MAX) ? saved : 1;
    } catch (err) {
      return 1;                    /* storage disabled or blocked; not fatal */
    }
  }

  function applyZoom() {
    document.documentElement.style.setProperty('--sheet-zoom', String(zoom));

    var level = byId('zoom-level');
    if (level) level.textContent = Math.round(zoom * 100) + '%';
    var group = level && level.parentNode;
    if (group) {
      group.className = 'zoom' + (Math.abs(zoom - 1) > 0.001 ? ' is-zoomed' : '');
    }
    /* A stepper that cannot step should say so rather than going quiet. */
    var out = byId('zoom-out'), into = byId('zoom-in');
    if (out) out.disabled = zoom <= ZOOM_MIN + 0.001;
    if (into) into.disabled = zoom >= ZOOM_MAX - 0.001;

    try { window.localStorage.setItem(ZOOM_STORE, String(zoom)); } catch (err) {}
  }

  function setZoom(next) {
    zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
    zoomNote('');
    applyZoom();
  }

  /* What the toolbar says when the answer is not simply the percentage. */
  function zoomNote(text) {
    var note = byId('zoom-note');
    if (!note) return;
    note.textContent = text;
    note.hidden = !text;
  }

  //: Which table a scroll box belongs to, for the note above.
  var TABLE_NAMES = {
    'sheet-table': 'the module table',
    'l10-table': 'the L10 table',
    'l11-table': 'the L11 table'
  };

  function stepZoom(direction) {
    var index;
    if (direction > 0) {
      for (index = 0; index < ZOOM_STEPS.length; index++) {
        if (ZOOM_STEPS[index] > zoom + 0.001) return setZoom(ZOOM_STEPS[index]);
      }
      return setZoom(ZOOM_MAX);
    }
    for (index = ZOOM_STEPS.length - 1; index >= 0; index--) {
      if (ZOOM_STEPS[index] < zoom - 0.001) return setZoom(ZOOM_STEPS[index]);
    }
    return setZoom(ZOOM_MIN);
  }

  /* Shrink until the widest table on the page fits its box.
   *
   * Measured at 100% rather than scaled from wherever the zoom happens to be:
   * the table carries min-width:100%, so at a zoom where it already fits,
   * scrollWidth equals clientWidth and a ratio taken there would say "you are
   * fitted" at every level. Reading the natural width first is the only
   * measurement that means anything.
   *
   * Not a mode. A later window resize does not re-fit — a zoom that moved on
   * its own while somebody was reading would be worse than one that is simply
   * where they left it. */
  function fitZoom() {
    setZoom(1);

    var scale = 1;
    var wraps = document.querySelectorAll('.sheet-wrap');
    for (var i = 0; i < wraps.length; i++) {
      var wrap = wraps[i];
      /* offsetParent is null for the L10/L11 blocks on a day that has none.
       * Measuring a hidden block returns zeroes and would fit to nothing. */
      if (wrap.offsetParent === null) continue;
      var room = wrap.clientWidth;          /* reading these forces the reflow */
      var need = wrap.scrollWidth;
      if (room > 0 && need > room) scale = Math.min(scale, room / need);
    }
    /* Floor rather than round, so the last column lands inside the box instead
     * of one pixel outside it with a scrollbar to prove it. */
    setZoom(Math.floor(scale * 100) / 100);

    /* 50% is the floor because 50% of 13px is the smallest this table has any
     * business being, and the widest one on the page — L10, nineteen columns —
     * needs 44% at a full-screen window and 33% at a narrow one. So Fit width
     * cannot always fit, and when it cannot it says which table is still short
     * rather than leaving somebody to wonder why the scrollbar survived a
     * button labelled Fit. Page zoom stacks on top of this if they need it. */
    var worst = null, over = 0;
    var after = document.querySelectorAll('.sheet-wrap');
    for (var j = 0; j < after.length; j++) {
      if (after[j].offsetParent === null) continue;
      var short = after[j].scrollWidth - after[j].clientWidth;
      if (short > over) {
        over = short;
        worst = (after[j].querySelector('table') || {}).id;
      }
    }
    if (over > 1) {
      zoomNote((TABLE_NAMES[worst] || 'one table') + ' still scrolls \u2014 ' +
               Math.round(ZOOM_MIN * 100) + '% is as small as these go');
    }
  }

  function bindZoom() {
    var out = byId('zoom-out'), into = byId('zoom-in');
    var fit = byId('zoom-fit'), reset = byId('zoom-reset');
    if (out) out.addEventListener('click', function () { stepZoom(-1); });
    if (into) into.addEventListener('click', function () { stepZoom(1); });
    if (fit) fit.addEventListener('click', fitZoom);
    if (reset) reset.addEventListener('click', function () { setZoom(1); });

    document.addEventListener('keydown', function (event) {
      if (!(event.metaKey || event.ctrlKey) || !event.shiftKey || event.altKey) {
        return;
      }
      /* event.code is the physical key, so this survives the layouts where +
       * and - are not where a US keyboard puts them; event.key is the fallback
       * for the shifted characters those layouts produce. */
      var code = event.code || '';
      var key = event.key || '';
      var smaller = code === 'Minus' || code === 'NumpadSubtract' ||
                    key === '_' || key === '-';
      var bigger = code === 'Equal' || code === 'NumpadAdd' ||
                   key === '+' || key === '=';
      var back = code === 'Digit0' || code === 'Numpad0' ||
                 key === '0' || key === ')';
      if (!smaller && !bigger && !back) return;

      event.preventDefault();
      if (back) setZoom(1);
      else stepZoom(bigger ? 1 : -1);
    });

    zoom = storedZoom();
    applyZoom();
  }

  /* ---------------------------------------------------------------- table */

  function renderTable(tab, els) {
    els = els || el;
    var columns = tab.columns || [];
    /* Everything the column filters left — the tiles are computed from this,
     * so switching the count mode never changes what the filters selected. */
    var counted = shownRows(tab);
    /* What the table draws. New input only by default: the day's question is
     * how the fresh material did, and a re-run from last week answers a
     * different one. */
    var rows = countMode === 'new'
      ? counted.filter(function (row) { return rowIsNew(tab, row); })
      : counted;

    var head = h('tr', {});
    /* A row number, not a data column: it counts what is showing, so after a
     * filter the last number is the answer to "how many". */
    head.appendChild(h('th', { scope: 'col', class: 'col-index', text: '#' }));

    /* The column follows the data, not the mode.
     *
     * It was drawn only in Count all, on the assumption that Count new has no
     * returning units to put in it. That is wrong: a row is kept as new input
     * when it is new at *any* station, so on 08-16 all sixteen shown rows are
     * returning to MLT and fresh to HTT — their earlier attempts existed, and
     * the one column that shows them was the one the mode had switched off.
     * Now: if anything on screen has a history, the column is there. */
    var showHistory = rows.some(function (row) {
      var serial = row[columnIndex(tab, 'B')] || {};
      return !!(serial.history && Object.keys(serial.history).length);
    });
    historyColumn = showHistory;

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
      if (showHistory && column.key === 'B') {
        head.appendChild(h('th', { scope: 'col', class: 'col-history' }, [
          h('span', { class: 'col-head' }, [
            h('span', { class: 'col-name', text: 'Test History' })
          ]),
          h('span', { class: 'col-build',
                      text: 'earlier attempts at this station' })
        ]));
      }
    });
    els.head.innerHTML = '';
    els.head.appendChild(head);

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
        var column = columns[position];
        if (showHistory && column && column.key === 'B') {
          /* One serial, one column — always.
           *
           * The serial used to move into a second column when the unit was a
           * returning one, which put the day's units under two headings: to
           * read "which units ran today" you had to scan down both, and the
           * DUT SN column sat empty on every returning row. Now DUT SN holds
           * every serial in both count modes, and the column beside it holds
           * what varies — the attempts that unit already made here. */
          tr.appendChild(renderCell(cell, column, wraps[position]));
          tr.appendChild(historyCell(cell));
          return;
        }
        var td = renderCell(cell, column, wraps[position]);
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
    els.body.innerHTML = '';
    els.body.appendChild(body);

    renderSummary(tab, counted, els);
    renderCaption(tab, rows.length, els);
    renderCountMode(tab, counted.length - rows.length, els);
  }

  /* The switch, under the table where the rows it is talking about are.
   *
   * Stated rather than implied: a reader who sees 76.1% needs to know it is
   * 33 of 43 fresh units and not 51 of 67 rows, and the two are different
   * enough to argue about. */
  function renderCountMode(tab, hidden, els) {
    els = els || el;
    var host = byId(els.countMode);
    if (!host) return;
    host.innerHTML = '';

    var counts = countsFor(tab, shownRows(tab));
    var returning = 0, lookback = 10;
    Object.keys(counts).forEach(function (key) {
      returning = Math.max(returning, counts[key].returning || 0);
      lookback = counts[key].lookback || lookback;
    });

    /* The label is what pressing it does, not what the page is doing. A
     * button that names the current state reads as a status line, and half
     * the room presses it expecting the opposite. */
    var button = h('button', { type: 'button', class: 'cm-btn',
      text: countMode === 'new' ? 'Count all' : 'Count new' });
    button.addEventListener('click', function () {
      countMode = countMode === 'new' ? 'all' : 'new';
      renderTable(tab, els);
      if (els === el) { renderL10(current); renderL11(current); }
    });
    host.appendChild(button);

    /* On a hand-kept tab the two modes agree, and that is worth a sentence
     * rather than leaving a reader to wonder whether the button works. */
    var omits = tab.sheetOmits;
    if (omits && Object.keys(omits).length) {
      var parts = Object.keys(omits).map(function (station) {
        var o = omits[station];
        return station.toUpperCase() + ': ' + o.units + ' of ' + o.ranThatDay +
          (o.returning === o.units
            ? ', every one of them a returning unit'
            : ', ' + o.returning + ' of them returning');
      });
      host.appendChild(h('p', { class: 'cm-note cm-sheet' }, [
        h('strong', { text: 'Both modes agree on this tab.' }),
        document.createTextNode(
          ' It is the line\u2019s own sheet, not a rebuild, and the sheet ' +
          'already leaves the re-runs out — ' + parts.join('; ') +
          '. So there is nothing for Count all to add: the line was keeping a ' +
          'new-input record by hand before this page counted one.')
      ]));
    }

    host.appendChild(h('p', { class: 'cm-note' }, [
      h('strong', { text: countMode === 'new'
        ? 'Counting new input only.' : 'Counting every unit.' }),
      document.createTextNode(countMode === 'new'
        ? ' The table is units with no earlier attempt at any station in the ' +
          'previous ' + lookback + ' days — completely new material, so every ' +
          'Test History cell in it is empty. ' + hidden + ' unit' +
          (hidden === 1 ? '' : 's') + ' with a history ' +
          (hidden === 1 ? 'is' : 'are') + ' left out, because a unit that ' +
          'failed last week and is re-run today says whether a fix worked — ' +
          'not how today’s build went. The tiles still judge each column on ' +
          'its own and carry both yields, so a tile can count a unit this ' +
          'table leaves out. Press Count all to see them, each with its ' +
          'earlier attempts as F1 P2 — F failed, P passed, numbered from the ' +
          'unit’s first visit, each one a link to that run.'
        : ' Every row is in the table and in the figures, new material and ' +
          're-runs together. That is the day’s whole workload, and it is not ' +
          'a build yield: ' + returning + ' of these units had already been ' +
          'through this station within ' + lookback + ' days, and the Test ' +
          'History column beside each serial links every earlier attempt — ' +
          'F1 is the first attempt and it failed, P2 the second and it ' +
          'passed. Press Count new for the fresh material on its own.')
    ]));
  }

  function renderCaption(tab, showing, els) {
    els = els || el;
    var total = (tab.rows || []).length;
    var source = tab.derived
      ? (tab.day || tab.label) + ', rebuilt from ' +
        (((tab.derivedFrom || {}).source === 'pega3') ? 'pega3' : 'EOS')
      : (tab.day || tab.label) + ', as recorded by the line';

    els.caption.innerHTML = '';
    if (showing === total) {
      els.caption.appendChild(document.createTextNode(
        total + ' units — ' + source));
      return;
    }

    /* A filtered table that does not say so is a table someone will screenshot
     * and quote as the day's total. */
    els.caption.appendChild(h('strong', { class: 'cap-filtered',
      text: showing + ' of ' + total + ' units' }));
    els.caption.appendChild(document.createTextNode(' — ' + source + ' · '));
    var reset = h('button', { type: 'button', class: 'cap-reset',
                              text: 'clear filters' });
    reset.addEventListener('click', function () {
      view.filters = {};
      renderTable(tab);
    });
    els.caption.appendChild(reset);
  }

  /* What this unit already did here, one link per prior attempt.
   *
   * F1 is the first attempt and it failed; P2 is the second and it passed.
   * The letter is the verdict and the number is which attempt, counted from
   * the unit's first — so F7 means the seventh, not the seventh of the ones
   * that fit on the row. Each opens that run on the controller, which is what
   * makes "this unit has been here four times" checkable rather than a claim.
   *
   * Empty for a unit on its first visit. The cell is a blank, not a dash: a
   * dash would read as a missing value, and "no earlier attempt" is the
   * ordinary case, not a gap.
   */
  function historyCell(cell) {
    var td = h('td', { class: 'history' });
    var history = cell.history || {};
    Object.keys(history).forEach(function (station) {
      var line = h('span', { class: 'rt-line' });
      line.appendChild(h('span', { class: 'rt-station',
                                   text: station.toUpperCase() }));
      history[station].forEach(function (attempt) {
        var mark = (attempt.status === 'pass' ? 'P' : 'F') + attempt.n;
        var chip = attempt.url
          ? h('a', { class: 'rt-att a-' + attempt.status, href: attempt.url,
                     target: '_blank', rel: 'noopener noreferrer',
                     title: attempt.day + ' · ' + attempt.status + ' · ' +
                            (attempt.suite || '') +
                            '  (pega3 asks for an ESVM login)' })
          : h('span', { class: 'rt-att a-' + attempt.status,
                        title: attempt.day + ' · ' + attempt.status });
        chip.appendChild(document.createTextNode(mark));
        line.appendChild(chip);
      });
      /* The date of the last of them, in the open. The chips carry it in a
       * tooltip, and "when was this unit last here" is the question the
       * column is most often read for — too common to make anyone hover. */
      var last = history[station][history[station].length - 1];
      if (last && last.day) {
        line.appendChild(h('span', { class: 'rt-when', text: last.day }));
      }
      td.appendChild(line);
    });
    return td;
  }

  function renderCell(cell, column, wrap) {
    var td = h('td', {});
    var classes = [];
    if (cell.t) classes.push('tone-' + cell.t);
    if (wrap) classes.push('wrap');
    if (column && column.key === 'B') classes.push('serial');
    if (column && column.key === 'B' && cell.seen) classes.push('was-here');
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

    /* How many times the rack went through this stage today. L11 is retried
     * hard during bring-up — six attempts on one rack in an afternoon — and a
     * cell showing only the last verdict makes that look like one quiet
     * test. Only L11 sets it. */
    if (cell.tries > 1) {
      td.appendChild(h('span', {
        class: 'tries', title: cell.tries + ' attempts at this stage today; ' +
                               'the verdict shown is the last one'
      }, [document.createTextNode('\u00d7' + cell.tries)]));
    }

    /* When a returning unit was last at this station. Without it "returning"
     * is an assertion the reader has to take on trust.
     *
     * Not here when the Test History column is drawn: it stands immediately
     * to the right carrying the same station and the same date, and printing
     * it twice buys nothing while making DUT SN something other than a column
     * of serials. */
    if (column && column.key === 'B' && cell.seen && !historyColumn) {
      var days = Object.keys(cell.seen).map(function (station) {
        return station.toUpperCase() + ' ' + cell.seen[station];
      });
      td.appendChild(h('span', { class: 'seen-when',
                                 text: 'last here ' + days.join(', ') }));
    }
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

  /* L10 under the module table, from the day it started testing.
   *
   * The same renderer, pointed at a second set of elements: the two tables
   * have to behave identically — the same filters, the same Count all, the
   * same F1 P2 traces — and a second implementation would drift within a
   * week. What it does not share is the subject. A chassis is not a module,
   * one chassis holds many of them, and a row carrying both would have
   * nothing to be about.
   */
  function renderL10(tab) {
    var block = byId('l10-block');
    if (!block) return;
    var l10 = tab && tab.l10;
    if (!l10 || !(l10.rows || []).length) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    /* Chassis and controller. The suite-run count that used to sit between
     * them is gone here for the same reason it left the tile above: it is
     * not how anyone reads a day. */
    byId('l10-sub').textContent = l10.rows.length + ' chassis · pega4';
    renderTable(l10, {
      summary: byId('l10-summary'), head: byId('l10-head'),
      body: byId('l10-body'), caption: byId('l10-caption'),
      countMode: 'l10-count-mode'
    });
  }

  /* L11 under L10, from the day the line asked for it. Third table, third
   * subject: a module, a chassis, a rack. */
  function renderL11(tab) {
    var block = byId('l11-block');
    if (!block) return;
    var l11 = tab && tab.l11;
    if (!l11 || !(l11.rows || []).length) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    byId('l11-sub').textContent = l11.rows.length + ' rack' +
      (l11.rows.length === 1 ? '' : 's') + ' · pega5';
    renderTable(l11, {
      summary: byId('l11-summary'), head: byId('l11-head'),
      body: byId('l11-body'), caption: byId('l11-caption'),
      countMode: 'l11-count-mode'
    });
  }

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
    renderL10(current);            /* and L10 under it, where the day has any */
    renderL11(current);            /* and L11 under that */
    document.title = 'Daily tracker — ' + (current.day || current.label);
  }

  function init() {
    el.tabbar = byId('tabbar');
    el.summary = byId('summary');
    el.head = byId('sheet-head');
    el.body = byId('sheet-body');
    el.caption = byId('sheet-caption');
    el.countMode = 'count-mode';

    if (!TABS.length) {
      var banner = byId('notice');
      banner.hidden = false;
      banner.textContent =
        'No tracker data. Export the sheet to daily/ and run `make dailyexcel`.';
      return;
    }

    bindZoom();
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
