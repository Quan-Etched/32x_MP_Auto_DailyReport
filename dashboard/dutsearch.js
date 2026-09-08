/* The other way to ask: by serial rather than by range.
 *
 * WHY A SECOND MODE RATHER THAN ANOTHER FILTER
 * Sections 1 to 3 answer "what happened across these stations over these days".
 * That is the planning question. The other question people arrive with is the
 * opposite shape — "what happened to *this* module" — and it wants no date
 * range at all: you want everything the controllers ever saw for that serial,
 * because the interesting part is usually the run that fell outside whatever
 * window you would have picked.
 *
 * Bolting it on as a fourth filter would have made the range mandatory for a
 * question that has nothing to do with ranges. So it is a mode, switched at the
 * top, the same way flow.html switches between its two drawings. The range view
 * stays the default because it is what the page has always been for.
 *
 * TWO SOURCES, JOINED RATHER THAN MERGED
 * The runs bundle starts at the line's reporting horizon (2026-08-01), so this
 * page used to answer "everything the controllers ever saw" with everything
 * since August — and a board first tested in July arrived looking new. Chris
 * asked for the history to reach the first test on 2026-09-07; 268086800000021
 * had four MLT attempts in July and two runs in the bundle, both dated 09-07.
 *
 * So attempts from before that horizon come from a second, thinner file
 * (data/unit_history.js): day, verdict, suite and the log link, no duration
 * and no per-test detail. The two do not overlap — that file stops the day the
 * runs bundle starts — so there is nothing to dedupe and no tie to break. What
 * the reader is owed is knowing which side of the join a row came from, and
 * the table says so on the row rather than in a legend.
 *
 * MULTIPLE SERIALS
 * One per line. A tray of modules, a rack's four servers, the eight serials
 * somebody pasted out of a spreadsheet — that is the shape the question comes
 * in, and asking for them one at a time would mean eight searches and eight
 * CSVs to reconcile by hand.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RUNS__ || window.__FACTORY_RUNS_PEGA__ || {};
  /* See customize.js: the runs arrive on demand, and this is the other button
     that needs them. Optional, and a passthrough when absent. */
  var BIGDATA = window.FactoryBigData || { ensure: function (fn) { fn(); } };
  var RUNS = DATA.runs || [];
  var LABELS = DATA.stationLabels || {};
  var LINKS = DATA.links || {};
  var ORDER = DATA.stationOrder || [];
  var NAMES = DATA.testNames || [];
  var TSTATUS = DATA.testStatuses || [];

  /* Attempts from before the collected window. Optional throughout: a checkout
     without the file, or a build whose controllers were unreachable, renders
     exactly the page this was before. */
  var EARLIER = window.__FACTORY_UNIT_HISTORY__ || {};
  var EARLIER_UNITS = EARLIER.units || {};
  var JOIN = (EARLIER.window || {}).from || '';
  var REACH = EARLIER.historyFrom || '';

  var GRADED = { pass: true, fail: true, error: true };
  var RUN_PREFIX = /^[0-9a-f]{6,10}_(chip\d+_|sohu_)?/i;

  var view = { serials: [], ran: false };

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
  function byId(id) { return document.getElementById(id); }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  function labelOf(key) { return LABELS[key] || key; }

  function utcDay(run) {
    if (run.t) return new Date(run.t * 1000).toISOString().slice(0, 10);
    return run.day || '';
  }
  function stamp(run) {
    if (run.t) {
      return new Date(run.t * 1000).toISOString()
        .replace('T', ' ').slice(0, 16) + 'Z';
    }
    /* A row with a date and no clock says the date. Rendering midnight would
       be a time nobody recorded. */
    return run.day ? run.day : '';
  }
  function minutes(run) {
    return run.u === undefined || run.u === null ? null
      : Math.round(run.u / 60 * 10) / 10;
  }

  /* Same construction as everywhere else on this site, so a link from here and
     a link from the daily tracker land on the same page. */
  function runUrl(run) {
    var cfg = LINKS.pega;
    if (!cfg || !run.i) return '';
    var host = (cfg.hosts || {})[run.k];
    if (!host) return '';
    var id = String(run.i), slot = null, hash = id.indexOf('#slot');
    if (hash !== -1) { slot = id.slice(hash + 5); id = id.slice(0, hash); }
    var template = slot === null ? cfg.runTemplateNoSlot : cfg.urlTemplate;
    if (!template) return '';
    return template.replace('{host}', host)
      .replace('{run}', encodeURIComponent(id))
      .replace('{slot}', encodeURIComponent(slot || ''));
  }

  function failedCases(run) {
    var out = [];
    (run.T || []).forEach(function (test) {
      var status = TSTATUS[test[1]];
      if (status !== 'fail' && status !== 'error') return;
      var name = String(NAMES[test[0]] || '').replace(RUN_PREFIX, '');
      if (name && out.indexOf(name) === -1) out.push(name);
    });
    return out;
  }

  /* Serials as typed: one per line, and tolerant of what people actually
     paste — commas, tabs, stray whitespace, a header row they forgot to trim.
     Deduplicated, order kept, because the order they pasted is usually the
     order they care about (SS1..SS4, tray position, and so on). */
  function parseSerials(text) {
    var seen = {}, out = [];
    String(text || '').split(/[\s,;]+/).forEach(function (piece) {
      var serial = piece.trim();
      if (!serial || seen[serial]) return;
      seen[serial] = true;
      out.push(serial);
    });
    return out;
  }

  /* One earlier attempt, in the shape the rest of this module already reads.
     The same field names, so nothing downstream has to know where a row came
     from — and nothing invented where the source has nothing: nothing is put
     in `u` (duration) or `T` (test detail), because that file does not carry
     them and a zero there would read as "instant" and "no failures". */
  function earlyRuns(serial) {
    var per = EARLIER_UNITS[serial];
    if (!per) return [];
    var out = [];
    Object.keys(per).forEach(function (station) {
      per[station].forEach(function (row) {
        var runId = row[3], slot = row[4];
        out.push({
          d: serial, k: station, s: row[2], t: row[1], day: row[0],
          /* The runs bundle's own convention for "this run, this slot" — see
             runUrl, which splits on it. Same links from either side. */
          i: (slot === null || slot === undefined)
            ? runId : runId + '#slot' + slot,
          su: row[5],
          early: true
        });
      });
    });
    return out;
  }

  function timeOf(run) {
    if (run.t) return run.t;
    return run.day ? Date.parse(run.day + 'T00:00:00Z') / 1000 : 0;
  }

  /* Every run for a serial, oldest first, across every station and both
     sources. No window: the whole point of searching by serial is that you do
     not know when — which was the one thing this could not deliver while it
     read only the collected window. */
  function historyFor(serial) {
    return RUNS.filter(function (run) { return String(run.d) === serial; })
      .concat(earlyRuns(serial))
      .sort(function (a, b) { return timeOf(a) - timeOf(b); });
  }

  function stationRank(key) {
    var at = ORDER.indexOf(key);
    return at === -1 ? 99 : at;
  }

  /* Per station, the outcome — the same four the result-type page uses, so a
     serial's row here says the same word about it as that page does. */
  function outcomeOf(runs) {
    var graded = runs.filter(function (run) { return GRADED[run.s]; });
    if (!graded.length) return 'no-result';
    if (graded[0].s === 'pass') return 'pass';
    for (var i = 1; i < graded.length; i += 1) {
      if (graded[i].s === 'pass') return 'retest-pass';
    }
    return 'bonepile';
  }
  var OUTCOME_LABEL = {
    'pass': 'Pass', 'retest-pass': 'Retest Pass',
    'bonepile': 'Bonepile', 'no-result': 'No result'
  };

  function summarise(serial) {
    var runs = historyFor(serial);
    var byStation = {};
    runs.forEach(function (run) {
      (byStation[run.k] || (byStation[run.k] = [])).push(run);
    });

    /* Attempt numbers, counted across the whole sequence rather than within
       the collected window.
       `run.a` comes from the build and counts from 2026-08-01, so a bonepile
       board's September run described itself as attempt 1 when it was its
       fifth — the same off-by-a-window the daily tracker's F1 had. Held beside
       the runs rather than written onto them: these objects are the runs
       bundle's own, shared with every other view on this page. */
    var seen = {};
    var attemptNo = runs.map(function (run) {
      if (!GRADED[run.s]) return null;
      seen[run.k] = (seen[run.k] || 0) + 1;
      return seen[run.k];
    });
    var early = runs.filter(function (run) { return run.early; }).length;
    var stations = Object.keys(byStation).sort(function (a, b) {
      return stationRank(a) - stationRank(b);
    }).map(function (key) {
      var at = byStation[key];
      return {
        key: key, label: labelOf(key), runs: at,
        outcome: outcomeOf(at),
        attempts: at.filter(function (run) { return GRADED[run.s]; }).length,
        first: at[0], last: at[at.length - 1]
      };
    });
    return { serial: serial, runs: runs, stations: stations,
             attemptNo: attemptNo, early: early,
             firstSeen: runs.length ? utcDay(runs[0]) : null,
             lastSeen: runs.length ? utcDay(runs[runs.length - 1]) : null };
  }

  /* ------------------------------------------------------------------- csv */

  /* One row per run, with the link. The ask was "DUT_SN and then all the test
     history links", so the serial is the first column and every row carries the
     controller URL for that run — the CSV is the thing people forward, and a
     forwarded row with no link is a claim the recipient cannot check. */
  function csvRows(found) {
    var lines = [['DUT_SN', 'Seq', 'Station', 'Station_Key', 'Result',
                  'Station_Outcome', 'Attempt', 'Started_UTC', 'Day_UTC',
                  'Duration_min', 'Suite', 'Version', 'Failed_Cases',
                  'Run_Link', 'Source']];
    found.forEach(function (unit) {
      var outcomeAt = {};
      unit.stations.forEach(function (station) {
        outcomeAt[station.key] = OUTCOME_LABEL[station.outcome];
      });
      unit.runs.forEach(function (run, index) {
        lines.push([
          unit.serial, index + 1, labelOf(run.k), run.k || '', run.s || '',
          outcomeAt[run.k] || '',
          unit.attemptNo[index] === null ? '' : unit.attemptNo[index],
          stamp(run), utcDay(run),
          minutes(run) === null ? '' : minutes(run),
          run.su || '', run.v || '',
          failedCases(run).join('; '),
          runUrl(run),
          /* A forwarded row has to say what it is. The blank duration and
             blank failure list on an earlier row are the source's, not a
             finding about the run. */
          run.early ? 'run index (before ' + JOIN + ')' : 'runs bundle'
        ]);
      });
    });
    return lines;
  }

  /* ------------------------------------------------------------- rendering */

  function renderInput() {
    var box = byId('dut-input');
    if (!box) return;
    box.value = view.serials.join('\n');
    if (view.ran) box.setAttribute('disabled', 'disabled');
    else box.removeAttribute('disabled');
  }

  function renderRun() {
    var host = byId('dut-run');
    if (!host) return;
    host.innerHTML = '';
    var ready = view.serials.length > 0;

    var button = h('button', {
      type: 'button',
      class: 'view-toggle primary' + (view.ran ? ' done' : ''),
      disabled: (view.ran || !ready) ? 'disabled' : null,
      title: view.ran ? 'already run — press Reset to search again'
             : ready ? 'look up every run for these serials'
             : 'paste at least one serial first'
    }, [h('span', { text: view.ran ? 'Search complete' : 'SEARCH' })]);
    button.addEventListener('click', function () {
      if (view.ran || !ready) return;
      /* The runs arrive on demand now (see the module note in bigdata.js), so
         this is where the 8.6 MB half is fetched — behind the button that needs
         it, not in front of the whole page. */
      BIGDATA.ensure(function () {
        view.ran = true;
        render();
      });
    });
    host.appendChild(button);

    if (view.ran) {
      var reset = h('button', { type: 'button', class: 'view-toggle' },
        [h('span', { text: 'Reset' })]);
      reset.addEventListener('click', function () {
        view.ran = false;
        render();
      });
      host.appendChild(reset);
    } else if (!ready) {
      host.appendChild(h('span', { class: 'run-hint',
        text: 'one serial per line' }));
    }
  }

  function renderResults() {
    var host = byId('dut-results');
    var out = byId('dut-output');
    if (!host || !out) return;
    out.hidden = !view.ran;
    host.innerHTML = '';
    if (!view.ran) return;

    var found = view.serials.map(summarise);
    var known = found.filter(function (unit) { return unit.runs.length; });
    var missing = found.filter(function (unit) { return !unit.runs.length; });

    byId('dut-sub').textContent = known.length
      ? plural(known.length, 'serial') + ' found, '
        + plural(known.reduce(function (n, u) { return n + u.runs.length; }, 0),
                 'run') + ' in total'
        + (missing.length ? ' · ' + missing.length + ' not found' : '')
      : 'None of these serials appears in the collected history.';

    /* Named, not silently dropped. A serial with no runs is the answer to
       "was this ever tested here", and an empty result that looks like a typo
       is worse than one that says which serial it could not find. */
    if (missing.length) {
      host.appendChild(h('p', { class: 'dut-missing', text:
        'No run on any controller for: '
        + missing.map(function (unit) { return unit.serial; }).join(', ')
        + '. Either it has not been tested, or it is tested somewhere that does '
        + 'not report here.' }));
    }

    known.forEach(function (unit) {
      var card = h('div', { class: 'dut-card' });
      card.appendChild(h('div', { class: 'dut-head' }, [
        h('span', { class: 'dut-sn', text: unit.serial }),
        h('span', { class: 'dut-when', text: unit.firstSeen === unit.lastSeen
          ? unit.firstSeen
          : unit.firstSeen + ' → ' + unit.lastSeen }),
        h('span', { class: 'dut-when', text: plural(unit.runs.length, 'run')
          + ' over ' + plural(unit.stations.length, 'station') }),
        /* The headline fact for a bonepile board: its history starts before
           the window this page used to be able to see. */
        unit.early
          ? h('span', { class: 'dut-early-tag',
                        title: 'from the controllers\u2019 run index, which '
                             + 'reaches back to ' + (REACH || 'the first run')
                             + ' — the collected window starts ' + JOIN,
                        text: plural(unit.early, 'attempt') + ' before ' + JOIN })
          : null
      ]));

      /* Per station, the outcome and the attempts behind it — the shape of the
         journey, before the run-by-run detail. */
      var strip = h('div', { class: 'dut-strip' });
      unit.stations.forEach(function (station) {
        strip.appendChild(h('span', {
          class: 'dut-stage o-' + station.outcome,
          title: station.label + ': ' + OUTCOME_LABEL[station.outcome]
                 + ', ' + plural(station.attempts, 'graded attempt')
        }, [
          h('span', { class: 'dut-stage-k', text: station.label }),
          h('span', { class: 'dut-stage-v',
                      text: OUTCOME_LABEL[station.outcome] }),
          h('span', { class: 'dut-stage-n',
                      text: '×' + station.attempts })
        ]));
      });
      card.appendChild(strip);

      var table = h('table', { class: 'cz-table dut-table' });
      var head = h('thead', {}, [h('tr', {}, ['#', 'Station', 'Result',
        'Attempt', 'Started (UTC)', 'Min', 'Suite', 'Failed cases', 'Log']
        .map(function (title) {
          return h('th', { scope: 'col', text: title });
        }))]);
      var body = h('tbody', {});
      unit.runs.forEach(function (run, index) {
        var url = runUrl(run);
        var cases = failedCases(run);
        body.appendChild(h('tr', { class: run.early ? 'dut-early' : null }, [
          h('td', { class: 'num', text: String(index + 1) }),
          h('td', { text: labelOf(run.k) }),
          h('td', {}, [h('span', {
            class: run.s === 'pass' ? 'dut-pass'
                   : run.s === 'fail' ? 'dut-fail' : 'dut-other',
            text: run.s || '—' })]),
          h('td', { class: 'num', text: unit.attemptNo[index] === null
            ? '' : String(unit.attemptNo[index]) }),
          h('td', { class: 'mono', text: stamp(run) }),
          h('td', { class: 'num',
                    text: minutes(run) === null ? '' : String(minutes(run)) }),
          h('td', { class: 'dut-suite', text: run.su || '' }),
          /* An earlier row has no per-test detail to show, and an empty cell
             where the other rows list failures would be read as "it failed
             nothing". Said, once, on the row. */
          run.early
            ? h('td', { class: 'dut-cases dut-nodetail',
                        title: 'the run index carries the verdict and the log '
                             + 'link; per-test detail is not collected before '
                             + JOIN,
                        text: 'not collected' })
            : h('td', { class: 'dut-cases',
                        text: cases.slice(0, 3).join(', ')
                              + (cases.length > 3 ? ', +' + (cases.length - 3) : '') }),
          h('td', {}, [url
            ? h('a', { class: 'dut-link', href: url, target: '_blank',
                       rel: 'noopener noreferrer', title: url, text: 'open' })
            : h('span', { class: 'dut-other', text: '—' })])
        ]));
      });
      table.appendChild(head);
      table.appendChild(body);
      card.appendChild(h('div', { class: 'table-wrap' }, [table]));
      if (unit.early) {
        card.appendChild(h('p', { class: 'dut-note', text:
          'The tinted rows are before ' + JOIN + ', the day the collected '
          + 'window starts. They come from the controllers\u2019 own run index, '
          + 'which reaches ' + (REACH || 'the first run on record') + ': day, '
          + 'verdict, suite and the log link. Duration and failed cases are '
          + 'not collected that far back, and the attempt numbers count from '
          + 'the unit\u2019s first ever run rather than from ' + JOIN + '.' }));
      }
      host.appendChild(card);
    });

    var dl = byId('dut-download');
    dl.innerHTML = '';
    if (known.length && window.FactoryCsv) {
      window.FactoryCsv.attach(dl, {
        label: 'Download CSV',
        title: 'every run for these serials, with the controller link on each',
        name: function () {
          return known.length === 1
            ? 'dut-' + known[0].serial + '-history.csv'
            : 'dut-history-' + known.length + '-serials.csv';
        },
        rows: function () { return csvRows(known); }
      });
    }
  }

  function render() {
    renderInput();
    renderRun();
    renderResults();
  }

  /* The mode switch. Published so the page's own script owns which mode is
     showing — two scripts both hiding and unhiding the same sections would
     race on first load. */
  window.FactoryDutSearch = {
    show: function () { render(); },
    reset: function () { view.ran = false; render(); }
  };

  function init() {
    if (!byId('dut-input')) return;
    var box = byId('dut-input');
    box.addEventListener('input', function () {
      view.serials = parseSerials(box.value);
      renderRun();
    });
    /* A serial in the address, so a link to one unit's history is shareable —
       which is most of why somebody looks a serial up in the first place. */
    var asked = /dut=([0-9A-Za-z,_-]+)/.exec(location.hash || '');
    if (asked) {
      view.serials = parseSerials(asked[1].replace(/,/g, '\n'));
      view.ran = view.serials.length > 0;
    }
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
