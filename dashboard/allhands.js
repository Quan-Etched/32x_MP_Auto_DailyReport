/* Five stages, one yield each, over any range of UTC days.
 *
 * WHY EVERY NUMBER HERE IS COUNTED PER UNIT
 * The temptation on a slide is to multiply station rates: MLT 77% × HTT 83% =
 * 64%. It is wrong, and wrong in the direction that flatters nobody — HTT runs
 * only on modules that cleared MLT, some of them on an earlier day, so the two
 * rates are over different populations. Counting the units gives 66.9% for the
 * same day. So every figure on this page is built by walking the runs and
 * asking, per serial, what happened to it.
 *
 * WHAT "ENTERED" MEANS
 * A stage's denominator is units graded at its first station — MLT for L6, FAT
 * for L10, Provision for L11. A unit that shows up only at a later station
 * arrived mid-stage, and counting it as an input would credit the stage with
 * work it did not see start.
 *
 * WS AND FT ARE HAND-REPORTED
 * They are Sigurd's, they arrive by message, and they are typed into
 * weekly/external_yields.json with the day they describe. So they carry a
 * number only when the chosen range contains that day, and say what they are
 * otherwise. Same rule the weekly page applies (build_fpy._external_in), and
 * the reason is that a figure shown on every range is one week's number wearing
 * every other week's label — on an all-hands slide, the worst place for it.
 *
 * Plain ES5, no build step, no dependencies.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RUNS__ || {};
  var RUNS = DATA.runs || [];
  var NAMES = DATA.testNames || [];
  var TSTATUS = DATA.testStatuses || [];
  var LABELS = DATA.stationLabels || {};
  var EXTERNAL = DATA.external || {};

  var CONTAINERS = {};
  (DATA.containerNames || []).forEach(function (i) { CONTAINERS[i] = true; });

  /* The five boxes, in line order.
   *
   * `stations` is every station inside the stage and `entry` is the one a unit
   * is counted as arriving at. L6 is MLT then HTT — TIM is deliberately not in
   * it, because the summary flow chart's accumulated yield is MLT × HTT and two
   * pages disagreeing about what "L6 combined" means would be worse than this
   * page being slightly incomplete. TIM has its own row in the table below. */
  var STAGES = [
    { key: 'wst',  label: 'WS',  external: 'wst', note: 'Wafer sort · Sigurd' },
    { key: 'ft',   label: 'FT',  external: 'ft',  note: 'Final test · Sigurd' },
    { key: 'l6',   label: 'MLT + HTT', stations: ['mlt', 'htt'], entry: 'mlt',
      note: 'Module test, combined' },
    { key: 'l10',  label: 'L10', stations: ['l10_fat', 'l10_sft', 'l10_rin'],
      entry: 'l10_fat', note: 'FAT · SFT · Run-in' },
    { key: 'l11',  label: 'L11', stations: ['l11_provision', 'l11_test'],
      entry: 'l11_provision', note: 'Provision · test' }
  ];

  /* Stations that are not in one of the five boxes but are worth a row. */
  var EXTRA_ROWS = ['tim', 'vbb_provision', 'slt', 'l10_2u'];

  var PARETO_TOP = 12;

  var view = { from: null, to: null, mode: 'graph' };

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
  function labelOf(key) { return LABELS[key] || key; }
  function pct(rate) {
    return rate == null ? null : (Math.round(rate * 1000) / 10) + '%';
  }

  /* The run's UTC day, from its own epoch. Never the bundle's `day`, which is
   * factory-local — it disagrees on about 40% of rows. */
  function utcDay(run) {
    return run.t ? new Date(run.t * 1000).toISOString().slice(0, 10) : null;
  }

  var DAYS = (function () {
    var seen = {};
    RUNS.forEach(function (run) {
      var day = utcDay(run);
      if (day) seen[day] = true;
    });
    return Object.keys(seen).sort();
  })();

  function shift(day, days) {
    var at = new Date(day + 'T00:00:00Z');
    at.setUTCDate(at.getUTCDate() + days);
    return at.toISOString().slice(0, 10);
  }

  function inRange() {
    return RUNS.filter(function (run) {
      var day = utcDay(run);
      return day && day >= view.from && day <= view.to;
    }).sort(function (a, b) { return (a.t || 0) - (b.t || 0); });
  }

  /* ------------------------------------------------------- per-unit history */

  /* serial -> station -> the verdicts it got there, in time order. Everything
   * on this page is computed off this: a yield, a recovery, a Pareto. */
  function byUnit(rows) {
    var out = {};
    rows.forEach(function (run) {
      if (!run.d) return;
      var unit = out[run.d] || (out[run.d] = {});
      (unit[run.k] || (unit[run.k] = [])).push(run);
    });
    return out;
  }

  function graded(run) { return run.s === 'pass' || run.s === 'fail'; }

  function stageYield(units, stage) {
    if (!stage.stations) return null;
    var out = { entered: 0, clean: 0, failedSome: 0, incomplete: 0,
                recovered: 0, stillOut: 0, attempts: 0, per: {} };
    stage.stations.forEach(function (station) {
      out.per[station] = { pass: 0, fail: 0 };
    });
    Object.keys(units).forEach(function (serial) {
      var unit = units[serial];
      var atEntry = (unit[stage.entry] || []).filter(graded);
      if (!atEntry.length) return;
      out.entered += 1;

      /* First pass, not final state.
       *
       * A unit is clean only if it never failed at any station in the stage —
       * which is what the label on the box says, and the two have to agree.
       * Counting the last verdict instead would fold recoveries into the yield
       * and make the recovery table below a second telling of the same story;
       * this way the two compose, and "clean + recovered" is the throughput. */
      var failedEver = false, sawAll = true, endedClean = true;
      stage.stations.forEach(function (station) {
        var runs = (unit[station] || []).filter(graded);
        if (!runs.length) { sawAll = false; endedClean = false; return; }
        var everFailed = runs.some(function (run) { return run.s === 'fail'; });
        out.per[station][everFailed ? 'fail' : 'pass'] += 1;
        if (everFailed) failedEver = true;
        if (runs[runs.length - 1].s !== 'pass') endedClean = false;
        out.attempts += runs.length - 1;
      });
      if (failedEver) {
        out.failedSome += 1;
        /* Through the WHOLE stage after rework — every station ending on a
         * pass, not merely one of them recovering.
         *
         * The first version counted a recovery at any single station, and it
         * disagreed with the recovery table on the same screen: the L10 box
         * claimed nine units came back while the table said none. Both were
         * describing something true and only the table's rule answers "back in
         * production", because a unit that recovered at FAT and is still
         * failing SFT has not gone anywhere. One rule now, so the two agree by
         * construction rather than by luck. */
        if (endedClean) out.recovered += 1; else out.stillOut += 1;
      } else if (!sawAll) out.incomplete += 1;
      else out.clean += 1;
    });
    out.rate = out.entered ? out.clean / out.entered : null;
    return out;
  }

  /* --------------------------------------------------------------- pareto */

  /* Per-run prefix on a controller test id: 2d257ec5_validate_… and
   * e4306c91_validate_… are one test failing twice. Same expression as
   * rootcause.RUN_PREFIX, so a signature here matches one on the station page. */
  var RUN_PREFIX = /^[0-9a-f]{6,10}_(chip\d+_|sohu_)?/i;

  function pareto(rows) {
    var counts = {};
    var total = 0;
    rows.forEach(function (run) {
      if (run.s !== 'fail') return;
      var seen = {};
      (run.T || []).forEach(function (test) {
        var status = TSTATUS[test[1]];
        if (status !== 'fail' && status !== 'error') return;
        if (CONTAINERS[test[0]]) return;
        var name = String(NAMES[test[0]] || '').replace(RUN_PREFIX, '');
        if (!name || seen[name]) return;
        seen[name] = true;
        var entry = counts[name] || (counts[name] = { name: name, units: 0,
                                                     stations: {} });
        entry.units += 1;
        entry.stations[run.k] = (entry.stations[run.k] || 0) + 1;
        total += 1;
      });
    });
    var rows_ = Object.keys(counts).map(function (name) { return counts[name]; })
      .sort(function (a, b) { return b.units - a.units || a.name.localeCompare(b.name); });
    var running = 0;
    rows_.forEach(function (row) {
      row.share = total ? row.units / total : 0;
      running += row.share;
      row.cumulative = running;
      row.where = Object.keys(row.stations).sort(function (a, b) {
        return row.stations[b] - row.stations[a];
      }).map(labelOf).join(', ');
    });
    return { rows: rows_, total: total };
  }

  /* ------------------------------------------------------------- the boxes */

  /* How long a figure is carried before it stops being shown. Same number as
   * build_fpy.CARRY_DAYS, and the two have to agree — one page carrying a
   * figure the other has dropped is the sort of thing nobody notices until a
   * meeting. */
  var CARRY_DAYS = 21;

  /* A hand-reported figure: this range's, carried forward, or not shown.
   *
   * Forward only. "FT: no new update" is a normal message, so a range with no
   * figure of its own shows the last one and marks it — a dash would read as
   * "there is no such measurement". A figure dated after the range is not shown
   * at all, because that is the case the rule exists for: a number pinned to
   * every window put August's WST on a June week that predated the line. */
  function externalFor(stage) {
    var entry = EXTERNAL[stage.external] || {};
    var rate = entry['yield'];
    if (rate === null || rate === undefined) {
      return { rate: null, state: 'absent', why: 'never reported' };
    }
    var asOf = entry.asOf;
    if (!asOf) {
      return { rate: null, state: 'absent', why: 'the figure carries no date' };
    }
    if (asOf >= view.from && asOf <= view.to) {
      return { rate: rate, state: 'fresh', asOf: asOf, source: entry.source };
    }
    if (asOf > view.to) {
      return { rate: null, state: 'ahead', asOf: asOf,
               why: 'first reported for ' + asOf };
    }
    var age = Math.round(
      (Date.parse(view.to + 'T00:00:00Z') - Date.parse(asOf + 'T00:00:00Z'))
      / 86400000);
    if (age > CARRY_DAYS) {
      return { rate: null, state: 'stale', asOf: asOf, age: age,
               why: 'last reported ' + age + ' days before this range ended' };
    }
    return { rate: rate, state: 'carried', asOf: asOf, age: age,
             source: entry.source };
  }

  function renderStages(units, rows) {
    var host = byId('stages');
    host.innerHTML = '';
    STAGES.forEach(function (stage) {
      var box = h('div', { class: 'stage' });
      box.appendChild(h('span', { class: 'stage-k', text: stage.label }));

      if (stage.external) {
        var ext = externalFor(stage);
        box.appendChild(h('strong', {
          class: 'stage-v' + (ext.rate === null ? ' absent' : '')
                 + (ext.state === 'carried' ? ' carried' : '')
        }, [
          document.createTextNode(ext.rate === null ? '—' : pct(ext.rate)),
          /* The small sign. On the number itself, because that is what gets
           * screenshotted off this page. */
          ext.state === 'carried'
            ? h('span', { class: 'carried-mark',
                          title: 'carried forward from ' + ext.asOf + ' — no '
                                 + 'new figure reported since',
                          text: '↩' })
            : null
        ]));
        box.appendChild(h('span', { class: 'stage-s', text: stage.note }));
        box.appendChild(h('span', { class: 'stage-s dim', text:
          ext.state === 'fresh' ? 'reported for ' + ext.asOf
          : ext.state === 'carried'
            ? 'carried forward from ' + ext.asOf + ' · ' + ext.age +
              ' days old, no new figure since'
          : 'not shown · ' + ext.why }));
        if (ext.rate !== null && ext.source) {
          box.appendChild(h('span', { class: 'stage-s dim', text: ext.source }));
        }
      } else {
        var y = stageYield(units, stage);
        box.appendChild(h('strong', {
          class: 'stage-v' + (y && y.rate !== null ? '' : ' absent'),
          text: y && y.rate !== null ? pct(y.rate) : '—'
        }));
        box.appendChild(h('span', { class: 'stage-s', text: stage.note }));
        if (y && y.entered) {
          box.appendChild(h('span', { class: 'stage-s', text:
            y.clean + ' clean of ' + plural(y.entered, 'unit') + ' in' }));
          if (y.failedSome) {
            box.appendChild(h('span', { class: 'stage-s dim',
              text: y.failedSome + ' failed somewhere in the stage' +
                    (y.recovered ? ', ' + y.recovered + ' of them through '
                                          + 'after a retest' : '') }));
          }
          /* First pass plus recoveries: what the stage actually delivered, as
           * against what it delivered without rework. Both wanted, and the
           * gap between them is the cost of the rework. */
          if (y.recovered) {
            box.appendChild(h('span', { class: 'stage-s', text:
              'with retests: ' + pct((y.clean + y.recovered) / y.entered) +
              ' (' + (y.clean + y.recovered) + ' of ' + y.entered + ')' }));
          }
          /* Where the losses are.
           *
           * A multi-station stage can read 0% while no single station is near
           * zero — L10 does exactly that, because a clean sheet needs FAT and
           * SFT and Run-in and almost nothing clears all three yet. Without
           * this line "L10 0%" invites the conclusion that L10 yields nothing,
           * when the honest reading is that the stage is not finishing. */
          if (stage.stations.length > 1) {
            box.appendChild(h('span', { class: 'stage-s dim', text:
              stage.stations.map(function (station) {
                var one = y.per[station];
                var graded_ = one.pass + one.fail;
                return labelOf(station).replace(/^L1[01] /, '') + ' ' +
                       (graded_ ? pct(one.pass / graded_) : '—');
              }).join(' · ') }));
          }
          /* A unit still mid-stage is neither a pass nor a fail, and lumping it
           * either way moves the number. Said out loud instead. */
          if (y.incomplete) {
            box.appendChild(h('span', { class: 'stage-s dim',
              text: y.incomplete + ' still part-way through' }));
          }
        } else {
          box.appendChild(h('span', { class: 'stage-s dim',
                                      text: 'no units entered in this range' }));
        }
      }
      host.appendChild(box);
    });
  }

  /* ----------------------------------------------------------- recovery table */

  var RECOVERY_COLUMNS = ['Stage', 'Units that failed', 'Back in production',
                          'Still out', 'Recovery %', 'Extra runs'];

  /* One computation behind the boxes and this table.
   *
   * They disagreed at first — the L6 box said three units came back and the
   * table said six — because the table counted every unit that failed either
   * station while the box counted only units that entered at MLT. Both were
   * true and the pair was unreadable. Now the table is over the boxes' own
   * population, which buys an invariant worth having: entered = clean +
   * recovered + still out + part-way through, and it is asserted below.
   *
   * A station that is not inside one of the five stages gets a stage of its
   * own, entered at itself, so TIM and VBB keep their rows. */
  function recoveryRows(units) {
    var out = [];
    STAGES.filter(function (stage) { return stage.stations; })
      .forEach(function (stage) {
        out.push([stage.label, stageYield(units, stage)]);
      });
    EXTRA_ROWS.forEach(function (station) {
      var got = stageYield(units, { stations: [station], entry: station });
      if (got && got.failedSome) out.push([labelOf(station), got]);
    });
    return out.filter(function (pair) {
      return pair[1] && pair[1].failedSome;
    });
  }

  function renderRecovery(units) {
    var head = byId('recovery-head'), body = byId('recovery-body');
    head.innerHTML = ''; body.innerHTML = '';
    var rows = recoveryRows(units);

    head.appendChild(h('tr', {}, RECOVERY_COLUMNS.map(function (title, at) {
      return h('th', { class: at ? 'num' : '', text: title });
    })));
    rows.forEach(function (pair) {
      var got = pair[1];
      var rate = got.failedSome ? got.recovered / got.failedSome : null;
      body.appendChild(h('tr', {}, [
        h('td', { text: pair[0] }),
        h('td', { class: 'num', text: String(got.failedSome) }),
        h('td', { class: 'num tone-pass', text: String(got.recovered) }),
        h('td', { class: 'num tone-fail', text: String(got.stillOut) }),
        h('td', { class: 'num', text: pct(rate) || '—' }),
        h('td', { class: 'num', text: String(got.attempts) })
      ]));
    });

    var all = rows.reduce(function (acc, pair) {
      acc.failed += pair[1].failedSome; acc.recovered += pair[1].recovered;
      return acc;
    }, { failed: 0, recovered: 0 });
    byId('recovery-sub').textContent = all.failed
      ? all.recovered + ' of ' + plural(all.failed, 'unit') +
        ' that entered a stage and failed inside it came out the other side — ' +
        pct(all.recovered / all.failed) + ' back into production. Back means ' +
        'every station in the stage ending on a pass: a unit that recovered at ' +
        'one and is still failing another has not gone anywhere. Same ' +
        'population as the boxes above, so for each row clean + back + still ' +
        'out + part-way accounts for everything that entered.'
      : 'No unit that entered a stage failed inside it in this range.';

    if (window.FactoryCsv) {
      var host = byId('recovery-download');
      host.innerHTML = '';
      window.FactoryCsv.attach(host, {
        table: function () { return byId('recovery'); },
        name: function () {
          return 'recovery-' + view.from + '_to_' + view.to + '.csv';
        },
        label: 'Download CSV'
      });
    }
  }

  /* ------------------------------------------------------------- the pareto */

  function renderPareto(rows) {
    var got = pareto(rows);
    var top = got.rows.slice(0, PARETO_TOP);
    var rest = got.rows.slice(PARETO_TOP);

    byId('pareto-sub').textContent = got.total
      ? plural(got.rows.length, 'distinct failing test') + ' across ' +
        got.total + ' unit-failures. The top ' + top.length + ' account for ' +
        pct(top.reduce(function (a, r) { return a + r.share; }, 0)) + '.'
      : 'No failures in this range.';

    var plot = byId('pareto-plot');
    var wrap = byId('pareto-table-wrap');
    plot.innerHTML = '';
    plot.hidden = view.mode !== 'graph';
    wrap.hidden = view.mode === 'graph';

    if (view.mode === 'graph') {
      var most = top.length ? top[0].units : 1;
      top.forEach(function (row) {
        plot.appendChild(h('div', { class: 'bar-row' }, [
          h('span', { class: 'bar-k', text: row.name, title: row.name }),
          h('span', { class: 'bar-track' }, [
            h('span', { class: 'bar-fill',
                        style: 'width:' + (100 * row.units / most) + '%' })
          ]),
          h('span', { class: 'bar-n', text: String(row.units) }),
          h('span', { class: 'bar-c', text: pct(row.cumulative) }),
          h('span', { class: 'bar-w', text: row.where })
        ]));
      });
      if (rest.length) {
        /* Named, not dropped: "and 40 others" is the difference between a
         * Pareto and a top-twelve list. */
        plot.appendChild(h('p', { class: 'cz-note', text:
          'and ' + plural(rest.length, 'more signature') + ', ' +
          rest.reduce(function (a, r) { return a + r.units; }, 0) +
          ' unit-failures between them. Switch to the table for all of them.' }));
      }
    } else {
      var head = byId('pareto-head'), body = byId('pareto-body');
      head.innerHTML = ''; body.innerHTML = '';
      head.appendChild(h('tr', {}, ['Failing test', 'Unit failures', 'Share',
                                    'Cumulative', 'Where']
        .map(function (title, at) {
          return h('th', { class: at && at < 4 ? 'num' : '', text: title });
        })));
      got.rows.forEach(function (row) {
        body.appendChild(h('tr', {}, [
          h('td', { class: 'mono', text: row.name }),
          h('td', { class: 'num', text: String(row.units) }),
          h('td', { class: 'num', text: pct(row.share) }),
          h('td', { class: 'num', text: pct(row.cumulative) }),
          h('td', { text: row.where })
        ]));
      });
    }

    var mode = byId('pareto-mode');
    mode.innerHTML = '';
    [['graph', 'Graph'], ['table', 'Table']].forEach(function (pair) {
      var button = h('button', {
        type: 'button',
        class: 'view-toggle' + (view.mode === pair[0] ? ' on' : ''),
        text: pair[1]
      });
      button.addEventListener('click', function () {
        view.mode = pair[0];
        writeHash();
        render();
      });
      mode.appendChild(button);
    });

    if (window.FactoryCsv) {
      var host = byId('pareto-download');
      host.innerHTML = '';
      var button = h('button', { type: 'button', class: 'view-toggle',
                                 text: 'Download CSV' });
      button.addEventListener('click', function () {
        /* Every signature, not the twelve on screen — the graph is a summary
         * and the file is the evidence. */
        var lines = [['Failing_Test', 'Unit_Failures', 'Share_Pct',
                      'Cumulative_Pct', 'Stations']];
        got.rows.forEach(function (row) {
          lines.push([row.name, row.units,
                      Math.round(row.share * 1000) / 10,
                      Math.round(row.cumulative * 1000) / 10, row.where]);
        });
        window.FactoryCsv.download(
          'pareto-' + view.from + '_to_' + view.to + '.csv',
          window.FactoryCsv.toCsv(lines));
      });
      host.appendChild(button);
    }
  }

  /* ------------------------------------------------- week over week ---
   *
   * The accumulated L6 yield per ISO week: MLT and HTT, per unit, the same
   * computation the box above uses. TIM is not in it — the summary flow chart's
   * accumulated figure is MLT × HTT and this has to be the same quantity, or
   * the trend and the headline are two different measures on one site.
   *
   * DELIBERATELY NOT RANGE-DRIVEN
   * Every complete week in the bundle, plus the one running. A trend that moved
   * when somebody narrowed the day picker would not be a trend — and with the
   * default seven-day range it would be a single bar, which is a number with a
   * chart drawn round it.
   */
  function isoWeek(day) {
    /* Thursday of the same week decides the year and the number, which is what
     * makes 29 December and 1 January land in the right places. */
    var at = new Date(day + 'T00:00:00Z');
    var dow = (at.getUTCDay() + 6) % 7;          /* Monday = 0 */
    at.setUTCDate(at.getUTCDate() - dow + 3);
    var firstThursday = new Date(Date.UTC(at.getUTCFullYear(), 0, 4));
    var fdow = (firstThursday.getUTCDay() + 6) % 7;
    firstThursday.setUTCDate(firstThursday.getUTCDate() - fdow + 3);
    var week = 1 + Math.round(
      (at - firstThursday) / (7 * 86400000));
    return at.getUTCFullYear() + '-W' + (week < 10 ? '0' + week : week);
  }

  function weekly() {
    var buckets = {};
    RUNS.forEach(function (run) {
      var day = utcDay(run);
      if (!day) return;
      var key = isoWeek(day);
      (buckets[key] || (buckets[key] = [])).push(run);
    });
    var l6 = STAGES.filter(function (stage) { return stage.key === 'l6'; })[0];
    var last = l6.stations[l6.stations.length - 1];
    return Object.keys(buckets).sort().map(function (key) {
      var got = stageYield(byUnit(buckets[key]), l6);
      /* A combined yield needs both stations to have run.
       *
       * Before HTT started, weeks came out as 0% over dozens of units — every
       * unit sat in "part-way through", so clean was zero and the rate read as
       * a total loss. Eight leading zeros on an all-hands chart is a story
       * about the line collapsing, and what actually happened is that the
       * second half of the stage did not exist yet. */
      var tail = got ? got.per[last] : null;
      var ran = tail ? tail.pass + tail.fail : 0;
      return {
        week: key,
        entered: got ? got.entered : 0,
        clean: got ? got.clean : 0,
        recovered: got ? got.recovered : 0,
        incomplete: got ? got.incomplete : 0,
        rate: ran && got ? got.rate : null,
        withRetests: ran && got && got.entered
          ? (got.clean + got.recovered) / got.entered : null,
        why: ran ? '' : 'HTT did not run this week'
      };
    }).filter(function (row) { return row.entered; });
  }

  function renderWeekly() {
    var host = byId('weekly-plot');
    var wrap = byId('weekly-table-wrap');
    if (!host) return;
    var rows = weekly();

    byId('weekly-sub').textContent = rows.length
      ? 'MLT and HTT combined, per unit, for every week the controllers cover. ' +
        'TIM is not counted — this is the same quantity the flow chart calls the ' +
        'accumulated L6 yield. Not affected by the range above.'
      : 'No week in the bundle has a unit through MLT.';

    host.innerHTML = '';
    host.hidden = view.mode !== 'graph';
    wrap.hidden = view.mode === 'graph';

    if (view.mode === 'graph') {
      /* Scaled to 100, not to the tallest bar: a yield chart whose axis floats
       * makes 44% and 57% look like a collapse and a recovery. */
      rows.forEach(function (row) {
        host.appendChild(h('div', { class: 'wk-bar' }, [
          h('span', { class: 'wk-lab', text: row.week }),
          h('span', { class: 'wk-track' }, [
            h('span', { class: 'wk-fill',
                        style: 'width:' + (100 * (row.rate || 0)) + '%' }),
            row.withRetests > row.rate
              ? h('span', { class: 'wk-ghost',
                            style: 'width:' + (100 * row.withRetests) + '%' })
              : null
          ]),
          h('strong', { class: 'wk-pct' + (row.rate === null ? ' absent' : ''),
                        text: pct(row.rate) || '—' }),
          h('span', { class: 'wk-n', text: row.why
            ? row.why : row.clean + ' of ' + row.entered })
        ]));
      });
      host.appendChild(h('p', { class: 'cz-note', text:
        'Solid is first pass. The lighter bar behind it, where there is one, is ' +
        'the same week once retests are counted.' }));
    } else {
      var head = byId('weekly-head'), body = byId('weekly-body');
      head.innerHTML = ''; body.innerHTML = '';
      head.appendChild(h('tr', {}, ['Week', 'Units in', 'Clean first pass',
                                    'First-pass yield', 'With retests', 'Note']
        .map(function (title, at) {
          return h('th', { class: at ? 'num' : '', text: title });
        })));
      rows.forEach(function (row) {
        body.appendChild(h('tr', {}, [
          h('td', { text: row.week }),
          h('td', { class: 'num', text: String(row.entered) }),
          h('td', { class: 'num', text: String(row.clean) }),
          h('td', { class: 'num', text: pct(row.rate) || '—' }),
          h('td', { class: 'num', text: pct(row.withRetests) || '—' }),
          h('td', { text: row.why })
        ]));
      });
    }

    var host2 = byId('weekly-download');
    if (host2 && window.FactoryCsv) {
      host2.innerHTML = '';
      var button = h('button', { type: 'button', class: 'view-toggle',
                                 text: 'Download CSV' });
      button.addEventListener('click', function () {
        var lines = [['Week', 'Units_In', 'Clean_First_Pass', 'Recovered',
                      'First_Pass_Yield_Pct', 'With_Retests_Pct']];
        rows.forEach(function (row) {
          lines.push([row.week, row.entered, row.clean, row.recovered,
                      row.rate === null ? '' : Math.round(row.rate * 1000) / 10,
                      row.withRetests === null ? ''
                        : Math.round(row.withRetests * 1000) / 10]);
        });
        window.FactoryCsv.download('l6-yield-by-week.csv',
                                   window.FactoryCsv.toCsv(lines));
      });
      host2.appendChild(button);
    }
  }

  /* ---------------------------------------------------------------- chrome */

  function renderQuick() {
    var host = byId('quick');
    host.innerHTML = '';
    if (!DAYS.length) return;
    var last = DAYS[DAYS.length - 1];
    [['Last 7 days', shift(last, -6)], ['Last 30 days', shift(last, -29)],
     ['Everything', DAYS[0]]].forEach(function (pair) {
      var from = pair[1] < DAYS[0] ? DAYS[0] : pair[1];
      var on = view.from === from && view.to === last;
      var button = h('button', {
        type: 'button', class: 'view-toggle' + (on ? ' on' : ''), text: pair[0]
      });
      button.addEventListener('click', function () {
        view.from = from; view.to = last; writeHash(); render();
      });
      host.appendChild(button);
    });
  }

  function writeHash() {
    location.replace('#from=' + view.from + '&to=' + view.to +
                     '&mode=' + view.mode);
  }

  function readHash() {
    var hash = location.hash || '';
    var from = /from=(\d{4}-\d{2}-\d{2})/.exec(hash);
    var to = /to=(\d{4}-\d{2}-\d{2})/.exec(hash);
    var mode = /mode=(graph|table)/.exec(hash);
    var last = DAYS.length ? DAYS[DAYS.length - 1] : null;
    view.from = (from && from[1]) || (last ? shift(last, -6) : null);
    if (DAYS.length && view.from < DAYS[0]) view.from = DAYS[0];
    view.to = (to && to[1]) || last;
    view.mode = (mode && mode[1]) || 'graph';
  }

  function render() {
    if (view.from && view.to && view.from > view.to) {
      var swap = view.from; view.from = view.to; view.to = swap;
    }
    byId('from').value = view.from;
    byId('to').value = view.to;
    byId('range-sub').textContent = DAYS.length
      ? 'The controllers hold ' + DAYS[0] + ' to ' + DAYS[DAYS.length - 1] +
        '. Day resolution, UTC.'
      : 'No runs in the bundle.';
    byId('meta').textContent = view.from + ' → ' + view.to + ' UTC';

    var rows = inRange();
    var units = byUnit(rows);
    renderQuick();
    renderStages(units, rows);
    renderRecovery(units);
    renderWeekly();
    renderPareto(rows);

    var ext = STAGES.filter(function (s) { return s.external; })
      .map(function (s) {
        var got = externalFor(s);
        return s.label + ': ' + (
          got.state === 'fresh' ? pct(got.rate) + ' as of ' + got.asOf
          : got.state === 'carried'
            ? pct(got.rate) + ' carried from ' + got.asOf + ' (' + got.age +
              ' days old)'
          : 'not shown, ' + got.why);
      });
    byId('external-note').textContent =
      'WS and FT are hand-reported into weekly/external_yields.json — ' +
      ext.join('; ') + '. A figure with no newer one is carried forward for up ' +
      'to ' + CARRY_DAYS + ' days and marked ↩, because “no new update” is a ' +
      'normal week and a dash would read as “there is no such measurement”. It ' +
      'is never carried backward onto an earlier range, and past ' + CARRY_DAYS +
      ' days it stops being shown: a number pinned to every range put August’s ' +
      'WS on a June week that predated the line.';
  }

  function init() {
    if (!byId('stages')) return;
    if (!RUNS.length) {
      var notice = byId('notice');
      notice.hidden = false;
      notice.textContent = 'No run bundle — run `make build` and publish.';
      return;
    }
    readHash();
    var build = DATA.build || {};
    byId('build').textContent = build.release
      ? build.release + ' · ' + build.commit : '';
    byId('footer-meta').textContent =
      'From the station controllers' +
      (DATA.collectedAt
        ? ', read ' + String(DATA.collectedAt).replace('T', ' ') : '') +
      '. ' + plural(RUNS.length, 'unit run') + ' in the bundle.';
    ['from', 'to'].forEach(function (which) {
      byId(which).addEventListener('change', function (event) {
        if (!event.target.value) return;
        view[which] = event.target.value;
        writeHash();
        render();
      });
    });
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
