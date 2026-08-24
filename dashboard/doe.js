/* The result-type view: pass, retest pass, bonepile — and the flow between
 * MLT and HTT.
 *
 * WHY A SANKEY AND NOT TWO BAR CHARTS
 * Two stacked bars can tell you MLT had ten retest passes and HTT had none.
 * Only the flow tells you what became of the ten — whether the modules MLT
 * recovered went on to pass HTT, failed it, or never turned up. The question
 * underneath the whole retest discussion is what happens to a module *after* it
 * fails, and that is a question about the step between two stations, so the
 * step is what gets drawn.
 *
 * The one property that makes a Sankey readable is that what leaves a node
 * equals what arrives. So two bands exist that are not outcomes at all:
 *
 *   did not arrive   left MLT, never seen at HTT this week. Mostly correct —
 *                    a module that failed MLT should not be at HTT — and the
 *                    band's size is how much of MLT's week never reached the
 *                    next station.
 *   not seen at MLT  turned up at HTT without an MLT record in the window,
 *                    because it was tested before the window opened. Real
 *                    units; dropping them would make the arriving total
 *                    disagree with HTT's own count.
 *
 * Drawn with plain SVG paths. No library: this repo has no build step and a
 * Sankey is four cubic curves and some arithmetic.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_OUTCOMES__ || {};
  var WEEKS = DATA.weeks || [];
  var LABELS = DATA.labels || {};
  var COLOURS = DATA.colours || {};
  var EXCLUSIVE = DATA.exclusive || ['pass', 'retest-pass', 'bonepile',
                                     'no-result'];
  var GONE = DATA.didNotArrive || 'did-not-arrive';
  var ABSENT = 'not-seen-here';

  /* The two bands that are not outcomes, and how they are drawn. Grey, and
     named in full, so nobody reads them as a verdict. */
  var EXTRA = {};
  EXTRA[GONE] = { label: 'did not reach HTT', colour: '#b9b7b0' };
  EXTRA[ABSENT] = { label: 'not seen at MLT this week', colour: '#d0cec7' };

  var view = { week: null };

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else if (key === 'class') node.className = attrs[key];
      else if (attrs[key] !== null && attrs[key] !== undefined)
        node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (attrs[key] !== null && attrs[key] !== undefined)
        node.setAttribute(key, attrs[key]);
    });
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function pct(v, places) {
    return v === null || v === undefined ? '—'
      : (Math.round(v * Math.pow(10, (places === undefined ? 1 : places) + 2))
         / Math.pow(10, places === undefined ? 1 : places)) + '%';
  }
  function nameOf(key) {
    if (EXTRA[key]) return EXTRA[key].label;
    return (LABELS[key] || {}).label || key;
  }
  function colourOf(key) {
    if (EXTRA[key]) return EXTRA[key].colour;
    return COLOURS[key] || '#8a8882';
  }

  function weekOf(label) {
    for (var i = 0; i < WEEKS.length; i += 1) {
      if (WEEKS[i].week === label) return WEEKS[i];
    }
    return WEEKS[WEEKS.length - 1] || null;
  }

  /* ------------------------------------------------------------- the sankey */

  var W = 900, H = 420;
  var PAD = { top: 34, bottom: 26, left: 108, right: 132 };
  var NODE_W = 16, GAP = 10;

  function stack(order, sizes, total, top, height) {
    /* Bands in a fixed order, sized by share, with a gap between them. A fixed
       order matters more than it looks: if the bands reordered themselves by
       size between two weeks, the eye would read the change as movement. */
    var used = order.filter(function (key) { return (sizes[key] || 0) > 0; });
    var room = height - GAP * Math.max(0, used.length - 1);
    var out = {}, y = top;
    used.forEach(function (key) {
      var span = total ? (sizes[key] / total) * room : 0;
      out[key] = { y: y, h: Math.max(span, 1.5), n: sizes[key] };
      y += out[key].h + GAP;
    });
    return out;
  }

  function ribbon(x1, y1, x2, y2, thickness) {
    var mid = (x1 + x2) / 2;
    return 'M' + x1 + ',' + y1
      + 'C' + mid + ',' + y1 + ' ' + mid + ',' + y2 + ' ' + x2 + ',' + y2
      + 'v' + thickness
      + 'C' + mid + ',' + (y2 + thickness) + ' ' + mid + ',' + (y1 + thickness)
      + ' ' + x1 + ',' + (y1 + thickness) + 'Z';
  }

  function renderSankey(host, week) {
    host.innerHTML = '';
    var flow = week.flow || {};
    var ribbons = (flow.ribbons || []).filter(function (r) { return r.units; });
    if (!ribbons.length) {
      host.appendChild(h('p', { class: 'doe-empty',
        text: 'No units ran both stations in this week.' }));
      return;
    }

    var leftOrder = EXCLUSIVE.concat([ABSENT]);
    var rightOrder = EXCLUSIVE.concat([GONE]);

    var leftSize = {}, rightSize = {}, total = 0;
    ribbons.forEach(function (r) {
      leftSize[r.source] = (leftSize[r.source] || 0) + r.units;
      rightSize[r.target] = (rightSize[r.target] || 0) + r.units;
      total += r.units;
    });

    var innerH = H - PAD.top - PAD.bottom;
    var left = stack(leftOrder, leftSize, total, PAD.top, innerH);
    var right = stack(rightOrder, rightSize, total, PAD.top, innerH);

    var plot = svg('svg', {
      viewBox: '0 0 ' + W + ' ' + H, width: '100%',
      role: 'img',
      'aria-label': 'How units flowed from their MLT result to their HTT '
                  + 'result in ' + week.week
    });

    var axisL = svg('text', { x: PAD.left, y: 18, class: 'doe-axis',
                              'text-anchor': 'end' });
    axisL.textContent = 'MLT result';
    plot.appendChild(axisL);
    var axisR = svg('text', { x: W - PAD.right, y: 18, class: 'doe-axis' });
    axisR.textContent = 'HTT result';
    plot.appendChild(axisR);

    /* Ribbons under the nodes, sorted so the biggest are drawn first and the
       thin ones stay visible on top of them. */
    var lo = {}, ro = {};
    ribbons.slice().sort(function (a, b) { return b.units - a.units; })
      .forEach(function (r) {
        var a = left[r.source], b = right[r.target];
        if (!a || !b) return;
        var share = total ? r.units / total : 0;
        var thick = Math.max(share * (innerH - GAP * 4), 1.2);
        var y1 = a.y + (lo[r.source] || 0);
        var y2 = b.y + (ro[r.target] || 0);
        lo[r.source] = (lo[r.source] || 0) + thick;
        ro[r.target] = (ro[r.target] || 0) + thick;

        var path = svg('path', {
          d: ribbon(PAD.left + NODE_W, y1, W - PAD.right - NODE_W, y2, thick),
          fill: colourOf(r.source), 'fill-opacity': 0.34,
          class: 'doe-ribbon'
        });
        var title = svg('title');
        title.textContent = r.units + ' units · ' + nameOf(r.source)
          + ' at MLT → ' + nameOf(r.target) + ' at HTT';
        path.appendChild(title);
        plot.appendChild(path);
      });

    [[left, PAD.left, 'end', -8], [right, W - PAD.right - NODE_W, 'start',
                                   NODE_W + 8]].forEach(function (spec) {
      var bands = spec[0], x = spec[1], anchor = spec[2], dx = spec[3];
      Object.keys(bands).forEach(function (key) {
        var band = bands[key];
        plot.appendChild(svg('rect', {
          x: x, y: band.y, width: NODE_W, height: band.h, rx: 2,
          fill: colourOf(key)
        }));
        var text = svg('text', {
          x: x + dx, y: band.y + Math.min(band.h / 2 + 4, band.h - 2),
          'text-anchor': anchor, class: 'doe-band'
        });
        text.textContent = nameOf(key) + '  ' + band.n;
        plot.appendChild(text);
      });
    });

    host.appendChild(plot);
  }

  /* ------------------------------------------------------------- the tallies */

  function renderStations(week) {
    var host = byId('doe-cards');
    host.innerHTML = '';
    (week.stations || []).forEach(function (row) {
      var counts = row.counts || {};
      var card = h('div', { class: 'doe-card' }, [
        h('div', { class: 'doe-card-head' }, [
          h('strong', { text: row.label }),
          h('span', { class: 'doe-sub', text: row.units + ' units' })
        ])
      ]);

      /* One bar, four segments. The proportions are the point — a table of four
         numbers makes the reader do the division. */
      var bar = h('div', { class: 'doe-bar' });
      EXCLUSIVE.forEach(function (key) {
        var n = counts[key] || 0;
        if (!n) return;
        bar.appendChild(h('span', {
          class: 'doe-seg',
          style: 'width:' + (100 * n / row.units) + '%;background:'
                 + colourOf(key),
          title: nameOf(key) + ': ' + n + ' units — ' + (LABELS[key] || {}).why
        }));
      });
      card.appendChild(bar);

      var list = h('div', { class: 'doe-list' });
      EXCLUSIVE.forEach(function (key) {
        var n = counts[key] || 0;
        list.appendChild(h('div', { class: 'doe-item' + (n ? '' : ' zero') }, [
          h('span', { class: 'doe-dot',
                      style: 'background:' + colourOf(key) }),
          h('span', { class: 'doe-k', text: nameOf(key) }),
          h('strong', { class: 'doe-n', text: String(n) }),
          h('span', { class: 'doe-p',
                      text: row.units ? pct(n / row.units, 0) : '—' })
        ]));
      });
      card.appendChild(list);

      /* The recovery rate, and what did the recovering. Same figure as the
         weekly tracker's Bonepile recovery column, by construction. */
      var back = counts['retest-pass'] || 0;
      card.appendChild(h('p', { class: 'doe-note', text: row.fail
        ? back + ' of ' + row.fail + ' first-attempt failures came back ('
          + pct(row.recoveryRate) + ')'
          + (back ? ' — ' + row.sameRelease + ' on the same build, '
                    + row.differentRelease + ' on a new one.' : '.')
        : 'Nothing failed its first attempt.' }));
      host.appendChild(card);
    });
  }

  function renderWeeks() {
    var host = byId('doe-weeks');
    host.innerHTML = '';
    WEEKS.forEach(function (week) {
      var on = week.week === view.week;
      var button = h('button', {
        type: 'button', class: 'view-toggle' + (on ? ' on' : ''),
        'aria-pressed': on ? 'true' : 'false'
      }, [h('span', { text: week.week })]);
      button.addEventListener('click', function () {
        view.week = week.week;
        if (window.history && window.history.replaceState) {
          window.history.replaceState(null, '', '#week=' + week.week);
        }
        render();
      });
      host.appendChild(button);
    });
  }

  /* Retest pass and bonepile per week, so the trend is visible without paging
     through the weeks one at a time. */
  function renderTrend() {
    var host = byId('doe-trend');
    if (!host) return;
    host.innerHTML = '';
    WEEKS.forEach(function (week) {
      (week.stations || []).forEach(function (row) {
        if (row.key !== 'mlt') return;
        var counts = row.counts || {};
        var track = h('span', { class: 'doe-trend-track' });
        EXCLUSIVE.forEach(function (key) {
          var n = counts[key] || 0;
          if (!n) return;
          track.appendChild(h('span', {
            class: 'doe-seg',
            style: 'width:' + (100 * n / row.units) + '%;background:'
                   + colourOf(key),
            title: week.week + ' ' + nameOf(key) + ': ' + n
          }));
        });
        host.appendChild(h('div', { class: 'doe-trend-row' }, [
          h('span', { class: 'doe-trend-k', text: week.week }),
          track,
          h('span', { class: 'doe-trend-n',
                      text: pct(row.recoveryRate, 0) + ' back' })
        ]));
      });
    });
  }

  function render() {
    var week = weekOf(view.week);
    if (!week) return;
    view.week = week.week;
    renderWeeks();
    byId('doe-sub').textContent = week.week + ' · ' + week.from + ' to '
      + week.to + ' · one outcome per unit per station, counted over the '
      + 'units that ran that week';
    renderStations(week);
    renderSankey(byId('doe-flow'), week);
    byId('doe-flow-sub').textContent =
      'Every unit MLT saw in ' + week.week + ', and what happened to it at '
      + 'HTT. Ribbon width is units.';
    renderTrend();
  }

  function init() {
    if (!byId('doe-flow')) return;
    if (!WEEKS.length) {
      byId('doe-sub').textContent = 'No outcome bundle — run `make outcomes`.';
      return;
    }
    var asked = /week=(\d{4}-W\d{2})/.exec(location.hash || '');
    view.week = asked ? asked[1] : WEEKS[WEEKS.length - 1].week;
    byId('doe-legend').innerHTML = '';
    EXCLUSIVE.concat([GONE, ABSENT]).forEach(function (key) {
      byId('doe-legend').appendChild(h('span', { class: 'doe-key' }, [
        h('span', { class: 'doe-dot', style: 'background:' + colourOf(key) }),
        h('span', { text: nameOf(key) }),
        (LABELS[key] || {}).why
          ? h('span', { class: 'doe-why', text: ' — ' + LABELS[key].why })
          : null
      ]));
    });
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
