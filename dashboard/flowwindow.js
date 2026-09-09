/* Which window the flowchart's yields cover.
 *
 * WHY THERE IS A CHOICE AT ALL
 * The chart counts the week to date, and that stays the default: the line
 * stands in front of this page and reads it as "how are we doing", which a
 * trailing seven days answers with half of this week and half of last — a
 * number quoted on Thursday covering days already quoted on Monday under a
 * different heading.
 *
 * It is also, at nine on a Monday, four units. Eleven boxes reading "no runs in
 * the window" beside two reading "3 units" looks like a broken dashboard rather
 * than like a young week, and the reader who wants to know what the line has
 * actually been doing has nowhere on this page to go.
 *
 * So the week keeps the default and the trailing seven days is one click away,
 * named. The two are never mixed: every box on the chart is the same window and
 * the control says which one, because a chart where one stage is this week and
 * the next is last week is worse than either window on its own.
 *
 * The counts on the pills carry as much as the pills do. "This week 5 runs"
 * beside "Last 7 days 258 runs" answers "why is it empty" before anybody
 * clicks, which a control that only offered the choice would not.
 *
 * Plain ES5, no build step, no dependencies.
 */
(function () {
  'use strict';

  var STATIONS = window.__FACTORY_STATIONS__ || {};

  /* -------------------------------------------------------------- the address
   *
   * Two controls now write to the hash — which drawing, and which window — and
   * they each used to write it by assignment, so whichever moved last erased
   * the other's choice from the address. Read the whole thing, change one key,
   * put it back.
   */
  var FlowHash = {
    read: function () {
      var out = {};
      String(location.hash || '').replace(/^#/, '').split('&')
        .forEach(function (part) {
          var eq = part.indexOf('=');
          if (eq < 1) return;
          out[decodeURIComponent(part.slice(0, eq))] =
            decodeURIComponent(part.slice(eq + 1));
        });
      return out;
    },
    set: function (key, value) {
      var all = FlowHash.read();
      all[key] = value;
      var text = Object.keys(all).map(function (name) {
        return encodeURIComponent(name) + '=' + encodeURIComponent(all[name]);
      }).join('&');
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', '#' + text);
      } else {
        location.hash = text;
      }
    }
  };
  window.FlowHash = FlowHash;

  /* --------------------------------------------------------------- the choice
   *
   * `views` and `window` name the keys in the station bundle, so the two
   * windows are picked apart in one place rather than at every call site.
   */
  var OPTIONS = [
    { key: 'week', label: 'This week', note: 'from Monday',
      views: 'viewsWeek', window: 'windowWeek' },
    { key: '7d',   label: 'Last 7 days', note: 'trailing',
      views: 'views',     window: 'window' }
  ];

  /* An older bundle predates the week views. Offer what it actually carries:
     a control with one pill on it is not a choice, and a pill that selects a
     window the bundle does not have would empty the chart. */
  function offered() {
    return OPTIONS.filter(function (option) { return STATIONS[option.views]; });
  }

  function optionFor(key) {
    return offered().filter(function (option) {
      return option.key === key;
    })[0] || offered()[0] || OPTIONS[1];
  }

  /* Both counts through the same view, so the two pills compare like with
     like. `windowWeek.runs` counts unclassified runs too and would read a
     little higher than the chart it is labelling. */
  function runsIn(option) {
    var all = (STATIONS[option.views] || {}).__all__;
    return ((all && all.summary) || {}).runs || 0;
  }

  var asked = FlowHash.read().window;
  var state = { key: optionFor(asked).key };
  var listeners = [];
  var host = null;

  function current() { return optionFor(state.key); }

  function views() { return STATIONS[current().views] || {}; }
  function windowOf() { return STATIONS[current().window] || {}; }

  function onChange(fn) { if (fn) listeners.push(fn); }

  function select(key) {
    if (key === state.key) return;
    state.key = key;
    FlowHash.set('window', key);
    paint();
    listeners.forEach(function (fn) { fn(); });
  }

  function paint() {
    if (!host) return;
    var options = offered();
    host.innerHTML = '';
    if (options.length < 2) return;   /* nothing to pick: say nothing */

    var label = document.createElement('span');
    label.className = 'fw-label';
    label.textContent = 'Yields cover';
    host.appendChild(label);

    options.forEach(function (option) {
      var on = option.key === state.key;
      var runs = runsIn(option);
      var button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.title = option.key === 'week'
        ? 'The calendar week so far, from Monday'
        : 'The last seven days with runs, wherever the week boundary falls';

      var name = document.createElement('span');
      name.textContent = option.label;
      button.appendChild(name);

      var count = document.createElement('span');
      count.className = 'n';
      count.textContent = runs + (runs === 1 ? ' run' : ' runs');
      button.appendChild(count);

      button.addEventListener('click', function () { select(option.key); });
      host.appendChild(button);
    });
  }

  function mount(id) {
    host = document.getElementById(id);
    paint();
  }

  window.FlowWindow = {
    key: function () { return state.key; },
    views: views,
    window: windowOf,
    onChange: onChange,
    mount: mount
  };

  function init() { mount('flow-window'); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
