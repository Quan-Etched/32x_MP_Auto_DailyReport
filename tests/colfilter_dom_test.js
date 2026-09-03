/* dashboard/colfilter.js under JavaScriptCore, driven like a reader drives it.
 *
 * WHY A HARNESS THAT RECORDS LISTENERS
 * trace_dom_harness.js stubs addEventListener to a no-op, which is enough for a
 * module that only renders. This one is all behaviour: the menu exists to be
 * opened, ticked and applied, and a test that never fires a handler would pass
 * against a panel with every button dead. So handlers are kept and invoked.
 */
var ROOT = (typeof ROOT === 'string') ? ROOT : '.';

var FAILURES = 0;
function ok(name, cond, extra) {
  if (cond) { print('ok   ' + name); }
  else { FAILURES += 1; print('FAIL ' + name + (extra ? ' — ' + extra : '')); }
}
function eq(name, got, want) {
  ok(name, JSON.stringify(got) === JSON.stringify(want),
     'got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
}

/* ----------------------------------------------------------------- the DOM */

function El(tag) {
  this.tagName = String(tag).toUpperCase();
  this.children = [];
  this.attrs = {};
  this.style = {};
  this.listeners = {};
  this.textContent = '';
  this.className = '';
  this.checked = false;
  this.value = '';
  this.hidden = false;
  this.parentNode = null;
  this.offsetWidth = 300;
}
El.prototype.appendChild = function (kid) {
  this.children.push(kid); kid.parentNode = this; return kid;
};
El.prototype.removeChild = function (kid) {
  var at = this.children.indexOf(kid);
  if (at >= 0) this.children.splice(at, 1);
  kid.parentNode = null;
  return kid;
};
/* A real DOM keeps the `class` attribute and .className as one value, and
   colfilter.js sets some classes one way and appends to others the other way.
   A stub that kept them apart would fail to find its own buttons. */
El.prototype.setAttribute = function (k, v) {
  this.attrs[k] = v;
  if (k === 'class') this.className = v;
};
El.prototype.getAttribute = function (k) { return this.attrs[k]; };
El.prototype.addEventListener = function (kind, fn) {
  (this.listeners[kind] || (this.listeners[kind] = [])).push(fn);
};
El.prototype.fire = function (kind, event) {
  (this.listeners[kind] || []).forEach(function (fn) { fn(event || {}); });
};
El.prototype.focus = function () {};
El.prototype.getBoundingClientRect = function () {
  return { left: 10, right: 90, top: 10, bottom: 30, width: 80, height: 20 };
};
El.prototype.contains = function (node) {
  if (node === this) return true;
  for (var i = 0; i < this.children.length; i++) {
    if (this.children[i].contains(node)) return true;
  }
  return false;
};
El.prototype.matches = function (selector) {
  var want = selector.replace(/^\./, '');
  return (' ' + this.className + ' ').indexOf(' ' + want + ' ') !== -1;
};
El.prototype.closest = function (selector) {
  var at = this;
  while (at) { if (at.matches && at.matches(selector)) return at; at = at.parentNode; }
  return null;
};
El.prototype.querySelector = function (selector) {
  for (var i = 0; i < this.children.length; i++) {
    var kid = this.children[i];
    if (kid.matches(selector)) return kid;
    var deep = kid.querySelector(selector);
    if (deep) return deep;
  }
  return null;
};
El.prototype.querySelectorAll = function (selector) {
  var out = [];
  this.children.forEach(function (kid) {
    if (kid.matches(selector)) out.push(kid);
    out = out.concat(kid.querySelectorAll(selector));
  });
  return out;
};
El.prototype.text = function () {
  var out = this.textContent || '';
  for (var i = 0; i < this.children.length; i++) out += ' ' + this.children[i].text();
  return out;
};

var document = {
  body: new El('body'),
  listeners: {},
  createElement: function (tag) { return new El(tag); },
  addEventListener: function (kind, fn) {
    (this.listeners[kind] || (this.listeners[kind] = [])).push(fn);
  },
  fire: function (kind, event) {
    (this.listeners[kind] || []).forEach(function (fn) { fn(event || {}); });
  }
};
var window = {
  innerWidth: 1400,
  addEventListener: function () {},
  document: document
};

load(ROOT + '/dashboard/colfilter.js');
var ColFilter = window.ColFilter;
ok('the module publishes ColFilter.create', typeof ColFilter.create === 'function');

/* ------------------------------------------------------------- the fixture */

/* Three units at one station: one clean pass, one that failed then passed, one
 * that only ever failed. The same shape customize.js hands it. */
var ROWS = [
  { day: '2026-09-01', dut: 'A1', status: 'pass', result: 'Pass' },
  { day: '2026-09-01', dut: 'B2', status: 'fail', result: 'Retest Pass' },
  { day: '2026-09-02', dut: 'B2', status: 'pass', result: 'Retest Pass' },
  { day: '2026-09-02', dut: 'C3', status: 'fail', result: 'Bonepile' },
  { day: '2026-09-10', dut: 'D4', status: 'fail', result: '' }
];
var COLUMNS = [
  { key: 'Day_UTC', title: 'Day_UTC', value: function (r) { return r.day; } },
  { key: 'DUT_SN', title: 'DUT_SN', value: function (r) { return r.dut; } },
  { key: 'Status', title: 'Status', value: function (r) { return r.status; } },
  { key: 'Result', title: 'Result', value: function (r) { return r.result; } }
];

var renders = 0;
var filter = ColFilter.create({ onChange: function () { renders += 1; } });

function results(rows) {
  return rows.map(function (r) { return r.dut + ':' + r.result; });
}

/* ------------------------------------------------------- unfiltered, unsorted */

eq('every row passes through when nothing is set',
   results(filter.rows(ROWS, COLUMNS)),
   ['A1:Pass', 'B2:Retest Pass', 'B2:Retest Pass', 'C3:Bonepile', 'D4:']);
ok('and it reports itself inactive', filter.active() === false);

/* ------------------------------------------------------------- open the menu */

function openMenuOn(key) {
  var column = COLUMNS.filter(function (c) { return c.key === key; })[0];
  var th = new El('th');
  filter.head(th, column, COLUMNS, ROWS);
  var arrow = th.querySelector('.col-filter');
  ok('the ' + key + ' heading grew an arrow', !!arrow);
  arrow.fire('click', { stopPropagation: function () {} });
  var menu = document.body.children[document.body.children.length - 1];
  ok('the ' + key + ' menu is on the page', menu && menu.className === 'filter-menu');
  return menu;
}

var menu = openMenuOn('Result');

/* The values it offers, with counts — this is what a reader picks from. */
var listed = menu.querySelector('.fm-list').children.map(function (row) {
  return row.querySelector('.fm-value').textContent + '=' +
         row.querySelector('.fm-count').textContent;
});
eq('it offers every Result with its count, blanks last',
   listed, ['Bonepile=1', 'Pass=1', 'Retest Pass=2', '(blank)=1']);

/* --------------------------------------------------------- tick and apply */

/* Keep Bonepile only: untick everything, then tick the one row wanted. */
menu.querySelector('.fm-none').fire('click');
var boxes = menu.querySelector('.fm-list').children;
boxes.forEach(function (row) {
  if (row.querySelector('.fm-value').textContent === 'Bonepile') {
    var box = row.children[0];
    box.checked = true;
    box.fire('change');
  }
});
menu.querySelector('.fm-apply').fire('click');

ok('applying redrew the table', renders === 1);
ok('the menu closed behind it', document.body.children.length === 0);
eq('only the Bonepile rows survive',
   results(filter.rows(ROWS, COLUMNS)), ['C3:Bonepile']);
ok('and it now reports itself active', filter.active() === true);
eq('the filter reads back as the value that was kept',
   filter.filterFor('Result'), ['Bonepile']);

/* --------------------------- a second column narrows, it does not replace */

filter.setFilter('Result', ['Pass', 'Retest Pass', 'Bonepile']);
filter.setFilter('Status', ['fail']);
eq('two columns intersect',
   results(filter.rows(ROWS, COLUMNS)), ['B2:Retest Pass', 'C3:Bonepile']);

/* A menu offers what the OTHER filters leave available, so it can never offer
 * a value that would empty the table. With Status pinned to `fail`, Result has
 * no `Pass` left to offer. */
menu = openMenuOn('Result');
listed = menu.querySelector('.fm-list').children.map(function (row) {
  return row.querySelector('.fm-value').textContent;
});
/* D4 is a `fail` with no Result at all, so `(blank)` is genuinely reachable
   under Status=fail and the menu is right to offer it. Pass is not: its only
   row passed. */
eq('a menu offers only what the other columns leave reachable',
   listed, ['Bonepile', 'Retest Pass', '(blank)']);

menu.querySelector('.fm-clear').fire('click');
eq('clearing one column leaves the other in force — and only that one',
   results(filter.rows(ROWS, COLUMNS)),
   ['B2:Retest Pass', 'C3:Bonepile', 'D4:']);
ok('Status is still the one filter standing',
   filter.filterFor('Result') === null &&
   JSON.stringify(filter.filterFor('Status')) === '["fail"]');

/* ------------------------------------------------------------------- sort */

filter.clear();
var column = COLUMNS.filter(function (c) { return c.key === 'DUT_SN'; })[0];
var th = new El('th');
filter.head(th, column, COLUMNS, ROWS);
th.querySelector('.col-filter').fire('click', { stopPropagation: function () {} });
menu = document.body.children[document.body.children.length - 1];
menu.querySelector('.fm-sorts').children[1].fire('click');   /* Z -> A */
eq('Z to A sorts descending',
   results(filter.rows(ROWS, COLUMNS)),
   ['D4:', 'C3:Bonepile', 'B2:Retest Pass', 'B2:Retest Pass', 'A1:Pass']);
ok('sorting is reported', filter.sorted() === true);

/* Ties keep the caller's order — the two B2 rows must stay 09-01 then 09-02,
 * because the builder put them in time order and a sort on another column has
 * no opinion about them. */
var ties = filter.rows(ROWS, COLUMNS).filter(function (r) { return r.dut === 'B2'; });
eq('equal values keep the order they arrived in',
   ties.map(function (r) { return r.day; }), ['2026-09-01', '2026-09-02']);

/* Numeric-aware, so 10 sorts after 9 rather than before it. */
var NUM = [{ n: '9' }, { n: '10' }, { n: '1' }];
var NUMCOL = [{ key: 'n', title: 'n', value: function (r) { return r.n; } }];
var numeric = ColFilter.create({ onChange: function () {} });
var nth = new El('th');
numeric.head(nth, NUMCOL[0], NUMCOL, NUM);
nth.querySelector('.col-filter').fire('click', { stopPropagation: function () {} });
document.body.children[document.body.children.length - 1]
        .querySelector('.fm-sorts').children[0].fire('click');
eq('digits inside the text sort as numbers',
   numeric.rows(NUM, NUMCOL).map(function (r) { return r.n; }), ['1', '9', '10']);

/* -------------------------------------------------------------- the search */

filter.clear();
menu = openMenuOn('Result');
var search = menu.querySelector('.fm-search');
search.value = 'pass';
search.fire('input');
var visible = menu.querySelector('.fm-list').children
  .filter(function (row) { return !row.hidden; })
  .map(function (row) { return row.querySelector('.fm-value').textContent; });
eq('the search narrows the list it shows', visible, ['Pass', 'Retest Pass']);

/* "None" acts on what the search is showing, not on the whole list — the Excel
 * behaviour, and the reason a search box in a filter menu is useful at all. */
menu.querySelector('.fm-none').fire('click');
menu.querySelector('.fm-apply').fire('click');
eq('None applies to the searched subset only',
   results(filter.rows(ROWS, COLUMNS)), ['C3:Bonepile', 'D4:']);

/* ------------------------------------------------- closing without applying */

filter.clear();
menu = openMenuOn('Result');
menu.querySelector('.fm-none').fire('click');
document.fire('keydown', { key: 'Escape' });
ok('Escape closes the menu', document.body.children.length === 0);
eq('a menu closed without Apply changes nothing',
   results(filter.rows(ROWS, COLUMNS)),
   ['A1:Pass', 'B2:Retest Pass', 'B2:Retest Pass', 'C3:Bonepile', 'D4:']);

/* -------------------------------------------------------- heading feedback */

filter.setFilter('Result', ['Bonepile']);
var marked = new El('th');
filter.head(marked, COLUMNS[3], COLUMNS, ROWS);
ok('a filtered heading says so', marked.className.indexOf('is-filtered') !== -1);
var plain = new El('th');
filter.head(plain, COLUMNS[0], COLUMNS, ROWS);
ok('an unfiltered one does not', plain.className.indexOf('is-filtered') === -1);

print(FAILURES ? ('colfilter.js: ' + FAILURES + ' FAIL') : 'colfilter.js: ok');
