/* Every week, one row. The index over the per-week pages.
 *
 * Columns are the test steps, so a step reads down the page and a week reads
 * across it. Which steps appear is decided by the data rather than hard-coded:
 * the line gained L10 stations mid-quarter and will gain more, and a fixed
 * column list would silently omit them.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_WEEKLY__ || {};
  var WEEKS = DATA.weeks || [];

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
  function tone(v) {
    if (v == null) return '';
    return v >= 0.9 ? 'good' : v >= 0.6 ? 'warn' : 'bad';
  }

  /* Steps in line order, taken from whichever weeks have them. */
  function steps() {
    var seen = [], labels = {};
    WEEKS.forEach(function (week) {
      (week.rows || []).forEach(function (row) {
        if (seen.indexOf(row.key) === -1) seen.push(row.key);
        labels[row.key] = row.label;
      });
    });
    return seen.map(function (key) { return { key: key, label: labels[key] }; });
  }

  /* The rolled cell: the product, how thin it is, and what it is over.
   *
   * It used to be withheld below the cohort floor, and 2026-W36 showed why
   * that was the wrong caution — MLT 40% and HTT 78.9% both on the row, and a
   * dash where their product belonged. A blank is not a smaller claim than a
   * number; it is a different one, and it was read as "the week was not
   * measured" twice in a day. So the product publishes, marked, with the two
   * cohorts under it: 31.6% over ten units and nineteen is a fact a reader can
   * discount for themselves, which a dash gives them no way to do.
   *
   * Still a dash when a half is missing. The column is called MLT × HTT, and
   * 2026-W31's MLT-only 54.5% under that heading would be a different measure
   * wearing the headline's name. */
  function rolledCell(totals) {
    var td = h('td', { class: 'n y ' + tone(totals.rolledFpy) });
    var thin = totals.rolledThin || [];
    var missing = totals.rolledMissing || [];
    td.appendChild(document.createTextNode(pct(totals.rolledFpy)));

    if (totals.rolledFpy == null) {
      /* No product to publish. Which half, and why. */
      td.title = missing.length
        ? 'No rolled figure — ' + missing.join(' and ') + ' had no first-pass '
          + 'cohort this week, and one station is not a product of two.'
        : 'No rolled figure for this week.';
      if (missing.length) {
        td.appendChild(h('span', { class: 'sub',
                                   text: 'no ' + missing.join('/') }));
      }
      return td;
    }

    if (!thin.length) {
      td.title = (totals.rolledOver || []).join(' × ') + ', multiplied';
      return td;
    }

    /* Published and marked, the same way a thin step's own yield is. */
    td.className += ' thin';
    td.appendChild(h('span', { class: 'thin-mark',
      title: 'thin: ' + thin.map(function (step) {
        return step.label + ' over ' + step.newUnits + ' first-time unit' +
          (step.newUnits === 1 ? '' : 's');
      }).join(', ') + ' — fewer than ' + DATA.minCohort +
        ', so the product moves a long way on one unit',
      text: '\u2009*' }));
    td.appendChild(h('span', { class: 'sub', text: thin.map(function (step) {
      return step.label + ' ' + step.newUnits;
    }).join(' · ') + ' new' }));
    td.title = 'Thin: ' + thin.map(function (step) {
      return step.label + ' ran ' + step.units + ' unit' +
        (step.units === 1 ? '' : 's') + ', ' + step.newUnits +
        ' of them new to the step';
    }).join('; ') + '. Under ' + DATA.minCohort + ' first-time units the ' +
      'yield moves a long way on one unit, so the product publishes with its ' +
      'cohorts rather than being quoted as though it were solid.';
    return td;
  }

  function render() {
    var cols = steps();

    var head = h('tr', {});
    head.appendChild(h('th', { scope: 'col', text: 'Week' }));
    head.appendChild(h('th', { scope: 'col', class: 'n',
                               text: 'Rolled MLT \u00d7 HTT' }));
    cols.forEach(function (col) {
      head.appendChild(h('th', { scope: 'col', class: 'n', text: col.label }));
    });
    head.appendChild(h('th', { scope: 'col', class: 'n', text: 'Unit runs' }));
    byId('head').innerHTML = '';
    byId('head').appendChild(head);

    var body = byId('body');
    body.innerHTML = '';
    WEEKS.forEach(function (week) {
      var by = {};
      (week.rows || []).forEach(function (row) { by[row.key] = row; });

      var tr = h('tr', {});
      var cell = h('td', {}, [
        h('a', { class: 'wk-link', href: 'week.html#week=' + week.week,
                 text: week.week }),
        h('span', { class: 'sub', text: week.from.slice(5) + ' – ' +
          week.endsOn.slice(5) + (week.partial ? ' · running' : '') })
      ]);
      tr.appendChild(cell);
      tr.appendChild(rolledCell(week.totals || {}));

      cols.forEach(function (col) {
        var row = by[col.key];
        var td = h('td', { class: 'n' });
        if (!row) {
          td.textContent = '—';
        } else if (row.fpy == null) {
          /* No first pass to take a yield over — either the stage reports
             quantity only, or not one unit this week was new to it. The count
             is the honest answer to both. */
          td.appendChild(h('span', { class: 'countonly',
                                     text: row.units + ' u' }));
          td.title = row.countsOnly
            ? 'Quantity only — chassis and rack level, in bring-up'
            : 'No unit was new to this step this week — every one had run it '
              + 'before, so there is no first pass to measure';
        } else {
          td.className = 'n y ' + tone(row.fpy);
          td.appendChild(document.createTextNode(pct(row.fpy)));
          /* A thin cohort still publishes its yield — L10 and L11 asked for
             it — but says so, because 50% of two units and 50% of two hundred
             are the same number and not the same fact. Marked on the number,
             not instead of it.

             The question is about the yield's OWN denominator, which is
             first-time units — so `readable`, not `thinCohort`. Following
             `thinCohort`, the size of the week's window, left MLT in 2026-W36
             reading as a solid 40% with "90 u" under it when the 40% was four
             units of the ten that were new: the one thin figure on the page
             whose thinness was invisible. `thinCohort` is still honoured, so an
             older bundle keeps the marks it had. */
          if (row.readable === false || row.thinCohort === true) {
            td.className += ' thin';
            td.appendChild(h('span', { class: 'thin-mark',
              title: 'fewer than ' + DATA.minCohort + ' first-time units — the '
                   + 'yield is published but it moves a long way on one unit, '
                   + 'and it stays out of the rolled figure',
              text: '\u2009*' }));
          }
          /* The count under the number is that number's denominator, not the
             week's traffic. The two were the same thing until repeats began to
             outnumber new units, and then "40%" over "90 u" was two facts that
             did not belong to each other. */
          td.appendChild(h('span', { class: 'sub',
            text: row.newUnits != null && row.newUnits !== row.units
              ? row.newUnits + ' new of ' + row.units + ' u'
              : row.units + ' u' }));
        }
        tr.appendChild(td);
      });

      tr.appendChild(h('td', { class: 'n', text: week.hasDetail
        ? String((week.units || []).length) : 'summary only' }));
      body.appendChild(tr);
    });

    byId('caption').textContent = WEEKS.length + ' weeks. ' +
      'A cell shows first-pass yield over the count under it, and that count is ' +
      'the yield\u2019s own denominator: first-pass counts a unit only on its ' +
      'first ever run at that step, so \u201c10 new of 90 u\u201d is a yield ' +
      'over ten. A * marks a yield over fewer than ' + DATA.minCohort +
      ' first-time units — published since L10 and L11 wanted their numbers, ' +
      'because a blank read as nothing having been tested, and marked because ' +
      'it moves a long way on one unit. A grey count is a step where no unit was on its first run, so ' +
      'there is no first pass to measure. The rolled column carries the same ' +
      'mark for the same reason — a product is as thin as its thinnest term, ' +
      'and the cohorts it was taken over are printed under it. A dash there ' +
      'means one half of MLT \u00d7 HTT had no first-pass cohort at all.';

    byId('meta').textContent = WEEKS.length
      ? WEEKS[WEEKS.length - 1].from + ' → ' + WEEKS[0].endsOn : '';

    var info = DATA.build || {};
    var slot = byId('build');
    if (info.release) {
      slot.appendChild(h('span', { class: 'build-release', text: info.release }));
    }
    if (info.commit) {
      slot.appendChild(info.commitUrl
        ? h('a', { class: 'build-commit', href: info.commitUrl,
                   target: '_blank', rel: 'noopener noreferrer',
                   text: info.commit })
        : h('span', { class: 'build-commit', text: info.commit }));
    }

    byId('sources').appendChild(h('p', { class: 'src', text:
      'Rolled first-pass is MLT \u00d7 HTT — the accumulated module yield, and '
      + 'only that. TIM has its own column and is not in the product: it '
      + 'started reporting in W34, and rolling it in would have moved every '
      + 'week’s headline for a reason that has nothing to do with the line. '
      + 'VBB provisioning is '
      + 'excluded: a real stage, but not part of the product test flow. WST '
      + 'and FT are Sigurd’s and are asked for weekly in '
      + '#production-test-eng; they appear on a week’s page once '
      + 'reported. Source: ' + ((DATA.source || {}).label ||
        'the station controllers') + '.' }));
  }

  function init() {
    if (!WEEKS.length) {
      byId('caption').textContent = 'No data — run `make weekly`.';
      return;
    }
    render();
    /* One table, one button. Every week is on screen at once here, so nothing
     * about the filename or the table depends on when it is clicked. */
    if (window.FactoryCsv) {
      window.FactoryCsv.attach(byId('csv-summary'), {
        table: byId('summary'),
        name: 'weekly-summary-' + WEEKS.length + '-weeks.csv',
        label: 'Download CSV',
        title: 'every week in this table, as a CSV for Excel'
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
