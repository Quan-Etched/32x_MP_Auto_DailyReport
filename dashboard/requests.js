/* The feature-request page.
 *
 * A list of asks against other systems, each with a status the build worked out
 * rather than a status someone typed. Two things this page tries hard to do:
 *
 *  - Never claim more than the probe knows. A check that ran on a laptop says
 *    so, because "reachable from here" is not the same claim as "reachable from
 *    the host that publishes this page", and the difference is the entire ask.
 *  - Keep the un-probeable entries visibly un-probed. A decision nobody has
 *    made and a route nobody has opened are both open, but they are not the
 *    same kind of open, and flattening them would hide which one needs a person
 *    rather than a ticket.
 *
 * Plain ES5, no build step — same as every other page here.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_REQUESTS__ || {};
  var ALL = DATA.requests || [];

  var STATE_LABEL = {
    blocked:  'Blocked',
    resolved: 'Resolved',
    open:     'Open',
    unknown:  'Unverified',
    decision: 'Needs a decision'
  };

  /* Order the list by what a reader should act on first: things that are
   * blocking, then things waiting on a person, then what is already done. */
  var STATE_RANK = { blocked: 0, open: 1, decision: 2, unknown: 3, resolved: 4 };
  var PRIORITY_RANK = { P0: 0, P1: 1, P2: 2, Decision: 3, Question: 4, Escalation: 5 };

  var filter = null;

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  function byId(id) { return document.getElementById(id); }

  function ago(iso) {
    if (!iso) return '';
    var mins = (Date.now() - Date.parse(iso)) / 60000;
    if (isNaN(mins)) return '';
    if (mins < 1) return 'just now';
    if (mins < 60) return Math.round(mins) + 'm ago';
    if (mins < 48 * 60) return Math.round(mins / 60) + 'h ago';
    return Math.round(mins / 1440) + 'd ago';
  }

  /* Backticked spans in the registry are identifiers — hostnames, endpoints,
   * commands. They are the substance of an evidence line, so they are set as
   * code rather than left as prose. */
  function withCode(text) {
    var frag = document.createDocumentFragment();
    String(text).split('`').forEach(function (part, index) {
      if (!part) return;
      frag.appendChild(index % 2 ? h('code', { text: part })
                                 : document.createTextNode(part));
    });
    return frag;
  }

  function sorted(list) {
    return list.slice().sort(function (a, b) {
      var sa = STATE_RANK[a.status.state], sb = STATE_RANK[b.status.state];
      if (sa !== sb) return sa - sb;
      var pa = PRIORITY_RANK[a.priority], pb = PRIORITY_RANK[b.priority];
      if (pa !== pb) return (pa === undefined ? 9 : pa) - (pb === undefined ? 9 : pb);
      return a.title < b.title ? -1 : 1;
    });
  }

  /* -------------------------------------------------------------- summary */

  function renderSummary() {
    var counts = DATA.counts || {};
    var el = byId('summary');
    el.innerHTML = '';

    var blocking = DATA.openBlocking || 0;
    el.appendChild(h('div', { class: 'req-tile headline' }, [
      h('span', { class: 'k', text: 'Blocking automation' }),
      h('strong', { class: 'v', text: String(blocking) }),
      h('span', { class: 's', text: blocking === 1
        ? 'one P0 or P1 ask is still open'
        : blocking + ' P0/P1 asks are still open' })
    ]));

    ['blocked', 'open', 'decision', 'resolved'].forEach(function (state) {
      if (!counts[state]) return;
      el.appendChild(h('div', { class: 'req-tile ' + state }, [
        h('span', { class: 'k', text: STATE_LABEL[state] }),
        h('strong', { class: 'v', text: String(counts[state]) }),
        h('span', { class: 's', text: state === 'resolved'
          ? 'closed since this page was started'
          : state === 'decision' ? 'waiting on a person, not a ticket'
          : state === 'open' ? 'no automated check for these'
          : 'verified still true by this build' })
      ]));
    });
  }

  /* --------------------------------------------------------------- filter */

  function renderFilter() {
    var bar = byId('filterbar');
    bar.innerHTML = '';
    var owners = [];
    ALL.forEach(function (r) {
      if (owners.indexOf(r.owner) === -1) owners.push(r.owner);
    });

    function chip(label, value, count) {
      var active = filter === value;
      var button = h('button', {
        type: 'button', 'aria-pressed': active ? 'true' : 'false'
      }, [
        document.createTextNode(label),
        h('span', { class: 'n', text: String(count) })
      ]);
      button.addEventListener('click', function () {
        filter = active ? null : value;
        render();
      });
      return button;
    }

    bar.appendChild(chip('Everything', null, ALL.length));
    owners.forEach(function (owner) {
      var n = ALL.filter(function (r) { return r.owner === owner; }).length;
      bar.appendChild(chip(owner, owner, n));
    });
  }

  /* ----------------------------------------------------------------- list */

  function renderOne(req) {
    var state = req.status.state;
    var card = h('article', { class: 'req req-' + state });

    var head = h('div', { class: 'req-head' }, [
      h('span', { class: 'req-pri pri-' + String(req.priority).toLowerCase(),
                  text: req.priority }),
      h('span', { class: 'req-owner', text: req.owner }),
      h('h2', { class: 'req-title', text: req.title })
    ]);
    card.appendChild(head);

    var status = h('div', { class: 'req-status' }, [
      h('span', { class: 'pill pill-' + state, text: STATE_LABEL[state] || state })
    ]);
    status.appendChild(h('span', { class: 'req-note' }, [withCode(req.status.note || '')]));
    if (req.status.checkedAt) {
      status.appendChild(h('span', {
        class: 'req-checked',
        text: 'checked ' + ago(req.status.checkedAt),
        title: req.status.checkedAt
      }));
    }
    card.appendChild(status);

    card.appendChild(h('p', { class: 'req-need' }, [withCode(req.need)]));

    if (req.evidence && req.evidence.length) {
      var list = h('ul', { class: 'req-evidence' });
      req.evidence.forEach(function (line) {
        list.appendChild(h('li', {}, [withCode(line)]));
      });
      card.appendChild(list);
    }

    card.appendChild(h('p', { class: 'req-done' }, [
      h('span', { class: 'lbl', text: 'Done when' }),
      h('span', {}, [withCode(req.doneWhen)])
    ]));

    if (req.workaround) {
      card.appendChild(h('p', { class: 'req-aside' }, [
        h('span', { class: 'lbl', text: 'Today' }),
        h('span', {}, [withCode(req.workaround)])
      ]));
    }
    if (req.note) {
      card.appendChild(h('p', { class: 'req-aside' }, [
        h('span', { class: 'lbl', text: 'Note' }),
        h('span', {}, [withCode(req.note)])
      ]));
    }
    if (req.raised) {
      card.appendChild(h('p', { class: 'req-raised', text: 'Raised ' + req.raised }));
    }
    return card;
  }

  function render() {
    renderFilter();
    var host = byId('requests');
    host.innerHTML = '';
    var list = filter
      ? ALL.filter(function (r) { return r.owner === filter; })
      : ALL;
    sorted(list).forEach(function (req) { host.appendChild(renderOne(req)); });
  }

  function init() {
    if (!ALL.length) {
      byId('requests').appendChild(h('p', { class: 'req-empty',
        text: 'No requests recorded. Add one in src/factory/requests.py.' }));
      return;
    }
    byId('meta').textContent = ALL.length + ' open with other teams';
    renderSummary();
    render();

    byId('footer-meta').textContent =
      'Checked on ' + (DATA.builtOn || 'unknown host') + ' at ' +
      String(DATA.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC') +
      '. A probe is only true where it ran — the published copy is built on the ' +
      'dashboard host, so that is the answer that counts.';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
