/* Excel-style column filtering and sorting, for any table on any page.
 *
 * WHY THIS IS SHARED
 * The daily tracker grew this first (dailysheet.js) and the line learned it
 * there: click a heading, tick the values you want, sort from the same menu.
 * When the customize page needed the same thing for its Result column, the
 * choice was a second copy or one engine. A second copy is a second set of
 * keyboard handling, a second menu that closes on scroll but not on resize,
 * and a second thing to fix twice. This is the engine; the styling it expects
 * is colfilter.css.
 *
 * WHAT A CALLER PROVIDES
 * A column is `{ key, title, value(row) }` — `value` returns the cell's text,
 * because only the caller knows how to get it out of its own row shape. That
 * is the whole coupling: this file never looks inside a row.
 *
 *   var filter = ColFilter.create({ onChange: render });
 *   var shown  = filter.rows(allRows, columns);   // filtered, then sorted
 *   filter.head(th, column, columns, allRows);    // the arrow, on one heading
 *
 * `rows` is given every row, not the ones already on screen: a menu offers the
 * values that are *available*, which it cannot know from a list already cut
 * down to what is showing.
 */
window.ColFilter = (function () {
  'use strict';

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, attrs[key]);
      }
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  function label(value) { return value === '' ? '(blank)' : value; }

  /* Serials, dates and run ids all sort wrongly as plain strings — 10 before
     9 — so digits inside the text are compared as numbers. */
  function compare(left, right) {
    if (left === right) return 0;
    if (left === '') return 1;            /* blanks last, filtered or not */
    if (right === '') return -1;
    return left.localeCompare(right, undefined, { numeric: true });
  }

  /* One menu at a time, for the whole document: two panels open over each
     other is never what a click meant. */
  var openPanel = null;

  function closeMenu() {
    if (openPanel && openPanel.parentNode) {
      openPanel.parentNode.removeChild(openPanel);
    }
    openPanel = null;
  }

  document.addEventListener('click', function (event) {
    if (!openPanel) return;
    if (openPanel.contains(event.target)) return;
    if (event.target.closest && event.target.closest('.col-filter')) return;
    closeMenu();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeMenu();
  });
  window.addEventListener('resize', closeMenu);

  function create(options) {
    var onChange = (options || {}).onChange || function () {};
    var view = { filters: {}, sort: null };

    function textOf(column, row) {
      var value = column.value(row);
      return value === null || value === undefined ? '' : String(value);
    }

    function keep(row, columns, skipKey) {
      for (var i = 0; i < columns.length; i++) {
        var allowed = view.filters[columns[i].key];
        if (!allowed || columns[i].key === skipKey) continue;
        if (allowed.indexOf(textOf(columns[i], row)) === -1) return false;
      }
      return true;
    }

    /* The values one column can offer, counted with the *other* columns'
       filters already applied — so a menu never offers a value that would
       leave the table empty. Excel does the same, and the alternative reads
       as a broken filter. */
    function valuesFor(all, columns, column) {
      var counts = {};
      all.forEach(function (row) {
        if (!keep(row, columns, column.key)) return;
        var value = textOf(column, row);
        counts[value] = (counts[value] || 0) + 1;
      });
      return Object.keys(counts).sort(compare).map(function (value) {
        return { value: value, count: counts[value] };
      });
    }

    function rows(all, columns) {
      var out = (all || []).filter(function (row) {
        return keep(row, columns, null);
      });
      if (!view.sort) return out;
      var column = null;
      columns.forEach(function (entry) {
        if (entry.key === view.sort.key) column = entry;
      });
      if (!column) return out;
      var direction = view.sort.dir === 'desc' ? -1 : 1;
      /* Decorate with the original position so equal values keep the caller's
         order instead of whatever the engine's sort does with ties. */
      return out.map(function (row, at) { return [row, at]; })
        .sort(function (a, b) {
          var by = compare(textOf(column, a[0]), textOf(column, b[0]));
          return by ? by * direction : a[1] - b[1];
        })
        .map(function (pair) { return pair[0]; });
    }

    function openMenu(all, columns, column, anchor) {
      closeMenu();
      var values = valuesFor(all, columns, column);
      var chosen = view.filters[column.key];
      var picked = {};
      values.forEach(function (entry) {
        picked[entry.value] = !chosen || chosen.indexOf(entry.value) !== -1;
      });

      var menu = h('div', { class: 'filter-menu', role: 'dialog',
                            'aria-label': 'Filter ' + column.title });
      menu.appendChild(h('div', { class: 'fm-head', text: column.title }));

      function sortButton(text, dir) {
        var button = h('button', { type: 'button', class: 'fm-sort',
                                   text: text });
        if (view.sort && view.sort.key === column.key
            && view.sort.dir === dir) {
          button.className += ' on';
        }
        button.addEventListener('click', function () {
          view.sort = { key: column.key, dir: dir };
          closeMenu();
          onChange();
        });
        return button;
      }
      menu.appendChild(h('div', { class: 'fm-sorts' }, [
        sortButton('Sort A → Z', 'asc'),
        sortButton('Sort Z → A', 'desc')
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
          if (item.row.hidden) return;    /* only what the search is showing */
          item.box.checked = state;
          picked[item.entry.value] = state;
        });
      }

      var apply = h('button', { type: 'button', class: 'fm-apply',
                                text: 'Apply' });
      apply.addEventListener('click', function () {
        var allowed = values.filter(function (entry) {
          return picked[entry.value];
        }).map(function (entry) { return entry.value; });
        if (allowed.length === values.length) delete view.filters[column.key];
        else view.filters[column.key] = allowed;
        closeMenu();
        onChange();
      });

      var clear = h('button', { type: 'button', class: 'fm-clear',
                                text: 'Clear' });
      clear.addEventListener('click', function () {
        delete view.filters[column.key];
        closeMenu();
        onChange();
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
      openPanel = menu;
      var box = anchor.getBoundingClientRect();
      var width = menu.offsetWidth;
      /* Anchored to the heading, nudged back inside the viewport rather than
         hanging off the right edge on the last column. */
      var left = Math.min(box.left, window.innerWidth - width - 12);
      menu.style.left = Math.max(8, left) + 'px';
      menu.style.top = (box.bottom + 4) + 'px';
      search.focus();
    }

    /* Turn a plain <th> into a filterable heading. The caller has already put
       the title in it; this adds the arrow and the state classes. */
    function head(th, column, columns, all) {
      var isFiltered = !!view.filters[column.key];
      var isSorted = !!(view.sort && view.sort.key === column.key);
      if (isFiltered) th.className += ' is-filtered';
      if (isSorted) th.className += ' is-sorted';

      var arrow = isSorted
        ? (view.sort.dir === 'desc' ? '▲' : '▼')
        : '▼';
      var button = h('button', {
        type: 'button', class: 'col-filter', text: arrow,
        'aria-label': 'Filter or sort ' + column.title,
        title: isFiltered ? 'Filtered — click to change'
                          : 'Filter or sort this column'
      });
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        openMenu(all, columns, column, th);
      });
      th.appendChild(button);
      return th;
    }

    return {
      rows: rows,
      head: head,
      active: function () { return Object.keys(view.filters).length > 0; },
      sorted: function () { return !!view.sort; },
      /* Which values one column is pinned to, so a caller can describe the
         view in prose or seed it from a URL. */
      filterFor: function (key) { return view.filters[key] || null; },
      setFilter: function (key, allowed) {
        if (!allowed || !allowed.length) delete view.filters[key];
        else view.filters[key] = allowed.slice();
      },
      clear: function () { view.filters = {}; view.sort = null; },
      close: closeMenu
    };
  }

  return { create: create };
}());
