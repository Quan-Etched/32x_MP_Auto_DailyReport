/* Which question the customize page is being asked.
 *
 * Two shapes of question, and they want different inputs. "What happened across
 * these stations over these days" needs a range and a station list. "What
 * happened to this module" needs neither — it wants everything the controllers
 * ever saw for a serial, because the run that matters is usually the one
 * outside whatever window you would have picked.
 *
 * So: a switch, the same as the one on flow.html. Range is the default because
 * it is what the page has always done, and a returning reader should find what
 * they left.
 */
(function () {
  'use strict';

  var MODES = [
    ['range', 'By day and station',
      'Pick a range and stations, filter by result type, take the CSV.'],
    ['dut', 'By DUT_SN',
      'Paste one or more serials — every run they have ever had, with links.']
  ];

  var current = 'range';

  function byId(id) { return document.getElementById(id); }

  function paint() {
    MODES.forEach(function (mode) {
      var host = byId('mode-' + mode[0]);
      if (!host) return;
      if (mode[0] === current) host.removeAttribute('hidden');
      else host.setAttribute('hidden', 'hidden');
    });

    var bar = byId('search-mode');
    if (!bar) return;
    bar.innerHTML = '';
    MODES.forEach(function (mode) {
      var on = mode[0] === current;
      var button = document.createElement('button');
      button.setAttribute('type', 'button');
      button.setAttribute('class', 'fs-btn' + (on ? ' on' : ''));
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      var name = document.createElement('span');
      name.setAttribute('class', 'fs-k');
      name.textContent = mode[1];
      var why = document.createElement('span');
      why.setAttribute('class', 'fs-s');
      why.textContent = mode[2];
      button.appendChild(name);
      button.appendChild(why);
      button.addEventListener('click', function () {
        current = mode[0];
        /* In the address, so a link opens in the mode it was shared from. */
        if (window.history && window.history.replaceState) {
          var hash = (location.hash || '').replace(/[#&]?mode=[a-z]+/, '');
          hash = hash.replace(/^#?/, '');
          window.history.replaceState(null, '',
            '#mode=' + mode[0] + (hash ? '&' + hash : ''));
        }
        paint();
      });
      bar.appendChild(button);
    });
  }

  function init() {
    if (!byId('search-mode')) return;
    var asked = /mode=(range|dut)/.exec(location.hash || '');
    /* A serial in the address implies the serial mode, so a shared
       #dut=... link does not land on the range view with the serial ignored. */
    if (asked) current = asked[1];
    else if (/dut=/.test(location.hash || '')) current = 'dut';
    paint();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
