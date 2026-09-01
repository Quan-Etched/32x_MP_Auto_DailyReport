/* A DOM small enough to run dashboard/trace.js under JavaScriptCore.
 *
 * WHY THIS RATHER THAN A REAL BROWSER
 * The published dashboard has no build step and no test runner for its JS, so
 * until now the only check on a page module was opening it. trace.js decides
 * what a failure investigation is told about a serial -- which records exist,
 * which link reaches the raw data -- and that deserves an assertion, not a
 * squint. This stub is the smallest thing that lets the real module run: enough
 * DOM to append nodes and read their text back, nothing more.
 */
var LOG = [];

function El(tag) {
  this.tagName = tag; this.children = []; this.attrs = {};
  this.textContent = ''; this.className = ''; this.innerHTML = '';
}
El.prototype.appendChild = function (kid) { this.children.push(kid); return kid; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.addEventListener = function () {};
El.prototype.remove = function () {};
El.prototype.text = function () {
  var out = this.textContent || '';
  for (var i = 0; i < this.children.length; i++) out += ' ' + this.children[i].text();
  return out;
};
El.prototype.hrefs = function () {
  var out = this.attrs.href ? [this.attrs.href] : [];
  for (var i = 0; i < this.children.length; i++) out = out.concat(this.children[i].hrefs());
  return out;
};

var TRACE_HOST = new El('div');
var listeners = {};
var document = {
  readyState: 'complete',
  getElementById: function (id) { return id === 'trace' ? TRACE_HOST : null; },
  createElement: function (tag) { return new El(tag); },
  createTextNode: function (text) { var n = new El('#text'); n.textContent = text; return n; },
  addEventListener: function (name, fn) { listeners[name] = fn; },
  body: new El('body')
};
var window = {
  location: { hash: '' },
  addEventListener: function (name, fn) { listeners[name] = fn; }
};
var Blob = function () {}; var URL = { createObjectURL: function () { return 'blob:x'; },
                                       revokeObjectURL: function () {} };
var setTimeout = function () {};

function assert(cond, label) {
  LOG.push((cond ? 'ok   ' : 'FAIL ') + label);
  if (!cond) LOG.failed = true;
}

/* jsc has no event loop: microtasks only run once the top-level script ends, so
 * a synchronous test can never observe a promise resolving. `after(n, fn)`
 * therefore chains n turns of the queue and runs fn on the far side, which is
 * enough for a multi-step chain (fetch -> read -> decode -> parse -> adopt) to
 * have finished. Assertions that follow an async call go inside it. */
function after(turns, fn) {
  var p = Promise.resolve();
  for (var i = 0; i < turns; i++) p = p.then(function () {});
  return p.then(fn);
}
