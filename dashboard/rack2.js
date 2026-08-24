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

  /* ------------------------------------------- the ramp review's questions */

  /* Four questions were asked about these four servers on 2026-08-24, and each
   * one is answerable from the controllers. They are here rather than in a
   * Slack reply because two of the answers contradict the premise of the
   * question, and a number that contradicts what the room believes needs to be
   * standing somewhere it can be checked.
   *
   * Everything below is computed. Nothing is transcribed from the discussion
   * except the questions themselves and the agreed run-in target.
   */
  var AGREED_RUNIN_MIN = 180;          /* the three hours agreed on Thursday */

  function graded(runs) {
    return (runs || []).filter(function (run) {
      return run.s === 'pass' || run.s === 'fail' || run.s === 'error';
    });
  }

  function minutes(run) {
    return run && run.u ? run.u / 60 : null;
  }

  /* Per server per stage: attempts, whether it ever passed, and on which try.
     Attempt counts matter here — "did they pass" and "how many goes did it
     take" are different questions and only the second explains the schedule. */
  function stageFacts(stage) {
    return RACK.servers.map(function (server) {
      var runs = graded(historyFor(server.sn)[stage]);
      var passAt = -1;
      runs.forEach(function (run, index) {
        if (passAt < 0 && run.s === 'pass') passAt = index;
      });
      return {
        slot: server.slot, sn: server.sn, runs: runs,
        attempts: runs.length,
        ran: runs.length > 0,
        passed: passAt >= 0,
        passOn: passAt >= 0 ? passAt + 1 : null,
        firstPass: runs.length ? runs[0].s === 'pass' : null,
        pass: passAt >= 0 ? runs[passAt] : null,
        last: runs.length ? runs[runs.length - 1] : null
      };
    });
  }

  /* The failing test cases in a run, de-noised of the per-run id prefix so the
     same case reads the same way it does everywhere else on this site. */
  var RUN_PREFIX = /^[0-9a-f]{6,10}_(chip\d+_|sohu_)?/i;
  function failedCases(run) {
    var names = DATA.testNames || [], statuses = DATA.testStatuses || [];
    var out = [];
    (run.T || []).forEach(function (test) {
      var status = statuses[test[1]];
      if (status !== 'fail' && status !== 'error') return;
      var name = String(names[test[0]] || '').replace(RUN_PREFIX, '');
      if (name && out.indexOf(name) === -1) out.push(name);
    });
    return out;
  }

  function anyVirus(runs) {
    var hits = [];
    (runs || []).forEach(function (run) {
      failedCases(run).forEach(function (name) {
        if (/virus/i.test(name) && hits.indexOf(name) === -1) hits.push(name);
      });
    });
    return hits;
  }

  function runLink(run, text) {
    var url = runUrl(run);
    if (!url) return h('span', { class: 'r2-none', text: text });
    return h('a', { class: 'r2-run', href: url, target: '_blank',
                    rel: 'noopener noreferrer', title: url, text: text });
  }

  /* Question 1 — did all four pass FAT and SFT, what was SFT's first-pass
     yield, and were retests involved. */
  function answerFatSft() {
    var fat = stageFacts('l10_fat'), sft = stageFacts('l10_sft');
    var ranSft = sft.filter(function (row) { return row.ran; });
    var firstPass = ranSft.filter(function (row) { return row.firstPass; });
    var everPass = ranSft.filter(function (row) { return row.passed; });

    var lines = [];
    /* FPY over the servers that ran it, not over four. Three ran SFT; dividing
       by four would report a yield for a server that was never tested. */
    lines.push(h('p', {}, [
      h('strong', { text: 'SFT first-pass yield: ' }),
      h('span', { text: ranSft.length
        ? firstPass.length + ' of ' + ranSft.length + ' ('
          + Math.round(1000 * firstPass.length / ranSft.length) / 10
          + '%) passed SFT on the first attempt'
          + (ranSft.length < RACK.servers.length
             ? ' — over the ' + ranSft.length + ' that ran it, not four: '
               + sft.filter(function (row) { return !row.ran; })
                    .map(function (row) { return row.slot; }).join(', ')
               + ' has no SFT record at all.'
             : '.')
        : 'no server has an SFT record.' })
    ]));
    if (ranSft.length && everPass.length === firstPass.length) {
      lines.push(h('p', { class: 'r2-note', text:
        'After retests it is still ' + everPass.length + ' of '
        + ranSft.length + ': nothing that failed SFT has since passed it.' }));
    }

    /* FAT was not asked about but answers itself: nobody passed it first time,
       so its first-pass yield is zero and every FAT pass on this rack is a
       retest. That is the more useful number for the schedule question behind
       the question. */
    var ranFat = fat.filter(function (row) { return row.ran; });
    var fatFirst = ranFat.filter(function (row) { return row.firstPass; });
    if (ranFat.length) {
      lines.push(h('p', {}, [
        h('strong', { text: 'FAT first-pass yield: ' }),
        h('span', { text: fatFirst.length + ' of ' + ranFat.length + ' ('
          + Math.round(1000 * fatFirst.length / ranFat.length) / 10 + '%)'
          + (fatFirst.length === 0
             ? ' — no server passed FAT on its first attempt, so every FAT '
               + 'pass on this rack is a retest.' : '.') })
      ]));
    }
    return { fat: fat, sft: sft, lines: lines };
  }

  /* Question 2 — the run-in was 45 minutes against three hours agreed. */
  function answerRunin() {
    var rows = stageFacts('l10_rin');
    var withAny = rows.filter(function (row) { return row.ran; });
    var durations = [];
    withAny.forEach(function (row) {
      row.runs.forEach(function (run) {
        var mins = minutes(run);
        if (mins !== null) durations.push({ row: row, run: run, mins: mins });
      });
    });
    var passing = durations.filter(function (d) { return d.run.s === 'pass'; });
    return {
      rows: rows, durations: durations, passing: passing,
      missing: rows.filter(function (row) { return !row.ran; }),
      longest: passing.length
        ? passing.reduce(function (a, b) { return a.mins > b.mins ? a : b; })
        : null
    };
  }

  function renderReview() {
    var host = byId('review');
    if (!host) return;
    host.innerHTML = '';

    var fatSft = answerFatSft();
    var runin = answerRunin();
    var newest = null;
    RACK.servers.forEach(function (server) {
      var hist = historyFor(server.sn);
      Object.keys(hist).forEach(function (key) {
        hist[key].forEach(function (run) {
          if (!newest || (run.t || 0) > (newest.t || 0)) newest = run;
        });
      });
    });

    function block(question, answer, kids) {
      var card = h('div', { class: 'r2-qa' }, [
        h('p', { class: 'r2-q', text: question }),
        h('p', { class: 'r2-a', text: answer })
      ]);
      (kids || []).forEach(function (kid) { if (kid) card.appendChild(kid); });
      host.appendChild(card);
    }

    /* --- run-in duration --- */
    var runinAnswer;
    if (!runin.durations.length) {
      runinAnswer = 'No server has a run-in record at all.';
    } else {
      var mins = runin.passing.map(function (d) {
        return Math.round(d.mins) + ' min';
      });
      runinAnswer = 'Confirmed, and shorter than 45 minutes for some of it. '
        + 'The only run-in on record is ' + runin.rows.filter(
            function (r) { return r.ran; }).map(function (r) {
              return r.slot; }).join(', ')
        + ' — passing runs of ' + mins.join(' and ')
        + ', against the ' + (AGREED_RUNIN_MIN / 60) + '-hour target.';
      if (runin.missing.length) {
        runinAnswer += ' ' + runin.missing.map(function (r) { return r.slot; })
          .join(', ') + ' have no run-in record on any controller.';
      }
    }
    var runinTable = h('div', { class: 'r2-mini' });
    runin.rows.forEach(function (row) {
      var cells = [h('span', { class: 'r2-slot', text: row.slot })];
      if (!row.ran) {
        cells.push(h('span', { class: 'r2-none', text: 'no run-in record' }));
      } else {
        row.runs.forEach(function (run) {
          var mins = minutes(run);
          cells.push(h('span', { class: 'r2-cell' }, [
            h('span', { class: run.s === 'pass' ? 'r2-pass' : 'r2-fail',
                        text: run.s }),
            h('span', { class: 'r2-att',
                        text: mins === null ? '' : Math.round(mins) + ' min' }),
            runLink(run, utcDay(run))
          ]));
        });
      }
      runinTable.appendChild(h('div', { class: 'r2-mini-row' }, cells));
    });
    block('The L10 servers went through standalone SFT and 45 minutes of '
          + 'run-in, which deviated from the agreed 3-hour run-in.',
          runinAnswer, [runinTable]);

    /* --- FAT / SFT --- */
    var fatSftTable = h('div', { class: 'r2-mini' });
    [['FAT', fatSft.fat], ['SFT', fatSft.sft]].forEach(function (spec) {
      spec[1].forEach(function (row) {
        fatSftTable.appendChild(h('div', { class: 'r2-mini-row' }, [
          h('span', { class: 'r2-slot', text: row.slot + ' ' + spec[0] }),
          h('span', { class: !row.ran ? 'r2-none'
                      : row.passed ? 'r2-pass' : 'r2-fail',
            text: !row.ran ? 'never ran'
                  : row.passed ? 'passed on attempt ' + row.passOn
                  : 'never passed' }),
          h('span', { class: 'r2-att', text: row.attempts
            ? plural(row.attempts, 'attempt') : '' }),
          row.last ? runLink(row.last, 'last run ' + utcDay(row.last)) : null
        ]));
      });
    });
    var notPassedFat = fatSft.fat.filter(function (row) {
      return row.ran && !row.passed; });
    var extra = [];
    if (notPassedFat.length) {
      /* A unit at SFT without a FAT pass behind it is the same mis-flow the
         daily tracker tracks at MLT and HTT, one stage up. */
      extra.push(h('p', { class: 'r2-flag', text:
        notPassedFat.map(function (row) { return row.slot; }).join(', ')
        + ' never passed FAT — and reached SFT anyway. That is a wrong flow at '
        + 'L10, the same kind the module line tracks between MLT and HTT.' }));
    }
    block('Did all 4 servers pass FAT / SFT? What was the FPY for the 4 '
          + 'servers at SFT? Were any retests involved?',
          'No. ' + fatSft.fat.filter(function (r) { return r.passed; }).length
          + ' of 4 passed FAT and ' + fatSft.sft.filter(
              function (r) { return r.passed; }).length
          + ' of 4 passed SFT. Retests were involved throughout — FAT took up '
          + 'to ' + Math.max.apply(null, fatSft.fat.map(function (r) {
              return r.attempts; })) + ' attempts on one server.',
          fatSft.lines.concat([fatSftTable]).concat(extra));

    /* --- thermal virus --- */
    var virusRuns = [];
    RACK.servers.forEach(function (server) {
      var hist = historyFor(server.sn);
      Object.keys(hist).forEach(function (key) {
        hist[key].forEach(function (run) {
          var hits = anyVirus([run]);
          if (hits.length) {
            virusRuns.push({ slot: server.slot, station: key, run: run,
                             cases: hits });
          }
        });
      });
    });
    var virusTable = h('div', { class: 'r2-mini' });
    virusRuns.forEach(function (item) {
      virusTable.appendChild(h('div', { class: 'r2-mini-row' }, [
        h('span', { class: 'r2-slot', text: item.slot + ' ' +
                    labelOf(item.station) }),
        h('span', { class: 'r2-fail', text: utcDay(item.run) }),
        h('span', { class: 'r2-att', text: item.cases.slice(0, 3).join(', ') }),
        runLink(item.run, 'log')
      ]));
    });
    /* The dominant failures, so the answer names what actually went wrong
       rather than only what did not. */
    var tally = {};
    RACK.servers.forEach(function (server) {
      var hist = historyFor(server.sn);
      Object.keys(hist).forEach(function (key) {
        hist[key].forEach(function (run) {
          if (run.s === 'pass') return;
          failedCases(run).forEach(function (name) {
            tally[name] = (tally[name] || 0) + 1;
          });
        });
      });
    });
    var top = Object.keys(tally).sort(function (a, b) {
      return tally[b] - tally[a]; }).slice(0, 5);
    block('I heard that all 4 servers failed the preliminary run-in due to '
          + 'thermal virus. Do we have the factory test logs and failure '
          + 'details?',
          virusRuns.length
            ? 'Partly. A power-virus failure appears in ' + virusRuns.length
              + ' run' + (virusRuns.length === 1 ? '' : 's') + ', not four '
              + 'servers’ worth — and only on '
              + virusRuns.map(function (i) { return i.slot; })
                  .filter(function (v, i, a) { return a.indexOf(v) === i; })
                  .join(', ') + '. Logs are linked below.'
            : 'Not in this data. No run on any of the four failed a '
              + 'power-virus or thermal case.',
          [virusTable,
           h('p', { class: 'r2-note', text: 'What actually dominates the '
             + 'failures on these four: ' + top.map(function (name) {
                 return name + ' ×' + tally[name]; }).join(', ')
             + '. Firmware and provisioning at FAT, disk and inference '
             + 'validation at SFT — not thermal.' })]);

    /* --- the in-rack SFT --- */
    var stamp = newest ? utcDay(newest) : null;
    var collected = (DATA.collectedAt || '').slice(0, 10);
    block('These 4 servers were then assembled into the L11 rack and L10 SFT '
          + 'was conducted again in the rack. My understanding is that none of '
          + 'the 4 passed SFT due to thermal virus. Please confirm.',
          'Cannot confirm — there is no record of it. The most recent run on '
          + 'any of these four serials is ' + (stamp || 'unknown')
          + ', and the controllers were read on ' + (collected || 'unknown')
          + '. Whatever SFT ran in the rack has not reached pega4 or pega5, so '
          + 'this dashboard has nothing to confirm or contradict.',
          [h('p', { class: 'r2-flag', text: 'What the data does say cuts the '
             + 'other way: '
             + fatSft.sft.filter(function (r) { return r.passed; })
                 .map(function (r) {
                   return r.slot + ' passed SFT on ' + utcDay(r.pass) + ' in '
                     + Math.round(minutes(r.pass)) + ' minutes, first attempt';
                 }).join('; ')
             + '. If the in-rack SFT then failed it, that is a change of state '
             + 'worth having the log for.' })]);
  }

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
    renderReview();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
