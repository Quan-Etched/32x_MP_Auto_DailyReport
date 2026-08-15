/* The weekly one-pager: first-pass yield, step by step.
 *
 * One rule runs through it — a number's provenance is part of the number. A
 * stage measured from 279 runs and a stage someone typed in from another
 * team's report are both on this page, and they are never drawn the same way.
 * Same for volume: a 0% on one unit is not a yield, it is a coin toss, so it
 * is greyed and kept out of the headline.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_FPY__ || {};

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
  function pct(v) { return v == null ? '—' : (Math.round(v * 1000) / 10) + '%'; }

  function tone(value) {
    if (value == null) return '';
    if (value >= 0.9) return 'good';
    if (value >= 0.6) return 'warn';
    return 'bad';
  }

  function headline() {
    var totals = DATA.totals || {};
    var external = DATA.external || [];
    var host = byId('headline');
    host.innerHTML = '';

    var rolled = totals.rolledFpy;
    var upstream = 1;
    external.forEach(function (item) { upstream *= item['yield']; });
    var endToEnd = (rolled == null) ? null : rolled * upstream;

    host.appendChild(h('div', { class: 'hl lead' }, [
      h('span', { class: 'k', text: 'Rolled first-pass, board stages' }),
      h('span', { class: 'v', text: pct(rolled) }),
      h('span', { class: 's',
        text: (totals.rolledOver || []).join(' × ') + ' — the chance a ' +
              'board clears all three first time' })
    ]));

    host.appendChild(h('div', { class: 'hl' }, [
      h('span', { class: 'k', text: 'Die to module, including Sigurd' }),
      h('span', { class: 'v', text: pct(endToEnd) }),
      h('span', { class: 's',
        text: external.map(function (item) {
          return item.label + ' ' + pct(item['yield']);
        }).join(' × ') + ' × the board stages. Two of these are ' +
        'reported figures, not measured here.' })
    ]));

    host.appendChild(h('div', { class: 'hl' }, [
      h('span', { class: 'k', text: 'Measured this week' }),
      h('span', { class: 'v', text: String(totals.units || 0) }),
      h('span', { class: 's', text: 'units across ' + (totals.runs || 0) +
        ' runs and ' + (totals.stations || 0) + ' stages, one row per unit' })
    ]));
  }

  function rows() {
    var body = byId('body');
    body.innerHTML = '';
    var thin = DATA.totals && DATA.totals.minCohort;

    (DATA.external || []).forEach(function (item) {
      var tr = h('tr', { class: 'reported' });
      tr.appendChild(h('td', {}, [
        h('span', { class: 'step', text: item.label }),
        h('span', { class: 'ctrl', text: item.source })
      ]));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'n fpy ' + tone(item['yield']),
                               text: pct(item['yield']) }));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'n', text: '—' }));
      tr.appendChild(h('td', { class: 'fails',
        text: 'as of ' + item.asOf + ' — ' + item.note }));
      body.appendChild(tr);
    });

    (DATA.rows || []).forEach(function (row) {
      var isThin = thin && row.newUnits < thin;
      var tr = h('tr', { class: isThin ? 'thin' : '' });

      tr.appendChild(h('td', {}, [
        h('span', { class: 'step', text: row.label }),
        h('span', { class: 'ctrl', text: (row.controller || '') +
          (isThin ? ' · too few units to read' : '') })
      ]));
      tr.appendChild(h('td', { class: 'n', text: String(row.units) }));
      tr.appendChild(h('td', { class: 'n', text: String(row.runs) }));
      tr.appendChild(h('td', { class: 'n fpy ' + (isThin ? '' : tone(row.fpy)) }, [
        document.createTextNode(pct(row.fpy)),
        row.newUnits != null
          ? h('span', { class: 'ctrl', text: 'of ' + row.newUnits + ' new' })
          : null
      ]));
      tr.appendChild(h('td', { class: 'n', text: pct(row.finalYield) }));
      tr.appendChild(h('td', { class: 'n' }, [
        document.createTextNode(row.retestRatio == null ? '—'
                                : pct(row.retestRatio)),
        row.retestUnits != null
          ? h('span', { class: 'ctrl', text: row.retestUnits + ' units' })
          : h('span', { class: 'ctrl', text: row.retestNote || '' })
      ]));

      var fails = h('td', { class: 'fails' });
      (row.topFailures || []).slice(0, 3).forEach(function (item, index) {
        if (index) fails.appendChild(document.createElement('br'));
        fails.appendChild(h('b', { text: item.name }));
        fails.appendChild(document.createTextNode(' ×' + item.runs));
      });
      if (!(row.topFailures || []).length) {
        fails.appendChild(document.createTextNode('nothing failed'));
      }
      tr.appendChild(fails);
      body.appendChild(tr);
    });

    var window7 = DATA.window || {};
    byId('caption').textContent =
      'Seven days, ' + window7.from + ' to ' + window7.to + ' (UTC). ' +
      'First-pass yield counts units on their first run at that step; ' +
      '"after retest" counts units that passed eventually.';
  }

  function readiness() {
    var host = byId('readiness');
    var thin = (DATA.totals || {}).excludedThin || [];
    var rowsBy = {};
    (DATA.rows || []).forEach(function (row) { rowsBy[row.key] = row; });

    var points = [];

    var mlt = rowsBy.mlt, htt = rowsBy.htt;
    if (mlt && htt) {
      points.push(['Module test is the constraint.',
        'MLT first-pass ' + pct(mlt.fpy) + ' and HTT ' + pct(htt.fpy) +
        '. Retest recovers them to ' + pct(mlt.finalYield) + ' and ' +
        pct(htt.finalYield) + ', at a retest load of ' + pct(mlt.retestRatio) +
        ' and ' + pct(htt.retestRatio) + ' of units — every one of those is a ' +
        'second occupancy of a station that is already the bottleneck.']);
    }

    if (thin.length) {
      points.push(['Downstream is still bring-up, not production.',
        thin.map(function (item) {
          return item.label + ' ' + item.units + ' unit' +
                 (item.units === 1 ? '' : 's');
        }).join(', ') + '. Below ' + (DATA.totals || {}).minCohort +
        ' units a yield cannot be read, so these are excluded from the rolled ' +
        'figure rather than dragging it to zero. The readiness question here ' +
        'is volume, not yield.']);
    }

    var vbb = rowsBy.vbb_provision;
    if (vbb) {
      points.push(['Provisioning recovers everything it drops.',
        'VBB first-pass ' + pct(vbb.fpy) + ', but ' + pct(vbb.finalYield) +
        ' of boards end up provisioned. Nothing is scrapped here; the cost is ' +
        'cycle time.']);
    }

    points.push(['Three stages of the flow are still measured by hand.',
      'WST, FT and SLT are Sigurd’s, in STDF and SPLM. Until a chip ' +
      'serial reaches our rows — pega3 returns asic_lot_code and it is empty ' +
      'on every run — die-level and module-level yield cannot be joined, and ' +
      'the two halves of this table stay separate reports.']);

    host.innerHTML = '';
    host.appendChild(h('h2', { text: 'Manufacturing readiness' }));
    var list = h('ul', {});
    points.forEach(function (point) {
      list.appendChild(h('li', {}, [
        h('strong', { text: point[0] }),
        document.createTextNode(' ' + point[1])
      ]));
    });
    host.appendChild(list);
  }

  function sources() {
    var source = DATA.source || {};
    var build = DATA.build || {};
    var host = byId('sources');
    host.innerHTML = '';
    host.appendChild(h('p', { class: 'src', text:
      'Data source: ' + (source.label || 'the station controllers') +
      ' — read directly from pega2 (VBB), pega3 (MLT, HTT), pega4 (L10) and ' +
      'pega5 (L11), one row per unit rather than one per fixture. WST and FT ' +
      'are reported figures from Sigurd, entered by hand and dated on the row. ' +
      'Attempts are numbered over ' + (DATA.historyDays || 30) + ' days of ' +
      'history so a unit returning this week is counted as a retest, not a ' +
      'first pass. Built ' +
      String(DATA.generatedAt || '').replace('T', ' ').replace('+00:00', ' UTC') +
      (build.commit ? ' from ' + build.commit : '') + '.' }));
  }

  function build() {
    var info = DATA.build || {};
    var slot = byId('build');
    if (info.release) {
      slot.appendChild(h('span', { class: 'build-release', text: info.release }));
    }
    if (info.commit) {
      slot.appendChild(info.commitUrl
        ? h('a', { class: 'build-commit', href: info.commitUrl, target: '_blank',
                   rel: 'noopener noreferrer', text: info.commit })
        : h('span', { class: 'build-commit', text: info.commit }));
    }
  }

  function init() {
    if (!(DATA.rows || []).length) {
      byId('caption').textContent = 'No data — run `make fpy`.';
      return;
    }
    var window7 = DATA.window || {};
    byId('meta').textContent = window7.from + ' → ' + window7.to;
    headline();
    rows();
    readiness();
    sources();
    build();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
