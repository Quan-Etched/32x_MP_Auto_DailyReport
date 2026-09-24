/* L10 SFT report for the selected day on Daily FA.

   Counts are one chassis, not one attempt. A later pass replaces an
   earlier fail. A later fail does not add a second failed chassis.

   The CSV is one row per suite run — pass or fail. The same ESVM URL is
   written once. Failures are filed as one Jira per coverage-sheet stage
   (column C) from any selected day.
*/
(function () {
  'use strict';

  function byId(id) { return document.getElementById(id); }

  function cell(row, at) {
    if (at < 0 || !row || at >= row.length) return {};
    return row[at] || {};
  }

  function isC2c(name) {
    return /c2c/i.test(name || '');
  }

  function fromTable(l10) {
    var columns = (l10 && l10.columns) || [];
    var resultAt = -1;
    var snAt = -1;
    columns.forEach(function (column, index) {
      if (column.key === 'B') snAt = index;
      var title = column.title || '';
      if (column.station === 'l10_sft' && column.kind !== 'version' &&
          /Results/.test(title)) {
        resultAt = index;
      }
    });
    var failAt = -1;
    var linkAt = -1;
    if (resultAt >= 0) {
      for (var i = resultAt + 1; i < columns.length; i++) {
        var title = columns[i].title || '';
        if (failAt < 0 && /Failure Test Case/.test(title)) failAt = i;
        if (/^FI Test Link/.test(title)) { linkAt = i; break; }
      }
    }
    var day = (l10 && l10.day) || '';
    var tested = 0, passed = 0, failed = 0, sns = [], rows = [];
    ((l10 && l10.rows) || []).forEach(function (row) {
      var tone = cell(row, resultAt).t;
      var sn = (cell(row, snAt).v || '').trim();
      var failNames = String(cell(row, failAt).v || '').split(/\n+/)
        .map(function (name) { return name.trim(); })
        .filter(Boolean);
      var link = cell(row, linkAt).h || '';
      var hist = ((cell(row, snAt).history || {}).l10_sft) || [];
      var attempts = hist.filter(function (item) { return item.day === day; });
      if (!attempts.length && (tone === 'pass' || tone === 'fail')) {
        attempts = [{
          n: 1,
          status: tone,
          url: link,
          failures: tone === 'fail' ? failNames.map(function (name) {
            return {test: name, caseId: name, code: 'NA', at: ''};
          }) : []
        }];
      }
      if (!attempts.length) return;
      tested += 1;
      if (tone === 'pass') passed += 1;
      else if (tone === 'fail') {
        failed += 1;
        if (sn) sns.push(sn);
      }
      var seen = {};
      attempts.sort(function (a, b) {
        return (a.n || 0) - (b.n || 0);
      });
      attempts.forEach(function (attempt, index) {
        var url = attempt.url || '';
        var run = url || attempt.started || ('#' + index);
        if (seen[run]) return;
        seen[run] = true;
        var failures = attempt.failures || [];
        var tests = failures.map(function (item) {
          return item.test || '';
        }).filter(Boolean);
        if (!tests.length && attempt.status === 'fail' &&
            (attempt === attempts[attempts.length - 1] || !url || url === link)) {
          tests = failNames.slice();
          failures = tests.map(function (name) {
            return {test: name, caseId: name, code: 'NA', at: ''};
          });
        }
        var codes = failures.map(function (item) { return item.code || 'NA'; });
        var caseIds = failures.map(function (item) {
          return item.caseId || item.test || '';
        }).filter(Boolean);
        rows.push({
          sn: sn,
          attempt: attempt.n || (index + 1),
          final: tone,
          status: attempt.status || tone,
          test: tests.join('; '),
          tests: tests,
          code: tests.length ? codes.join('; ') : '',
          caseIds: caseIds,
          at: attempt.started || (failures[0] && failures[0].at) || '',
          url: url,
          c2c: tests.some(isC2c),
          jira: attempt.jira || ''
        });
      });
    });
    var kinds = {};
    rows.forEach(function (row) {
      (row.tests || []).forEach(function (test, index) {
        if (!test) return;
        var bucket = kinds[test] || (kinds[test] = {
          test: test, caseIds: [], sns: []
        });
        var caseId = (row.caseIds || [])[index] || test;
        if (bucket.caseIds.indexOf(caseId) < 0) bucket.caseIds.push(caseId);
        if (row.final === 'fail' && row.sn && bucket.sns.indexOf(row.sn) < 0) {
          bucket.sns.push(row.sn);
        }
      });
    });
    return {
      day: day,
      tested: tested, passed: passed, failed: failed,
      yield: tested ? passed / tested : null,
      failedSns: sns, rows: rows,
      kinds: Object.keys(kinds).sort().map(function (name) { return kinds[name]; }),
      coarse: true
    };
  }

  function reportFor(tab) {
    var l10 = tab && tab.l10;
    if (l10 && l10.sftReport) return l10.sftReport;
    if (l10) return fromTable(l10);
    return null;
  }

  function pct(report) {
    if (report.yield == null || !report.tested) return 'n/a';
    return (report.yield * 100).toFixed(1) + '%';
  }

  function csvText(report) {
    var lines = ['sn,attempt,final,test,errorCode,testedAt,esvmUrl,jira'];
    (report.rows || []).forEach(function (row) {
      lines.push([row.sn, row.attempt, row.final, row.test,
                  row.code || '', row.at, row.url, row.jira || '']
        .map(function (value) {
          var text = value == null ? '' : String(value);
          return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
        }).join(','));
    });
    return lines.join('\n') + '\n';
  }

  function bindCsv(report) {
    var link = byId('sft-report-csv');
    if (!link) return;
    var blob = new Blob([csvText(report)], {type: 'text/csv'});
    if (link._url) URL.revokeObjectURL(link._url);
    link._url = URL.createObjectURL(blob);
    link.href = link._url;
    link.download = 'L10-SFT-' + (report.day || 'day') + '.csv';
  }

  function flowMap() {
    return (window.__FACTORY_DAILY_EXCEL__ || {}).flowStages || {};
  }

  function normTest(name) {
    var text = String(name || '').trim();
    if (/TestCase$/i.test(text)) text = text.replace(/TestCase$/i, '');
    return text.replace(/MultiChip/ig, '').toLowerCase();
  }

  function stageOfTest(name) {
    var raw = String(name || '').trim();
    if (!raw) return '';
    var map = flowMap();
    if (map[raw]) return map[raw];
    var folded = normTest(raw);
    var best = '';
    var stage = '';
    Object.keys(map).forEach(function (key) {
      var known = normTest(key);
      if (known === folded) {
        stage = map[key];
        best = known;
        return;
      }
      if (folded.length < 8 || known.length < 8) return;
      if ((folded.indexOf(known) === 0 || known.indexOf(folded) === 0) &&
          known.length > best.length) {
        best = known;
        stage = map[key];
      }
    });
    if (stage) return stage;
    var lower = raw.toLowerCase();
    if (/c2c|sohuping|hostreboot/.test(lower) ||
        (lower.indexOf('vfio') >= 0 && lower.indexOf('ping') >= 0)) {
      return 'Sohu C2C';
    }
    if (lower.indexOf('inferencemax') >= 0) return 'InferenceMAX Run-in';
    if (lower.indexOf('llama') >= 0 || lower.indexOf('huggingface') >= 0) {
      return 'Model Registry & Inference';
    }
    return raw;
  }

  function stageKinds(report) {
    if (report && report.stageKinds && report.stageKinds.length) {
      return report.stageKinds;
    }
    var buckets = {};
    function add(stage, test, serial) {
      if (!stage) return;
      var bucket = buckets[stage] || (buckets[stage] = {
        test: stage, tests: [], sns: []
      });
      if (test && bucket.tests.indexOf(test) < 0) bucket.tests.push(test);
      if (serial && bucket.sns.indexOf(serial) < 0) bucket.sns.push(serial);
    }
    (report.kinds || []).forEach(function (kind) {
      var test = kind.test || '';
      var stage = kind.stage || stageOfTest(test);
      add(stage, test);
      (kind.sns || []).forEach(function (serial) { add(stage, test, serial); });
    });
    (report.rows || []).forEach(function (row) {
      var serial = row.final === 'fail' ? (row.sn || '') : '';
      (row.tests || []).forEach(function (test) {
        add(stageOfTest(test), test, serial);
      });
    });
    return Object.keys(buckets).map(function (name) { return buckets[name]; });
  }

  function failingStages(report) {
    return stageKinds(report).filter(function (kind) {
      return (kind.sns || []).length > 0;
    });
  }

  function hasFailures(report) {
    return failingStages(report).length > 0;
  }

  function renderStages(report, filed) {
    var host = byId('sft-report-stages');
    var label = byId('sft-report-stage-label');
    if (!host) return;
    host.innerHTML = '';
    var groups = failingStages(report);
    if (label) label.hidden = !groups.length;
    var byStage = {};
    (filed || []).forEach(function (item) {
      if (item && item.test && item.url) byStage[item.test] = item.url;
    });
    (report.rows || []).forEach(function (row) {
      (row.tests || []).forEach(function (test) {
        var stage = stageOfTest(test);
        if (!byStage[stage] && row.jira) {
          byStage[stage] = String(row.jira).split(';')[0].trim();
        }
      });
    });
    groups.forEach(function (kind) {
      var item = document.createElement('li');
      var tests = (kind.tests || []).join(', ');
      var sns = (kind.sns || []).join(', ');
      item.appendChild(document.createTextNode(
        kind.test + (tests ? ' — ' + tests : '') + (sns ? ' · ' + sns : '')
      ));
      var url = byStage[kind.test];
      if (url) {
        item.appendChild(document.createTextNode(' · '));
        var link = document.createElement('a');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = url.replace(/.*\//, '');
        item.appendChild(link);
      }
      host.appendChild(item);
    });
  }

  function note(text) {
    var node = byId('sft-report-note');
    if (node) node.textContent = text || '';
  }

  function render(tab) {
    var panel = byId('sft-report');
    if (!panel) return;
    panel.hidden = false;
    byId('sft-report-day').textContent = (tab && tab.day) || '';
    var report = reportFor(tab);
    if (!report) {
      byId('sft-report-counts').textContent = 'No L10 data for this day.';
      byId('sft-report-sns').textContent = '';
      byId('sft-report-csv').hidden = true;
      byId('sft-report-jira').hidden = true;
      renderStages({kinds: [], rows: []});
      note('');
      return;
    }
    byId('sft-report-csv').hidden = false;
    byId('sft-report-jira').hidden = false;
    byId('sft-report-counts').textContent =
      report.tested + ' DUT tested, ' + report.failed + ' failed, ' +
      report.passed + ' passed. Yield ' + pct(report) +
      '. A retest that passes counts as a pass. A chassis that fails again ' +
      'counts once. CSV is one row per SFT run.' +
      (report.coarse ? ' This build has only the latest attempt, so the CSV ' +
        'error code is NA until the tracker is rebuilt.' : '');
    var sns = report.failedSns || [];
    byId('sft-report-sns').textContent = sns.length
      ? 'Failed SN: ' + sns.join(', ')
      : 'Failed SN: none';
    bindCsv(report);
    renderStages(report);
    byId('sft-report-note').textContent = hasFailures(report)
      ? ''
      : 'No failing tests on this day.';
    var button = byId('sft-report-jira');
    button.onclick = function () { fileJiras(report); };
  }

  function applyFiled(report, filed) {
    var byTest = {};
    (filed || []).forEach(function (item) {
      if (!item || !item.url) return;
      (item.tests || []).forEach(function (test) {
        byTest[test] = item.url;
      });
      if (item.test) byTest[item.test] = item.url;
    });
    (report.rows || []).forEach(function (row) {
      var urls = [];
      (row.tests || []).forEach(function (test) {
        var url = byTest[test];
        if (url && urls.indexOf(url) < 0) urls.push(url);
      });
      if (urls.length) row.jira = urls.join('; ');
    });
    bindCsv(report);
    renderStages(report, filed);
  }

  function fileJiras(report) {
    var note = byId('sft-report-note');
    if (!hasFailures(report)) {
      note.textContent = 'No failing tests to file.';
      return;
    }
    note.textContent = 'Filing…';
    fetch('/api/sft-jiras', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Factory-Update': '1'
      },
      body: JSON.stringify({day: report.day})
    }).then(function (response) {
      return response.json().then(function (body) {
        return {ok: response.ok, body: body};
      });
    }).then(function (result) {
      if (!result.ok) {
        note.textContent = result.body.error || 'Jira was not filed.';
        return;
      }
      var filed = result.body.filed || [];
      if (!filed.length) {
        note.textContent = 'No tickets filed.';
        return;
      }
      applyFiled(report, filed);
      note.textContent = filed.map(function (item) {
        return item.key;
      }).join(', ');
    }).catch(function () {
      note.textContent = 'This page is not being served by the factory app, so Jira cannot be filed from here.';
    });
  }

  window.SftReport = {render: render, reportFor: reportFor, csvText: csvText,
                      fromTable: fromTable, note: note};
})();
