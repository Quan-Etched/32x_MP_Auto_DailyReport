/* L10 FAT / SFT / RIN reports for the selected day on Daily FA.

   Counts are one chassis, not one attempt. A later pass replaces an
   earlier fail. A later fail does not add a second failed chassis.

   The table is one row per SN + run + error type. Error type is only
   hardware or software. Test cases of that type stack in the cell.
   SN is written once per run. DRI is a dropdown. File Jira opens a
   preview first; Confirm files that row, Cancel leaves it unfiled.
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

  function errorTypeMap() {
    return (window.__FACTORY_DAILY_EXCEL__ || {}).errorTypes || {};
  }

  function driOptions() {
    var listed = (window.__FACTORY_DAILY_EXCEL__ || {}).driOptions;
    if (listed && listed.length) return listed;
    return ['Eason Chuang', 'Jonathan Wang', 'Software team'];
  }

  function normTest(name) {
    var text = String(name || '').trim();
    if (/TestCase$/i.test(text)) text = text.replace(/TestCase$/i, '');
    return text.replace(/MultiChip/ig, '').toLowerCase();
  }

  function lookupNamed(raw, map) {
    if (!raw) return '';
    if (map[raw]) return map[raw];
    var folded = normTest(raw);
    var best = '';
    var found = '';
    Object.keys(map).forEach(function (key) {
      var known = normTest(key);
      if (known === folded) {
        found = map[key];
        best = known;
        return;
      }
      if (folded.length < 8 || known.length < 8) return;
      if ((folded.indexOf(known) === 0 || known.indexOf(folded) === 0) &&
          known.length > best.length) {
        best = known;
        found = map[key];
      }
    });
    return found;
  }

  function errorTypeOfTest(name) {
    var raw = String(name || '').trim();
    if (!raw) return 'hardware';
    var found = String(lookupNamed(raw, errorTypeMap()) || '').toLowerCase();
    if (found === 'hardware' || found === 'software') return found;
    var lower = raw.toLowerCase();
    if (/llama|huggingface|inferencemax|modelregistry/.test(lower)) {
      return 'software';
    }
    return 'hardware';
  }

  function asErrorType(value, test) {
    var text = String(value || '').trim().toLowerCase();
    if (text === 'passed') return 'Passed';
    if (text === 'hardware' || text === 'software') return text;
    return errorTypeOfTest(test);
  }

  function defaultDri(errorType) {
    if (errorType === 'Passed' || !errorType) return '';
    if (errorType === 'software') return 'Software team';
    return 'Eason Chuang';
  }

  function asDri(value, errorType) {
    if (errorType === 'Passed' || !errorType) return '';
    var options = driOptions();
    if (options.indexOf(value) >= 0) return value;
    return defaultDri(errorType);
  }

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
          dri: asDri(leaf.dri, leaf.errorType),
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
        row.errorType = asErrorType(row.errorType, row.test);
        row.dri = asDri(row.dri, row.errorType);
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
        var errorType = asErrorType(row.errorType, test);
        found.push({
          id: rowId(row.sn, test, row.url, row.at),
          sn: row.sn || '',
          errorType: errorType,
          test: test,
          caseId: caseIds[index] || test,
          at: row.at || '',
          code: codes[index] || row.code || 'NA',
          url: row.url || '',
          jira: row.jira || '',
          dri: asDri(row.dri, errorType),
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
        var errorType = errorTypeOfTest(test);
        rows.push({
          id: rowId(sn, test, last.url, at),
          sn: sn,
          errorType: errorType,
          test: test,
          caseId: item.caseId || test,
          at: at,
          passAt: passAt,
          code: item.code || 'NA',
          url: last.url,
          jira: item.jira || last.jira || '',
          dri: defaultDri(errorType),
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

  function ticketSummary(report, row) {
    var label = stageLabel(report.stage || '');
    var tests = row.tests && row.tests.length
      ? row.tests.slice()
      : String(row.test || '').split(/,\s*/).filter(Boolean);
    var test = tests[0] || row.test || 'unclassified failure';
    var named = tests.length !== 1 ? (row.errorType || test) : test;
    return label + ' ' + (report.day || '') + ' ' + (row.sn || '') + ' ' + named;
  }

  function rememberedUrl(report, row) {
    if (row.jira) return row.jira;
    var book = window.__FA_FILED__ || {};
    var rows = book.rows || {};
    var gid = groupId(row.sn, row.errorType, row.url);
    var hit = rows[gid] || rows[row.id || ''];
    if (hit && hit.url) return hit.url;
    var summaries = [ticketSummary(report, row)];
    var byType = stageLabel(report.stage || '') + ' ' + (report.day || '') +
      ' ' + (row.sn || '') + ' ' + (row.errorType || '');
    if (row.errorType && summaries.indexOf(byType) < 0) summaries.push(byType);
    var issues = book.issues || [];
    for (var i = 0; i < issues.length; i++) {
      if (summaries.indexOf(issues[i].summary) >= 0 && issues[i].url) {
        return issues[i].url;
      }
    }
    return '';
  }

  function stampRemembered(report) {
    (report.rows || []).forEach(function (row) {
      var url = rememberedUrl(report, row);
      if (url) row.jira = url;
    });
  }

  function reportFor(tab, panel) {
    var l10 = tab && tab.l10;
    var stored = l10 && l10[panel.key];
    if (stored) {
      stored.stage = stored.stage || panel.stage;
      stored.day = stored.day || (tab && tab.day) || '';
      expandFailRows(stored);
      stampRemembered(stored);
      return stored;
    }
    if (l10 && l10.columns) {
      var built = fromTable(l10, panel.stage);
      if (built) stampRemembered(built);
      return built;
    }
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
                  row.errorType === 'Passed' ? '' : asDri(row.dri, row.errorType),
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
    button.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      fileRow(panel, report, row, button, td);
    });
    td.appendChild(button);
  }

  function dataLinkLabel(url) {
    var host = (/\/\/([^/:]+)/.exec(String(url || '')) || [])[1] || '';
    var named = /pega(\d+)/i.exec(host);
    if (named) return 'Pega' + named[1];
    if (!host) return 'DataLink';
    return host.charAt(0).toUpperCase() + host.slice(1);
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
      ['DataLink', 'col-url'],
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
        link.textContent = dataLinkLabel(row.url);
        urlTd.appendChild(link);
      }
      tr.appendChild(urlTd);
      var driTd = document.createElement('td');
      driTd.className = 'col-dri';
      if (!passed) {
        var select = document.createElement('select');
        select.className = 'fa-dri';
        var chosen = asDri(row.dri, row.errorType);
        row.dri = chosen;
        driOptions().forEach(function (name) {
          var option = document.createElement('option');
          option.value = name;
          option.textContent = name;
          if (name === chosen) option.selected = true;
          select.appendChild(option);
        });
        select.addEventListener('change', function () {
          row.dri = select.value;
          (report.rows || []).forEach(function (leaf) {
            if (groupId(leaf.sn, leaf.errorType, leaf.url) === row.id) {
              leaf.dri = select.value;
            }
          });
          bindCsv(panel, report);
        });
        driTd.appendChild(select);
      }
      tr.appendChild(driTd);
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

  var lastTab = null;

  function render(tab) {
    lastTab = tab;
    PANELS.forEach(function (panel) { renderPanel(tab, panel); });
  }

  function loadFiled() {
    fetch('/api/fa-jiras', {cache: 'no-store'}).then(function (response) {
      if (!response.ok) return null;
      return response.json();
    }).then(function (book) {
      if (!book || !book.rows && !book.issues) return;
      window.__FA_FILED__ = book;
      if (lastTab) render(lastTab);
    }).catch(function () {});
  }

  function postFa(path, payload) {
    return fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Factory-Update': '1'
      },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.text().then(function (text) {
        var body = {};
        try {
          body = text ? JSON.parse(text) : {};
        } catch (e) {
          body = {};
        }
        if (!body || typeof body !== 'object') body = {};
        if (!response.ok && !body.error) {
          body.error = 'Jira was not filed (HTTP ' + response.status + ').';
        }
        return {ok: response.ok, body: body};
      });
    });
  }

  function stageLabel(stage) {
    if (stage === 'fat') return 'L10 FAT';
    if (stage === 'sft') return 'L10 SFT';
    if (stage === 'rin') return 'L10 RIN';
    return 'L10 ' + String(stage || '').toUpperCase();
  }

  function localPreview(panel, report, row) {
    var stage = report.stage || panel.stage;
    var label = stageLabel(stage);
    var day = report.day || '';
    var sn = row.sn || '';
    var tests = row.tests && row.tests.length
      ? row.tests.slice()
      : String(row.test || '').split(/,\s*/).filter(Boolean);
    var test = tests[0] || row.test || 'unclassified failure';
    var errorType = row.errorType || '';
    var named = tests.length !== 1 ? (errorType || test) : test;
    var dri = row.dri || '';
    var at = '';
    if (row.times && row.times.length) at = row.times[0];
    else at = row.at || '';
    var summary = [label, day, sn, named].join(' ').replace(/\s+/g, ' ').trim();
    if (summary.length > 255) summary = summary.slice(0, 255);
    var markdown = [
      label + ' ' + day + ' failed ' + named + ' on ' + (sn || 'unknown SN') + '.',
      '',
      'Error type: ' + errorType,
      'Test case: ' + (tests.join('\n') || test),
      'Error code: ' + (row.code || 'NA'),
      'DRI: ' + dri,
      'Tested at: ' + (at || 'unknown'),
      'pega URL: ' + (row.url || 'none'),
      ''
    ].join('\n');
    return {
      sn: sn,
      test: test,
      errorType: errorType,
      dri: dri,
      epic: 'ETCH-44407',
      summary: summary,
      markdown: markdown
    };
  }

  function faDialog() {
    var node = byId('fa-jira-dialog');
    if (node) return node;
    var dialog = document.createElement('dialog');
    dialog.id = 'fa-jira-dialog';
    dialog.className = 'fa-dialog';
    dialog.setAttribute('aria-labelledby', 'fa-dialog-title');
    dialog.innerHTML =
      '<h2 id="fa-dialog-title">Preview Jira ticket</h2>' +
      '<p class="fa-dialog-meta" id="fa-dialog-meta"></p>' +
      '<label class="fa-dialog-field">Summary' +
      '<input id="fa-dialog-summary" type="text" maxlength="255"></label>' +
      '<label class="fa-dialog-field">Description' +
      '<textarea id="fa-dialog-body" rows="14" spellcheck="true"></textarea></label>' +
      '<p class="fa-dialog-error" id="fa-dialog-error" hidden></p>' +
      '<div class="fa-dialog-actions">' +
      '<button type="button" class="fa-dialog-cancel" id="fa-dialog-cancel">Cancel</button>' +
      '<button type="button" class="fa-dialog-confirm" id="fa-dialog-confirm">Confirm</button>' +
      '</div>';
    document.body.appendChild(dialog);
    dialog.addEventListener('cancel', function (event) {
      event.preventDefault();
      closeFaDialog(false);
    });
    dialog.addEventListener('click', function (event) {
      if (dialog.classList.contains('fa-dialog-armed')) return;
      var box = dialog.getBoundingClientRect();
      var outside = event.clientX < box.left || event.clientX > box.right ||
        event.clientY < box.top || event.clientY > box.bottom;
      if (outside) closeFaDialog(false);
    });
    dialog.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      if (event.target && event.target.id === 'fa-dialog-confirm') return;
      event.preventDefault();
    });
    byId('fa-dialog-cancel').addEventListener('click', function () {
      closeFaDialog(false);
    });
    byId('fa-dialog-confirm').addEventListener('click', confirmFaDialog);
    return dialog;
  }

  var faDialogState = null;
  var faDialogArm = 0;

  function setFaDialogError(text) {
    var node = byId('fa-dialog-error');
    if (!node) return;
    if (text) {
      node.hidden = false;
      node.textContent = text;
    } else {
      node.hidden = true;
      node.textContent = '';
    }
  }

  function closeFaDialog(filed) {
    if (faDialogState && faDialogState.filing && !filed) return;
    var dialog = byId('fa-jira-dialog');
    if (dialog) {
      dialog.classList.remove('fa-dialog-armed');
      if (dialog.open) dialog.close();
    }
    var state = faDialogState;
    faDialogState = null;
    if (!state) return;
    if (!filed) {
      state.button.disabled = false;
      state.button.textContent = 'File Jira';
      noteFor(state.panel, '');
      state.button.focus();
    }
  }

  function armFaDialog(dialog) {
    var token = Date.now();
    faDialogArm = token;
    dialog.classList.add('fa-dialog-armed');
    var confirm = byId('fa-dialog-confirm');
    confirm.disabled = true;
    function ready() {
      if (faDialogArm !== token) return;
      dialog.classList.remove('fa-dialog-armed');
      if (faDialogState && !faDialogState.filing) confirm.disabled = false;
      var summary = byId('fa-dialog-summary');
      if (summary) summary.focus();
    }
    window.setTimeout(ready, 450);
  }

  function openFaDialog(state, preview) {
    var dialog = faDialog();
    faDialogState = state;
    byId('fa-dialog-meta').textContent = [
      preview.sn, preview.errorType, preview.dri, preview.epic
    ].filter(Boolean).join(' · ');
    byId('fa-dialog-summary').value = preview.summary || '';
    byId('fa-dialog-body').value = preview.markdown || '';
    setFaDialogError('');
    var confirm = byId('fa-dialog-confirm');
    confirm.textContent = 'Confirm';
    byId('fa-dialog-cancel').disabled = false;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    armFaDialog(dialog);
  }

  function confirmFaDialog() {
    var state = faDialogState;
    var dialog = byId('fa-jira-dialog');
    if (!state || (dialog && dialog.classList.contains('fa-dialog-armed'))) return;
    var summary = (byId('fa-dialog-summary').value || '').trim();
    var markdown = byId('fa-dialog-body').value || '';
    if (!summary) {
      setFaDialogError('Summary cannot be empty.');
      byId('fa-dialog-summary').focus();
      return;
    }
    var confirm = byId('fa-dialog-confirm');
    confirm.disabled = true;
    confirm.textContent = 'Filing…';
    byId('fa-dialog-cancel').disabled = true;
    state.filing = true;
    setFaDialogError('');
    noteFor(state.panel, 'Filing ' + (state.row.sn || '') + '…');
    postFa('/api/fa-jiras', {
      day: state.report.day,
      stage: state.report.stage || state.panel.stage,
      id: state.row.id,
      dri: state.row.dri,
      summary: summary,
      markdown: markdown
    }).then(function (result) {
      byId('fa-dialog-cancel').disabled = false;
      if (!result.ok) {
        state.filing = false;
        confirm.disabled = false;
        confirm.textContent = 'Confirm';
        setFaDialogError(result.body.error || 'Jira was not filed.');
        noteFor(state.panel, result.body.error || 'Jira was not filed.');
        return;
      }
      var filed = result.body.filed || {};
      if (filed.url) state.row.jira = filed.url;
      renderJiraCell(state.td, state.panel, state.report, state.row);
      bindCsv(state.panel, state.report);
      noteFor(state.panel, filed.key || 'Filed.');
      closeFaDialog(true);
    }).catch(function () {
      state.filing = false;
      byId('fa-dialog-cancel').disabled = false;
      confirm.disabled = false;
      confirm.textContent = 'Confirm';
      setFaDialogError(
        'This page is not being served by the factory app, so Jira cannot be filed from here.');
    });
  }

  function fileRow(panel, report, row, button, td) {
    if (row.jira || button.disabled) return;
    button.disabled = true;
    button.textContent = 'Preview…';
    noteFor(panel, '');
    var preview = localPreview(panel, report, row);
    window.setTimeout(function () {
      openFaDialog({
        panel: panel,
        report: report,
        row: row,
        button: button,
        td: td
      }, preview);
    }, 0);
  }

  loadFiled();

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
