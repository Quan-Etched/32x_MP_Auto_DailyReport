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
    ['daily_FA.html', 'Daily FA',
      'L10 SFT report: yield, CSV, and File Jira for a picked day'],
    ['runs.html', 'Raw runs', 'One row per unit run — the drill-down'],
    ['customize.html', 'Customize',
      'Pick days and stations by range or by serial, take the CSV'],
    ['customize.html#section=errors', 'Error codes',
      'Every failure joined to the error-code catalogue, with root cause'],
    ['flow.html', 'Test flow', 'Both drawings of the line, with yields'],
    ['doe.html', 'Result types',
      'Pass, retest pass and bonepile per unit, and the MLT → HTT flow'],
    ['rack2.html', 'Rack 2', 'The second L11 rack, and where its servers are']
  ];

  /* Behind "More". Reference pages rather than daily reading: somebody opens
     these to answer a specific question, not to see how the line is doing. The
     row was thirteen tabs wide and wrapped to two lines on a laptop, which
     costs more than the two clicks this adds.
   *
   * They stay in the same file and the same order — this is a fold, not a
   * demotion, and a page in here is still one click away from every page. */
  var MORE = [
    ['releases.html', 'Releases', 'Test items by software release'],
    ['hourly.html', 'Hourly rates', 'Throughput and cycle time by the hour'],
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
      if (hidden.indexOf(link[0]) !== -1) return;

      /* Every destination on every page, including the one you are standing
         on.
       *
       * It used to omit the current page, on the grounds that a link to where
       * you already are is a dead control. True, but it made the row of tabs a
       * different row on every page — and someone looking for "Weekly tracker"
       * on the weekly page concluded it had gone. A visible, marked-as-current
       * tab costs one slot and makes the set stable, which is what a reader
       * uses a tab row for.
       *
       * A fragment link counts as the current page only when the fragment
       * matches too: Customize and Error codes are the same document, and
       * marking both current on either would say the reader is in two places. */
      var target = link[0].split('#')[0];
      var fragment = link[0].indexOf('#') === -1 ? '' : link[0].split('#')[1];
      var isHere = target === page
        && (fragment === '' || ('#' + fragment) === (location.hash || ''));

      host.appendChild(tab(link, isHere, page));
    });

    /* "More", holding the reference pages. A <details> rather than scripted
       show/hide: it opens on click, closes on Escape, and works before any of
       this file's own JavaScript has anything to do — which matters for a
       control whose whole job is reaching the rest of the site. */
    var folded = MORE.filter(function (link) {
      return hidden.indexOf(link[0]) === -1;
    });
    if (!folded.length) return;

    var wrap = document.createElement('details');
    wrap.setAttribute('class', 'nav-more');
    var open = document.createElement('summary');
    open.setAttribute('class', 'theme-toggle');
    /* Marked when the page you are on is one of the folded ones, so the row
       still says where you are without being expanded. */
    var hereInside = folded.some(function (link) {
      return link[0].split('#')[0] === page;
    });
    if (hereInside) open.setAttribute('class', 'theme-toggle current');
    open.textContent = hereInside ? 'More ▾' : 'More ▾';
    wrap.appendChild(open);

    var sheet = document.createElement('div');
    sheet.setAttribute('class', 'nav-more-sheet');
    folded.forEach(function (link) {
      var target = link[0].split('#')[0];
      sheet.appendChild(tab(link, target === page, page));
    });
    wrap.appendChild(sheet);
    host.appendChild(wrap);
  }

  function tab(link, isHere, page) {
    var a = document.createElement('a');
    a.setAttribute('class', 'theme-toggle' + (isHere ? ' current' : ''));
    a.setAttribute('href', link[0]);
    a.setAttribute('title', isHere ? 'you are here' : link[2]);
    if (isHere) a.setAttribute('aria-current', 'page');
    a.textContent = link[1] + (isHere ? '' : ' →');
    return a;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
