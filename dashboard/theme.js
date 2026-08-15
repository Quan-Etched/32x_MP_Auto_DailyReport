/* The theme button, for the pages whose own script does not carry one.
 *
 * Three states, cycled: dark -> light -> system. "System" is the absence of
 * the attribute, which is what lets prefers-color-scheme decide — so it is
 * removed rather than set to a third value.
 *
 * stations.js, runtable.js and app.js each wire their own because they must
 * redraw canvases on the change; this is for the pages that only need the
 * attribute flipped, where the button was previously inert.
 */
(function () {
  'use strict';

  function wire() {
    var button = document.getElementById('theme-toggle');
    if (!button || button.dataset.wired) return;
    button.dataset.wired = '1';

    var root = document.documentElement;
    button.textContent = 'Theme: ' + (root.getAttribute('data-theme') || 'system');
    button.addEventListener('click', function () {
      var current = root.getAttribute('data-theme');
      var next = current === 'dark' ? 'light' : current === 'light' ? null : 'dark';
      if (next) root.setAttribute('data-theme', next);
      else root.removeAttribute('data-theme');
      button.textContent = 'Theme: ' + (next || 'system');
      /* Anything that measured the old colours redraws itself. */
      window.dispatchEvent(new Event('resize'));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
