/* The Update button, shared by all three dashboard pages.
 *
 * TWO MODES, DECIDED BY WHO IS SERVING THE PAGE
 * ---------------------------------------------
 * Served locally by `factory.cli serve`, /api/ping answers and the button is
 * live: one click runs collect -> items -> build -> publish and streams the
 * stages back.
 *
 * On a published copy nothing answers /api/ping, so the same markup renders as
 * a freshness chip saying how old the snapshot is. A button that could not do
 * what it says would be worse than no button. (On the dashboard host that is a
 * wiring gap, not a law: nginx proxies /api/ to 127.0.0.1:8765 there and the
 * ETL runs on the same box. See docs/deploy.md.)
 *
 * Style note: plain ES5, no build step, no dependencies — same as the rest of
 * the dashboard, which has to open over file:// as well as http://.
 */
(function () {
  'use strict';

  var POLL_MS = 1200;
  var API = 'api/update';

  var el = {};
  var polling = null;
  var startedAt = null;
  // Whether *this* page instance started the running job. The server remembers
  // the last job across reloads, so without this the page reloaded after a
  // successful update would greet the reader with a finished panel still
  // promising to reload.
  var owned = false;

  /* ------------------------------------------------------------------ dom */

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else if (key === 'html') node.innerHTML = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { node.appendChild(kid); });
    return node;
  }

  function mount() {
    var masthead = document.querySelector('.masthead');
    if (!masthead) return false;

    el.button = h('button', {
      type: 'button',
      class: 'update-btn',
      id: 'update-btn',
      'aria-live': 'polite'
    });
    // Before the theme toggle: the primary action of the page should not be
    // the last thing in the row.
    var toggle = masthead.querySelector('#theme-toggle');
    masthead.insertBefore(el.button, toggle || null);

    el.panel = h('section', { class: 'update-panel', id: 'update-panel', hidden: 'hidden' });
    masthead.parentNode.insertBefore(el.panel, masthead.nextSibling);
    return true;
  }

  /* ------------------------------------------------------------- freshness */

  function bundle() {
    return window.__FACTORY_STATIONS__ || window.__FACTORY_METRICS__ ||
           window.__FACTORY_RELEASES__ || {};
  }

  function generatedAt() {
    var data = bundle();
    return data.generatedAt || data.collectedAt ||
           (data.fetch && (data.fetch.lastFetchAttemptAt || data.fetch.lastFetchAt)) || null;
  }

  function minutesSince(iso) {
    if (!iso) return null;
    var then = Date.parse(iso);
    if (isNaN(then)) return null;
    return (Date.now() - then) / 60000;
  }

  function ago(iso) {
    var mins = minutesSince(iso);
    if (mins === null) return 'unknown';
    if (mins < 1) return 'just now';
    if (mins < 60) return Math.round(mins) + 'm ago';
    if (mins < 48 * 60) return Math.round(mins / 60) + 'h ago';
    return Math.round(mins / 1440) + 'd ago';
  }

  /* ----------------------------------------------------------- static mode */

  /* No control endpoint: say how old this snapshot is and what refreshes it.
   * Stale is judged against the hourly agent's cadence — past two hours it has
   * either not run or could not publish. */
  function renderStatic() {
    var at = generatedAt();
    var mins = minutesSince(at);
    var stale = mins === null || mins > 130;

    el.button.className = 'update-btn snapshot' + (stale ? ' stale' : '');
    el.button.textContent = 'Snapshot · ' + ago(at);
    el.button.setAttribute('title', at ? 'Data collected ' + at : 'Collection time unknown');
    el.button.addEventListener('click', function () {
      el.panel.hidden = !el.panel.hidden;
    });

    el.panel.appendChild(h('div', { class: 'update-head' }, [
      h('strong', { text: stale ? 'This snapshot is stale' : 'Published snapshot' })
    ]));
    el.panel.appendChild(h('p', {
      class: 'update-note',
      text: 'This is a published copy: static files, so nothing here can reach ' +
            'the EOS API. It changes only when the dashboard host collects and ' +
            'publishes a new bundle, which it does hourly at :05.'
    }));
    el.panel.appendChild(h('p', {
      class: 'update-note',
      text: 'To update it now, on the dashboard host:'
    }));
    el.panel.appendChild(h('pre', { class: 'update-cmd', text: 'make update' }));
    if (stale) {
      el.panel.appendChild(h('p', {
        class: 'update-note',
        text: 'Two hours without a publish means the hourly job did not run or ' +
              'could not finish. `make schedule-status` on the host says which, ' +
              'and prints the tail of the last run.'
      }));
      el.panel.hidden = false;
    }
  }

  /* ------------------------------------------------------------- live mode */

  function renderLive(state) {
    var running = state && state.state === 'running';
    el.button.className = 'update-btn live' + (running ? ' running' : '');
    el.button.disabled = !!running;

    if (running) {
      el.button.textContent = 'Updating… ' + elapsed();
    } else {
      el.button.textContent = 'Update';
      el.button.setAttribute(
        'title', 'Collect from EOS, rebuild, and publish the dashboard');
    }
    if (state) renderPanel(state);
  }

  function elapsed() {
    if (!startedAt) return '';
    var secs = Math.round((Date.now() - startedAt) / 1000);
    return secs < 60 ? secs + 's' : Math.floor(secs / 60) + 'm' + (secs % 60) + 's';
  }

  var TONE = { ok: 'ok', failed: 'bad', busy: 'warn', running: 'run', idle: '' };

  function renderPanel(state) {
    if (state.state === 'idle') { el.panel.hidden = true; return; }
    el.panel.hidden = false;
    el.panel.innerHTML = '';

    el.panel.appendChild(h('div', { class: 'update-head ' + (TONE[state.state] || '') }, [
      h('strong', { text: headline(state) }),
      h('span', { class: 'update-sub', text: state.message || '' })
    ]));

    var list = h('ol', { class: 'update-steps' });
    (state.steps || []).forEach(function (step) {
      list.appendChild(h('li', { class: 'step ' + step.state }, [
        h('span', { class: 'step-mark', text: MARK[step.state] || '·' }),
        h('span', { text: step.label })
      ]));
    });
    el.panel.appendChild(list);

    // The log is the only thing that explains a failure, so show it unprompted
    // when one happens and keep it behind a toggle otherwise.
    var log = (state.log || []).slice(-14).join('\n');
    if (log) {
      var details = h('details', { class: 'update-log' });
      if (state.state === 'failed') details.setAttribute('open', 'open');
      details.appendChild(h('summary', { text: 'Pipeline output' }));
      details.appendChild(h('pre', { text: log }));
      el.panel.appendChild(details);
    }

    if (state.state === 'ok' && owned) {
      el.panel.appendChild(h('p', {
        class: 'update-note',
        text: 'Published. Reloading with the new data…'
      }));
    }
  }

  var MARK = { pending: '○', running: '◐', done: '●', failed: '✕' };

  function headline(state) {
    if (state.state === 'running') return 'Updating — ' + elapsed();
    if (state.state === 'ok') return 'Update complete';
    if (state.state === 'busy') return 'Already running';
    if (state.state === 'failed') return 'Update failed';
    return 'Update';
  }

  /* ------------------------------------------------------------------ wire */

  function get(path) {
    return fetch(path, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('http ' + res.status);
      return res.json();
    });
  }

  function startUpdate() {
    owned = true;
    startedAt = Date.now();
    el.button.disabled = true;
    el.button.textContent = 'Updating… 0s';
    fetch(API, {
      method: 'POST',
      // Not a CORS-safelisted header, so a cross-origin page cannot send it
      // without a preflight the server never answers.
      headers: { 'X-Factory-Update': '1' }
    }).then(function (res) {
      return res.json().then(function (state) { return { res: res, state: state }; });
    }).then(function (result) {
      renderLive(result.state);
      poll();
    }).catch(function (err) {
      renderLive({
        state: 'failed', steps: [],
        message: 'Could not reach the local server: ' + err.message,
        log: ['Is `make serve` still running?']
      });
    });
  }

  function poll() {
    if (polling) clearInterval(polling);
    polling = setInterval(function () {
      get(API).then(function (state) {
        renderLive(state);
        if (state.state === 'running') return;
        clearInterval(polling);
        polling = null;
        if (state.state === 'ok') setTimeout(function () { location.reload(); }, 1200);
      }).catch(function () {
        clearInterval(polling);
        polling = null;
        renderLive({ state: 'failed', steps: [], message: 'Lost the local server', log: [] });
      });
    }, POLL_MS);
  }

  function init() {
    if (!mount()) return;
    get('api/ping').then(function (info) {
      if (!info || !info.canUpdate) throw new Error('no control endpoint');
      el.button.addEventListener('click', startUpdate);
      // A page opened mid-update (or reopened after one) should show the truth,
      // not an idle button.
      return get(API).then(function (state) {
        if (state.state === 'running') {
          // Someone else — another tab, or this one before a reload — is
          // mid-update. Follow it rather than offering a second one.
          startedAt = Date.parse(state.startedAt) || Date.now();
          poll();
        } else if (state.state === 'ok' || state.state === 'idle') {
          // A finished-cleanly job is already visible in the data itself; only
          // a failure or a lock conflict still needs explaining.
          state = { state: 'idle', steps: state.steps, log: [], message: '' };
        }
        renderLive(state);
      });
    }).catch(function () {
      renderStatic();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
