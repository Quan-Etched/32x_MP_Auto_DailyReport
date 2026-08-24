/* One navigation, rendered on every page.
 *
 * WHY THIS EXISTS
 * Every page carried its own hand-written list of links, and they had drifted:
 * the landing page offered twelve, the weekly page three, the all-hands page
 * one. Which meant the route between two pages depended on which one you
 * happened to be standing on, and a page added last month was reachable from
 * four places and invisible from the rest.
 *
 * So the list lives here, once. A page contributes a <nav id="nav"> and gets
 * the same set as everywhere else, minus a link to itself — a page linking to
 * itself is a dead control that costs a click to discover.
 *
 * The accented "All-hands view" link beside the title is deliberately NOT in
 * here. It is the one destination that gets picked out, and repeating it in the
 * row would put two links to one page in one masthead, which is what this file
 * was partly written to remove.
 */
(function () {
  'use strict';

  /* href, label, and the short note the title attribute carries. Order is the
     order somebody works: where the numbers are, then the detail behind them,
     then the reference pages. */
  var LINKS = [
    ['index.html', 'Station yield',
      'Yield per station, from the controllers — the landing page'],
    ['weekly.html', 'Weekly tracker', 'Every week, every stage, one row each'],
    ['dailyexcel.html', 'Daily tracker',
      'The line’s own daily MLT/HTT sheet, rebuilt'],
    ['runs.html', 'Raw runs', 'One row per unit run — the drill-down'],
    ['customize.html', 'Customize',
      'Pick days and stations, take the CSV, read the error codes'],
    ['flow.html', 'Test flow', 'Both drawings of the line, with yields'],
    ['doe.html', 'Result types',
      'Pass, retest pass and bonepile per unit, and the MLT → HTT flow'],
    ['releases.html', 'Releases', 'Test items by software release'],
    ['hourly.html', 'Hourly rates', 'Throughput and cycle time by the hour'],
    ['rack2.html', 'Rack 2', 'The second L11 rack, and where its servers are'],
    ['requests.html', 'Requests', 'What we need from other systems'],
    ['ocp.html', 'OCP view', 'The same stations, sourced from OCP instead']
  ];

  /* Links a particular page does not want. The customize page builds its own
     row-level view and a jump to the raw run table from there is a step
     sideways into a worse version of what the reader is already looking at. */
  var HIDE = {
    'customize.html': ['runs.html']
  };

  function here() {
    var path = (location.pathname || '').split('/').pop();
    return path || 'index.html';
  }

  function init() {
    var host = document.getElementById('nav');
    if (!host) return;
    var page = here();
    host.innerHTML = '';
    var hidden = HIDE[page] || [];
    LINKS.forEach(function (link) {
      if (link[0] === page) return;          /* no link to the page you are on */
      if (hidden.indexOf(link[0]) !== -1) return;
      var a = document.createElement('a');
      a.setAttribute('class', 'theme-toggle');
      a.setAttribute('href', link[0]);
      a.setAttribute('title', link[2]);
      a.textContent = link[1] + ' →';
      host.appendChild(a);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
