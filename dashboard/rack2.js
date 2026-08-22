/* The second L11 rack, and where its four servers actually stand.
 *
 * WHY THIS IS NOT A STATIC ANNOUNCEMENT
 * "Rack 2 assembled" is true on the day and stops being news the day after. The
 * useful page is the one that says what is in the rack and what those units are
 * doing — and that has to come from the controllers, or it is a screenshot with
 * a date on it that nobody updates and everybody quotes.
 *
 * So the serials are written down here, once, because a rack's bill of
 * materials is not something this pipeline can derive; everything else — every
 * verdict, every attempt count, every link — is read from the run bundle at
 * load. The day SS2 clears run-in, this page says so without anyone editing it.
 *
 * Plain ES5, no build step, no dependencies.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RUNS__ || {};
  var RUNS = DATA.runs || [];
  var LINKS = DATA.links || {};
  var LABELS = DATA.stationLabels || {};

  /* The rack and what is in it. Hand-recorded from the floor, because nothing
   * in this pipeline maps a rack serial to the servers inside it — pega5 knows
   * the rack, pega4 knows the servers, and the join is a person. */
  var RACK = {
    sn: '268708630001',
    where: 'Pegatron',
    on: '2026-08-22',
    /* The SFIS lookup the floor uses. Recorded as a template so a host change
     * is one edit. */
    sfis: 'http://pega-sfis/lookup?sn={sn}',
    servers: [
      { slot: 'SS1', sn: '268645410001' },
      { slot: 'SS2', sn: '268645440007' },
      { slot: 'SS3', sn: '268645430002' },
      { slot: 'SS4', sn: '268645430004' }
    ]
  };

  /* The L10 stages a server goes through, in order. */
  var STAGES = ['l10_fat', 'l10_sft', 'l10_rin'];

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else if (attrs[key] !== null && attrs[key] !== undefined)
        node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  function labelOf(key) { return (LABELS[key] || key).replace(/^L10 /, ''); }
  function sfisFor(sn) { return RACK.sfis.replace('{sn}', encodeURIComponent(sn)); }

  function utcDay(run) {
    return run.t ? new Date(run.t * 1000).toISOString().slice(0, 10) : '';
  }

  function runUrl(run) {
    var cfg = LINKS.pega;
    if (!cfg || !run || !run.i) return '';
    var host = (cfg.hosts || {})[run.k];
    if (!host) return '';
    var id = String(run.i), slot = null, at = id.indexOf('#slot');
    if (at !== -1) { slot = id.slice(at + 5); id = id.slice(0, at); }
    var template = slot === null ? cfg.runTemplateNoSlot : cfg.urlTemplate;
    if (!template) return '';
    return template.replace('{host}', host)
      .replace('{run}', encodeURIComponent(id))
      .replace('{slot}', encodeURIComponent(slot || ''));
  }

  /* Every run this bundle has for one serial, by station, oldest first. */
  function historyFor(sn) {
    var out = {};
    RUNS.forEach(function (run) {
      if (String(run.d) !== sn) return;
      (out[run.k] || (out[run.k] = [])).push(run);
    });
    Object.keys(out).forEach(function (key) {
      out[key].sort(function (a, b) { return (a.t || 0) - (b.t || 0); });
    });
    return out;
  }

  function latest(runs) {
    var graded = (runs || []).filter(function (run) {
      return run.s === 'pass' || run.s === 'fail';
    });
    /* An errored run is not a verdict, but it is not nothing either — if a
     * stage has only errors, that is what the cell should say. */
    return graded.length ? graded[graded.length - 1]
                         : (runs || [])[(runs || []).length - 1] || null;
  }

  /* ------------------------------------------------------------------ rack */

  function renderRack() {
    byId('rack-sn').textContent = RACK.sn;
    var sfis = byId('rack-sfis');
    sfis.setAttribute('href', sfisFor(RACK.sn));
    sfis.setAttribute('title', sfisFor(RACK.sn));
    byId('meta').textContent = RACK.where + ' · ' + RACK.on;
    byId('photo-cap').textContent = RACK.where + ', ' + RACK.on;

    /* The rack's own L11 record, which today is nothing — and saying so is the
     * point. Assembled and tested are different milestones, and a page that
     * blurred them would be quoted as the second. */
    var l11 = RUNS.filter(function (run) {
      return String(run.d) === RACK.sn && String(run.k).indexOf('l11') === 0;
    });
    var host = byId('rack-state');
    host.innerHTML = '';
    if (!l11.length) {
      host.appendChild(h('p', { class: 'r2-note', text:
        'Assembled, not yet tested: the controllers have no L11 run against ' +
        'this serial. Provisioning and rack test are still ahead of it.' }));
    } else {
      var last = latest(l11);
      host.appendChild(h('p', { class: 'r2-note', text:
        plural(l11.length, 'L11 run') + ' on record, latest ' +
        utcDay(last) + ' — ' + (last.s || 'unknown') + '.' }));
    }
  }

  /* --------------------------------------------------------------- servers */

  function serverRows() {
    return RACK.servers.map(function (server) {
      var hist = historyFor(server.sn);
      var row = { slot: server.slot, sn: server.sn, stages: {}, runs: 0 };
      Object.keys(hist).forEach(function (key) { row.runs += hist[key].length; });
      STAGES.forEach(function (stage) {
        var runs = hist[stage] || [];
        var last = latest(runs);
        row.stages[stage] = {
          status: last ? (last.s || '') : '',
          attempts: runs.length,
          day: last ? utcDay(last) : '',
          url: runUrl(last)
        };
      });
      return row;
    });
  }

  function verdict(cell) {
    if (!cell.status) return h('span', { class: 'r2-none', text: '—' });
    var kids = [h('span', { class: 'r2-' + cell.status, text: cell.status })];
    /* The attempt count is the story on these four: a pass at the ninth
     * attempt and a pass at the first are not the same event. */
    if (cell.attempts > 1) {
      kids.push(h('span', { class: 'r2-att',
                            text: '×' + cell.attempts }));
    }
    if (cell.url) {
      kids.push(h('a', { class: 'r2-run', href: cell.url, target: '_blank',
                         rel: 'noopener noreferrer', title: cell.url,
                         text: cell.day }));
    }
    return h('span', { class: 'r2-cell' }, kids);
  }

  function renderServers() {
    var rows = serverRows();
    var head = byId('servers-head'), body = byId('servers-body');
    head.innerHTML = ''; body.innerHTML = '';

    head.appendChild(h('tr', {}, ['Slot', 'Serial', 'SFIS']
      .concat(STAGES.map(labelOf)).concat(['Runs'])
      .map(function (title) { return h('th', { text: title }); })));

    rows.forEach(function (row) {
      var tr = h('tr', {});
      tr.appendChild(h('td', { class: 'r2-slot', text: row.slot }));
      tr.appendChild(h('td', { class: 'mono' }, [
        h('a', { href: 'runs.html#dut=' + row.sn,
                 title: 'this unit in the run table', text: row.sn })
      ]));
      tr.appendChild(h('td', {}, [
        h('a', { class: 'r2-run', href: sfisFor(row.sn), target: '_blank',
                 rel: 'noopener noreferrer', title: sfisFor(row.sn),
                 text: 'SFIS ↗' })
      ]));
      STAGES.forEach(function (stage) {
        tr.appendChild(h('td', {}, [verdict(row.stages[stage])]));
      });
      tr.appendChild(h('td', { class: 'num', text: String(row.runs) }));
      body.appendChild(tr);
    });

    var clean = rows.filter(function (row) {
      return STAGES.every(function (stage) {
        return row.stages[stage].status === 'pass';
      });
    }).length;
    byId('servers-sub').textContent =
      clean + ' of ' + rows.length + ' are passing every L10 stage they have ' +
      'reached. The count beside a verdict is how many times that stage has ' +
      'run on that server.';

    /* The honest headline, computed rather than written: the rack is built and
     * its servers are not through L10 yet. If that changes, so does this. */
    var stuck = [];
    rows.forEach(function (row) {
      STAGES.forEach(function (stage) {
        var cell = row.stages[stage];
        if (cell.status && cell.status !== 'pass') {
          stuck.push(row.slot + ' at ' + labelOf(stage));
        }
      });
    });
    byId('caveat').textContent = stuck.length
      ? 'Assembly is done; test is not. Open right now: ' +
        stuck.join(', ') + '. Those are the runs between this rack and a ' +
        'shippable one.'
      : 'Every stage these four have reached is passing.';

    if (window.FactoryCsv) {
      var host = byId('download');
      host.innerHTML = '';
      window.FactoryCsv.attach(host, {
        table: function () { return byId('servers'); },
        name: 'rack-' + RACK.sn + '-servers.csv',
        label: 'Download CSV'
      });
    }
  }

  function init() {
    if (!byId('servers-body')) return;
    /* No photo checked in yet: drop the figure rather than show a broken
     * image. */
    var photo = byId('photo');
    if (photo) {
      photo.addEventListener('error', function () {
        var figure = photo.parentNode;
        if (figure && figure.parentNode) figure.parentNode.removeChild(figure);
      });
    }
    var build = DATA.build || {};
    byId('build').textContent = build.release
      ? build.release + ' · ' + build.commit : '';
    byId('footer-meta').textContent =
      'Serials recorded by hand from the floor; every verdict read from the ' +
      'station controllers' +
      (DATA.collectedAt
        ? ', ' + String(DATA.collectedAt).replace('T', ' ') : '') + '.';
    renderRack();
    renderServers();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
