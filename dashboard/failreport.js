/* L10 FAT / SFT / RIN reports for the selected day on Daily FA.

   Counts are one chassis, not one attempt. A later pass replaces an
   earlier fail. A later fail does not add a second failed chassis.

   The table is one row per SN + run + error type. Test cases of that
   type stack in the cell. SN is written once per run. DRI is MTE.
   Jira files that row only; after a row is filed the button stays off.
*/
(function () {
  'use strict';

  var PANELS = [
    {stage: 'fat', label: 'L10 FAT', key: 'fatReport',
     panel: 'fat-report', day: 'fat-report-day',
     counts: 'fat-report-counts', sns: 'fat-report-sns',
     table: 'fat-report-table', csv: 'fat-report-csv',
     note: 'fat-report-note'},
    {stage: 'sft', label: 'L10 SFT', key: 'sftReport',
     panel: 'sft-report', day: 'sft-report-day',
     counts: 'sft-report-counts', sns: 'sft-report-sns',
     table: 'sft-report-table', csv: 'sft-report-csv',
     note: 'sft-report-note'},
    {stage: 'rin', label: 'L10 RIN', key: 'rinReport',
     panel: 'rin-report', day: 'rin-report-day',
     counts: 'rin-report-counts', sns: 'rin-report-sns',
     table: 'rin-report-table', csv: 'rin-report-csv',
     note: 'rin-report-note'}
  ];

  var STATION_OF = {fat: 'l10_fat', sft: 'l10_sft', rin: 'l10_rin'};

  function byId(id) { return document.getElementById(id); }

  function cell(row, at) {
    if (at < 0 || !row || at >= row.length) return {};
    return row[at] || {};
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

  var DEFAULT_DRI = 'MTE';

  function rowId(sn, test, url, at) {
    return [sn || '', test || '', url || '', at || ''].join('|');
  }

  function groupId(sn, errorType, url) {
    return [sn || '', errorType || '', url || ''].join('|');
  }

  function groupFailRows(leaves) {
    var order = [];
    var buckets = {};
    leaves.forEach(function (leaf) {
      var key = groupId(leaf.sn, leaf.errorType, leaf.url);
      var bucket = buckets[key];
      if (!bucket) {
        bucket = {
          id: key,
          sn: leaf.sn || '',
          errorType: leaf.errorType || '',
          tests: [],
          codes: [],
          times: [],
          at: leaf.at || '',
          passAt: leaf.passAt || '',
          url: leaf.url || '',
          jira: leaf.jira || '',
          dri: leaf.errorType === 'Passed' ? '' : (leaf.dri || DEFAULT_DRI),
          attempt: leaf.attempt,
          final: leaf.final,
          status: leaf.status
        };
        buckets[key] = bucket;
        order.push(key);
      }
      if (leaf.test && bucket.tests.indexOf(leaf.test) < 0) {
        bucket.tests.push(leaf.test);
      }
      String(leaf.code || '').split(/\n+/).forEach(function (code) {
        code = code.trim();
        if (code && bucket.codes.indexOf(code) < 0) bucket.codes.push(code);
      });
      if (leaf.jira) bucket.jira = leaf.jira;
      if (leaf.passAt) bucket.passAt = leaf.passAt;
      if (leaf.at && bucket.times.indexOf(leaf.at) < 0) bucket.times.push(leaf.at);
      if (leaf.at && (!bucket.at || leaf.at < bucket.at)) bucket.at = leaf.at;
    });
    return order.map(function (key) {
      var bucket = buckets[key];
      bucket.test = bucket.tests.join(', ');
      var real = bucket.codes.filter(function (code) { return code !== 'NA'; });
      bucket.codes = real.length ? real : (bucket.codes.length ? ['NA'] : []);
      bucket.code = bucket.codes.join('\n') || 'NA';
      return bucket;
    });
  }

  function expandFailRows(report) {
    var found = [];
    (report.rows || []).forEach(function (row) {
      if (row.status === 'pass' || row.errorType === 'Passed') {
        row.errorType = 'Passed';
        row.dri = '';
        row.jira = row.jira || '';
        row.id = row.id || groupId(row.sn, 'Passed', row.url);
        found.push(row);
        return;
      }
      if (row.errorType || (row.test && !row.tests)) {
        if (!row.test) return;
        if (!row.id) {
          row.id = rowId(row.sn, row.test, row.url, row.at);
        }
        if (!row.errorType) row.errorType = stageOfTest(row.test);
        if (!row.dri) row.dri = DEFAULT_DRI;
        found.push(row);
        return;
      }
      var tests = row.tests || String(row.test || '').split(';')
        .map(function (name) { return name.trim(); })
        .filter(Boolean);
      var codes = String(row.code || '').split(';')
        .map(function (code) { return code.trim(); });
      var caseIds = row.caseIds || [];
      tests.forEach(function (test, index) {
        found.push({
          id: rowId(row.sn, test, row.url, row.at),
          sn: row.sn || '',
          errorType: stageOfTest(test),
          test: test,
          caseId: caseIds[index] || test,
          at: row.at || '',
          code: codes[index] || row.code || 'NA',
          url: row.url || '',
          jira: row.jira || '',
          dri: row.dri || DEFAULT_DRI,
          attempt: row.attempt || '',
          final: row.final || '',
          status: row.status || ''
        });
      });
    });
    report.rows = found;
    return found;
  }

  function fromTable(l10, stage) {
    var station = STATION_OF[stage];
    var columns = (l10 && l10.columns) || [];
    var resultAt = -1;
    var snAt = -1;
    columns.forEach(function (column, index) {
      if (column.key === 'B') snAt = index;
      var title = column.title || '';
      if (column.station === station && column.kind !== 'version' &&
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
    if (resultAt < 0) return null;
    var day = (l10 && l10.day) || '';
    var tested = 0, passed = 0, failed = 0, sns = [], rows = [];
    ((l10 && l10.rows) || []).forEach(function (row) {
      var tone = cell(row, resultAt).t;
      var sn = (cell(row, snAt).v || '').trim();
      var failNames = String(cell(row, failAt).v || '').split(/\n+/)
        .map(function (name) { return name.trim(); })
        .filter(Boolean);
      var link = cell(row, linkAt).h || '';
      var hist = ((cell(row, snAt).history || {})[station]) || [];
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
      if (tone !== 'pass' && tone !== 'fail') {
        var last = attempts.length ? attempts[attempts.length - 1].status : '';
        if (last === 'pass' || last === 'fail') tone = last;
        else return;
      }
      if (!attempts.length) return;
      tested += 1;
      if (tone === 'pass') passed += 1;
      else if (tone === 'fail') {
        failed += 1;
        if (sn) sns.push(sn);
      }
      var seen = {};
      var unique = [];
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
        unique.push({
          url: url,
          started: attempt.started || '',
          status: attempt.status || tone,
          failures: failures,
          n: attempt.n || (index + 1),
          jira: attempt.jira || ''
        });
      });
      if (!unique.length) return;
      var last = unique[unique.length - 1];
      var passAt = '';
      unique.forEach(function (attempt) {
        if (attempt.status === 'pass' && attempt.started) passAt = attempt.started;
      });
      if (last.status === 'pass') {
        rows.push({
          id: groupId(sn, 'Passed', last.url),
          sn: sn,
          errorType: 'Passed',
          test: '',
          caseId: '',
          at: last.started || '',
          passAt: last.started || passAt,
          code: '',
          url: last.url,
          jira: '',
          dri: '',
          attempt: last.n,
          final: 'pass',
          status: 'pass'
        });
        return;
      }
      last.failures.forEach(function (item) {
        var test = item.test || '';
        if (!test) return;
        var at = item.at || last.started || '';
        rows.push({
          id: rowId(sn, test, last.url, at),
          sn: sn,
          errorType: stageOfTest(test),
          test: test,
          caseId: item.caseId || test,
          at: at,
          passAt: passAt,
          code: item.code || 'NA',
          url: last.url,
          jira: item.jira || last.jira || '',
          dri: DEFAULT_DRI,
          attempt: last.n,
          final: 'fail',
          status: 'fail'
        });
      });
    });
    return {
      day: day,
      stage: stage,
      station: station,
      tested: tested, passed: passed, failed: failed,
      yield: tested ? passed / tested : null,
      failedSns: sns, rows: rows,
      coarse: true
    };
  }

  function reportFor(tab, panel) {
    var l10 = tab && tab.l10;
    var stored = l10 && l10[panel.key];
    if (stored) {
      stored.stage = stored.stage || panel.stage;
      expandFailRows(stored);
      return stored;
    }
    if (l10 && l10.columns) return fromTable(l10, panel.stage);
    return null;
  }

  function pct(report) {
    if (report.yield == null || !report.tested) return 'n/a';
    return (report.yield * 100).toFixed(1) + '%';
  }

  function csvText(report) {
    var lines = ['sn,errorType,test,testedAt,errorCode,pegaUrl,dri,jira'];
    groupFailRows(expandFailRows(report)).forEach(function (row) {
      lines.push([row.sn, row.errorType, row.test, row.at,
                  row.code || '', row.url,
                  row.errorType === 'Passed' ? '' : (row.dri || DEFAULT_DRI),
                  row.jira || '']
        .map(function (value) {
          var text = value == null ? '' : String(value);
          return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
        }).join(','));
    });
    return lines.join('\n') + '\n';
  }

  function bindCsv(panel, report) {
    var link = byId(panel.csv);
    if (!link) return;
    var blob = new Blob([csvText(report)], {type: 'text/csv'});
    if (link._url) URL.revokeObjectURL(link._url);
    link._url = URL.createObjectURL(blob);
    link.href = link._url;
    link.download = panel.label.replace(/ /g, '-') + '-' +
      (report.day || 'day') + '.csv';
  }

  function fmtTime(value) {
    var text = String(value || '').trim();
    if (!text) return '';
    var match = text.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    if (match) return match[2] + '-' + match[3] + ' ' + match[4] + ':' + match[5];
    return text.replace('T', ' ').replace(/\.\d+/, '').replace(/Z$/, '');
  }

  function jiraKey(url) {
    return String(url || '').replace(/\/+$/, '').replace(/.*\//, '');
  }

  function renderJiraCell(td, panel, report, row) {
    td.innerHTML = '';
    if (row.jira) {
      var done = document.createElement('a');
      done.href = row.jira;
      done.target = '_blank';
      done.rel = 'noopener';
      done.className = 'fa-jira-link';
      done.textContent = jiraKey(row.jira);
      td.appendChild(done);
      return;
    }
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'fa-jira-btn';
    button.textContent = 'File Jira';
    button.addEventListener('click', function () {
      fileRow(panel, report, row, button, td);
    });
    td.appendChild(button);
  }

  function renderTable(panel, report) {
    var host = byId(panel.table);
    if (!host) return;
    host.innerHTML = '';
    var rows = groupFailRows(expandFailRows(report));
    if (!rows.length) {
      host.appendChild(document.createTextNode('No DUT tested on this day.'));
      return;
    }
    var table = document.createElement('table');
    table.className = 'fa-table';
    var head = document.createElement('thead');
    var hr = document.createElement('tr');
    var titles = [
      ['DUT SN', 'col-sn'],
      ['Error type', 'col-type'],
      ['Test case', 'col-test'],
      ['Test time', 'col-time'],
      ['Error code', 'col-code'],
      ['ESVM', 'col-url'],
      ['DRI', 'col-dri'],
      ['Jira', 'col-jira']
    ];
    titles.forEach(function (item) {
      var th = document.createElement('th');
      th.className = item[1];
      th.textContent = item[0];
      hr.appendChild(th);
    });
    head.appendChild(hr);
    table.appendChild(head);
    var body = document.createElement('tbody');
    var prevRun = '';
    rows.forEach(function (row) {
      var tr = document.createElement('tr');
      function add(text, className) {
        var td = document.createElement('td');
        if (className) td.className = className;
        td.textContent = text || '';
        tr.appendChild(td);
        return td;
      }
      var runKey = (row.sn || '') + '|' + (row.url || '');
      add(runKey !== prevRun ? (row.sn || '') : '', 'mono col-sn');
      prevRun = runKey;
      add(row.errorType, 'col-type');
      var testTd = document.createElement('td');
      testTd.className = 'col-test';
      (row.tests && row.tests.length ? row.tests : String(row.test || '').split(/,\s*/))
        .filter(Boolean)
        .forEach(function (name, index) {
          if (index) testTd.appendChild(document.createTextNode(', '));
          var span = document.createElement('span');
          span.className = 'fa-case';
          span.textContent = name;
          testTd.appendChild(span);
        });
      tr.appendChild(testTd);
      var passed = row.status === 'pass' || row.errorType === 'Passed';
      var timeTd = document.createElement('td');
      timeTd.className = 'mono col-time';
      var times = (row.times && row.times.length ? row.times.slice() : [])
        .concat(row.at ? [row.at] : []);
      var seenTime = {};
      var shown = 0;
      times.forEach(function (at) {
        var text = fmtTime(at);
        if (!text || seenTime[text]) return;
        seenTime[text] = true;
        if (shown) timeTd.appendChild(document.createTextNode(', '));
        shown += 1;
        var span = document.createElement('span');
        span.className = 'fa-time';
        span.textContent = text;
        timeTd.appendChild(span);
      });
      if (!passed && row.passAt) {
        var passText = fmtTime(row.passAt);
        if (passText && !seenTime[passText]) {
          if (shown) timeTd.appendChild(document.createElement('br'));
          var passSpan = document.createElement('span');
          passSpan.className = 'fa-time';
          passSpan.textContent = 'pass ' + passText;
          timeTd.appendChild(passSpan);
        }
      }
      tr.appendChild(timeTd);
      var codeTd = document.createElement('td');
      codeTd.className = 'mono col-code';
      if (!passed) {
        String(row.code || 'NA').split(/\n+/).forEach(function (code) {
          code = code.trim();
          if (!code) return;
          var line = document.createElement('span');
          line.className = 'fa-code';
          line.textContent = code;
          codeTd.appendChild(line);
        });
      }
      tr.appendChild(codeTd);
      var urlTd = document.createElement('td');
      urlTd.className = 'mono col-url';
      if (row.url) {
        var link = document.createElement('a');
        link.href = row.url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = 'ESVM';
        urlTd.appendChild(link);
      }
      tr.appendChild(urlTd);
      add(passed ? '' : (row.dri || DEFAULT_DRI), 'col-dri');
      var jiraTd = document.createElement('td');
      jiraTd.className = 'fa-jira col-jira';
      if (!passed) renderJiraCell(jiraTd, panel, report, row);
      tr.appendChild(jiraTd);
      body.appendChild(tr);
    });
    table.appendChild(body);
    host.appendChild(table);
  }

  function noteFor(panel, text) {
    var node = byId(panel.note);
    if (node) node.textContent = text || '';
  }

  function renderPanel(tab, panel) {
    var host = byId(panel.panel);
    if (!host) return;
    host.hidden = false;
    var dayNode = byId(panel.day);
    if (dayNode) dayNode.textContent = (tab && tab.day) || '';
    var report = reportFor(tab, panel);
    if (!report) {
      byId(panel.counts).textContent = 'No ' + panel.label + ' data for this day.';
      byId(panel.sns).textContent = '';
      byId(panel.csv).hidden = true;
      byId(panel.table).innerHTML = '';
      noteFor(panel, '');
      return;
    }
    byId(panel.csv).hidden = false;
    byId(panel.counts).textContent =
      report.passed + 'x Passed/ ' + report.tested + 'x DUT tested， yield(' +
      pct(report) + ')';
    var sns = report.failedSns || [];
    byId(panel.sns).textContent = sns.length
      ? 'Failed SN: ' + sns.join(', ')
      : 'Failed SN: none';
    bindCsv(panel, report);
    renderTable(panel, report);
    noteFor(panel, '');
  }

  function render(tab) {
    PANELS.forEach(function (panel) { renderPanel(tab, panel); });
  }

  function fileRow(panel, report, row, button, td) {
    if (row.jira || button.disabled) return;
    button.disabled = true;
    button.textContent = 'Filing…';
    noteFor(panel, 'Filing ' + (row.sn || '') + ' ' + (row.test || '') + '…');
    fetch('/api/fa-jiras', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Factory-Update': '1'
      },
      body: JSON.stringify({
        day: report.day,
        stage: report.stage || panel.stage,
        id: row.id
      })
    }).then(function (response) {
      return response.json().then(function (body) {
        return {ok: response.ok, body: body};
      });
    }).then(function (result) {
      if (!result.ok) {
        button.disabled = false;
        button.textContent = 'File Jira';
        noteFor(panel, result.body.error || 'Jira was not filed.');
        return;
      }
      var filed = result.body.filed || {};
      if (filed.url) row.jira = filed.url;
      renderJiraCell(td, panel, report, row);
      bindCsv(panel, report);
      noteFor(panel, filed.key || 'Filed.');
    }).catch(function () {
      button.disabled = false;
      button.textContent = 'File Jira';
      noteFor(panel, 'This page is not being served by the factory app, so Jira cannot be filed from here.');
    });
  }

  window.FaReport = {render: render, reportFor: reportFor, csvText: csvText,
                     fromTable: fromTable, expandFailRows: expandFailRows,
                     groupFailRows: groupFailRows};
  window.SftReport = {
    render: render,
    reportFor: function (tab) { return reportFor(tab, PANELS[1]); },
    csvText: csvText,
    fromTable: function (l10) { return fromTable(l10, 'sft'); }
  };
})();
