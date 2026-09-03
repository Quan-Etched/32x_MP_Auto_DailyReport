/* Which drawing of the line flow.html is showing.
 *
 * Two charts, one page. They were two pages, and the second one was reached by
 * a link in a row of eleven — which is to say it was not reached. Both are
 * drawn on load into their own canvases (they cannot share one: each renderer
 * clears what it draws into), and this only decides which is visible.
 *
 * The summary is the default. It is the line's own chart, it carries the
 * accumulated MLT x HTT yield, and it is the one people arrive expecting.
 */
(function () {
  'use strict';

  var VIEWS = [
    ['summary', 'Summary', 'The line’s own chart, stage by stage, with the ' +
      'accumulated MLT × HTT yield.'],
    ['e2e', 'End-to-end', 'Every insertion, including the ones no controller ' +
      'reports.']
  ];

  function byId(id) { return document.getElementById(id); }

  function show(which) {
    VIEWS.forEach(function (view) {
      var section = byId('view-' + view[0]);
      if (!section) return;
      if (view[0] === which) section.removeAttribute('hidden');
      else section.setAttribute('hidden', 'hidden');
    });

    var host = byId('chart-switch');
    if (!host) return;
    host.innerHTML = '';
    VIEWS.forEach(function (view) {
      var on = view[0] === which;
      var button = document.createElement('button');
      button.setAttribute('type', 'button');
      button.setAttribute('class', 'fs-btn' + (on ? ' on' : ''));
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      var name = document.createElement('span');
      name.setAttribute('class', 'fs-k');
      name.textContent = view[1];
      var why = document.createElement('span');
      why.setAttribute('class', 'fs-s');
      why.textContent = view[2];
      button.appendChild(name);
      button.appendChild(why);
      button.addEventListener('click', function () {
        show(view[0]);
        /* In the address, so a link to the end-to-end chart lands on it — the
           whole reason the separate page existed. Through FlowHash, because
           the window control writes to the same address and assigning the
           whole hash here erased its choice. */
        if (window.FlowHash) {
          window.FlowHash.set('chart', view[0]);
        } else if (window.history && window.history.replaceState) {
          window.history.replaceState(null, '', '#chart=' + view[0]);
        }
      });
      host.appendChild(button);
    });

    /* The end-to-end chart is drawn while hidden, so its wires were measured
       against a zero-width canvas. Ask it to measure again now it is visible. */
    if (window.dispatchEvent) {
      window.dispatchEvent(new Event('resize'));
    }
  }

  function init() {
    var asked = /chart=(summary|e2e)/.exec(location.hash || '');
    show(asked ? asked[1] : 'summary');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
