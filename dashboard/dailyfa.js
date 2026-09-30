/* Daily FA: the daily tracker's month calendar, then FAT / SFT / RIN reports.

   The calendar is the same control as dailyexcel.html — days with a tab are
   clickable, empty/future/before-floor days are not. Nothing else from the
   tracker (module table, L10/L11 tables, zoom, count mode) is on this page.
*/
(function () {
  'use strict';

  var DATA = window.__FACTORY_DAILY_EXCEL__ || {};
  var TABS = DATA.tabs || [];
  var current = null;
  var calMonth = null;

  var CAL_FLOOR = '2026-08-01';
  var DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];

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

  function hashDay() {
    var match = /day=([0-9-]+)/.exec(location.hash || '');
    return match ? match[1] : null;
  }

  function pick(day) {
    for (var i = 0; i < TABS.length; i++) {
      if (TABS[i].day === day) return TABS[i];
    }
    return TABS.length ? TABS[TABS.length - 1] : null;
  }

  function iso(y, m, d) {
    return y + '-' + (m < 9 ? '0' : '') + (m + 1) + '-' + (d < 10 ? '0' : '') + d;
  }

  function todayKey() {
    var now = new Date();
    return iso(now.getFullYear(), now.getMonth(), now.getDate());
  }

  function tabFor(day) {
    for (var i = 0; i < TABS.length; i++) if (TABS[i].day === day) return TABS[i];
    return null;
  }

  function renderTabs() {
    var host = byId('daycal');
    if (!host) return;
    if (!calMonth) {
      var anchor = (current && current.day) || todayKey();
      calMonth = { y: +anchor.slice(0, 4), m: +anchor.slice(5, 7) - 1 };
    }
    host.innerHTML = '';

    var today = todayKey();
    var floorY = +CAL_FLOOR.slice(0, 4), floorM = +CAL_FLOOR.slice(5, 7) - 1;
    var atFloor = calMonth.y === floorY && calMonth.m === floorM;
    var atToday = calMonth.y === +today.slice(0, 4) &&
                  calMonth.m === +today.slice(5, 7) - 1;

    var head = h('div', { class: 'cal-head' }, [
      h('h2', { class: 'cal-title' }, [
        h('strong', { text: MONTHS[calMonth.m] }),
        document.createTextNode(' ' + calMonth.y)
      ])
    ]);
    var nav = h('div', { class: 'cal-nav' });
    nav.appendChild(calStep('\u2039', 'Previous month', atFloor, -1));
    var todayBtn = h('button', { type: 'button', class: 'cal-today',
                                 text: 'Today' });
    todayBtn.disabled = atToday;
    todayBtn.addEventListener('click', function () {
      calMonth = { y: +today.slice(0, 4), m: +today.slice(5, 7) - 1 };
      renderTabs();
    });
    nav.appendChild(todayBtn);
    nav.appendChild(calStep('\u203a', 'Next month', atToday, 1));
    head.appendChild(nav);
    host.appendChild(head);

    var grid = h('div', { class: 'cal-grid', role: 'grid' });
    DOW.forEach(function (name) {
      grid.appendChild(h('span', { class: 'cal-dow', text: name }));
    });

    var first = new Date(calMonth.y, calMonth.m, 1);
    var lead = first.getDay();
    var length = new Date(calMonth.y, calMonth.m + 1, 0).getDate();
    for (var blank = 0; blank < lead; blank++) {
      grid.appendChild(h('span', { class: 'cal-cell cal-pad' }));
    }
    for (var d = 1; d <= length; d++) {
      var key = iso(calMonth.y, calMonth.m, d);
      grid.appendChild(calCell(key, d, today));
    }
    host.appendChild(grid);
  }

  function calStep(glyph, label, disabled, delta) {
    var btn = h('button', { type: 'button', class: 'cal-step',
                            'aria-label': label, title: label, text: glyph });
    btn.disabled = !!disabled;
    btn.addEventListener('click', function () {
      var m = calMonth.m + delta, y = calMonth.y;
      if (m < 0) { m = 11; y -= 1; }
      if (m > 11) { m = 0; y += 1; }
      calMonth = { y: y, m: m };
      renderTabs();
    });
    return btn;
  }

  function calCell(key, number, today) {
    var tab = tabFor(key);
    var future = key > today;
    var before = key < CAL_FLOOR;
    var classes = ['cal-cell'];
    var why = '';

    if (tab) {
      classes.push('has-data');
      if (current && current.day === key) classes.push('is-on');
    } else if (future) {
      classes.push('is-future');
      why = 'Not yet — ' + key;
    } else if (before) {
      classes.push('is-before');
      why = 'Before the tracker starts (' + CAL_FLOOR + ')';
    } else {
      classes.push('is-empty');
      why = 'No runs recorded on ' + key;
    }

    if (!tab) {
      return h('span', {
        class: classes.join(' '), title: why, 'aria-disabled': 'true'
      }, [h('span', { class: 'cal-n', text: String(number) })]);
    }

    var units = tab.units != null ? tab.units : (tab.rows || []).length;
    var cell = h('button', {
      type: 'button', class: classes.join(' '),
      'aria-pressed': (current && current.day === key) ? 'true' : 'false',
      title: key + ' — ' + units + ' unit' + (units === 1 ? '' : 's')
    }, [
      h('span', { class: 'cal-n', text: String(number) }),
      h('span', { class: 'cal-units', text: units + 'u' })
    ]);
    cell.addEventListener('click', function () { location.hash = 'day=' + key; });
    return cell;
  }

  function stampMeta() {
    var meta = byId('meta');
    var build = byId('build');
    if (meta) {
      var at = DATA.generatedAt || '';
      meta.textContent = at ? ('Data ' + at.replace('T', ' ').replace(/\+00:00$/, 'Z')) : '';
    }
    if (build && DATA.build) {
      build.textContent = DATA.build.release || DATA.build.commit || '';
    }
  }

  function show() {
    current = pick(hashDay());
    if (!current) return;
    renderTabs();
    stampMeta();
    if (window.FaReport) window.FaReport.render(current);
    else if (window.SftReport) window.SftReport.render(current);
    document.title = 'Daily FA — ' + (current.day || current.label);
  }

  function init() {
    if (!TABS.length) {
      var banner = byId('notice');
      banner.hidden = false;
      banner.textContent =
        'No tracker data. Rebuild on a laptop that can reach pega, then copy ' +
        'dashboard/data/dailyexcel.js onto this host.';
      return;
    }
    window.addEventListener('hashchange', show);
    show();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
