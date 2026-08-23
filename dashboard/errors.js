/* Section 4 of the customize page: failures as error codes.
 *
 * WHAT IT SHOWS
 * One row per failing (unit, station, test case), joined to the error-code
 * catalogue Ulysses Kao maintains. The columns are the ones asked for:
 *
 *   Error Code | DUT_SN | Date | Station | FI | Root Cause | Corrective Action | Note
 *
 * FI is the line's own abbreviation and its own column heading in the daily
 * tracker — the link to the run that failed. It is kept rather than renamed so
 * a reader coming from the tracker recognises it.
 *
 * A test case usually maps to more than one code (125 of 177 in the
 * catalogue), because the code says *how* the case failed and the tracker
 * records only that it did. Those rows list every candidate and say so. Rows
 * whose case is not in the catalogue at all are kept and counted: an
 * uncatalogued failure mode is the more interesting finding, and a table that
 * dropped them would report the line as fully catalogued.
 *
 * ADMIN
 * Root Cause, Corrective Action and Note are people's work. Signing in unlocks
 * those three cells and nothing else. A save goes to the annotation service,
 * which writes errors/annotations.json and commits it.
 *
 * The sign-in here is a gate on the interface, not on the data: this is a
 * static page and anything it knows, a reader can read. The service holds its
 * own copy of the credential and checks it again, so an edit cannot be written
 * by editing this file. Without the service reachable, edits stay in the
 * browser and the page offers the exact JSON to commit by hand.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_ERRORS__ || {};
  var ROWS = DATA.rows || [];
  var CODES = DATA.codes || {};
  var LABELS = DATA.stationLabels || {};
  var CAT = DATA.catalogue || {};

  /* Where a save goes. Same origin, so nothing is configured per deployment:
     if the service is not mounted there, the page finds out on the first save
     and says so rather than pretending it worked. */
  var SAVE_URL = 'annotate';

  /* Whose edits are accepted. The list is here so the sign-in can name who it
     expects; the service keeps its own copy and is the one that decides. */
  var ADMINS = ['chuck', 'eason', 'chris'];

  var EDITABLE = ['rootCause', 'correctiveAction', 'note'];

  /* Root cause is a choice between two answers, not a text box. "Test setup"
     or "true DUT failure" is the decision the line acts on — whether to look at
     the harness or scrap the part — and a free-text field produced a dozen
     spellings of each and nothing countable. Detail goes in the note. */
  var CAUSES = DATA.causes || { setup: 'Test setup', dut: 'True DUT failure' };
  var CAUSE_ORDER = ['setup', 'dut'];

  var view = {
    from: null, to: null,
    stations: null,          /* null = every station, until section 2 reports */
    admin: null,             /* the signed-in name, or null */
    dirty: {},               /* key -> the fields edited but not yet saved */
    sort: null,              /* column index, or null for the default order */
    desc: false
  };

  function h(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') { node.textContent = attrs[key]; }
      else if (key === 'class') { node.className = attrs[key]; }
      else if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, attrs[key]);
      }
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  function keyOf(row) {
    return [row.day, row.station, row.dut, row.case].join('|');
  }

  /* The value shown: an unsaved edit wins over what the bundle was built with,
     so a cell does not appear to revert while a save is in flight. */
  function valueOf(row, field) {
    var pending = view.dirty[keyOf(row)];
    if (pending && pending[field] !== undefined) return pending[field];
    return row[field] || '';
  }

  /* ------------------------------------------------------------------- days */

  var DAYS = (function () {
    var seen = {};
    ROWS.forEach(function (row) { if (row.day) seen[row.day] = true; });
    return Object.keys(seen).sort();
  })();

  function shift(day, days) {
    var at = new Date(day + 'T00:00:00Z');
    at.setUTCDate(at.getUTCDate() + days);
    return at.toISOString().slice(0, 10);
  }

  function defaults() {
    /* A week, ending on the last day with a failure. The sections above carry
       whatever range someone set for a CSV pull; three weeks of failures is a
       wall, and "this week" is what a failure table is nearly always for. */
    var last = DAYS.length ? DAYS[DAYS.length - 1] : null;
    view.to = view.to || last;
    view.from = view.from || (last ? shift(last, -6) : null);
    if (DAYS.length && view.from < DAYS[0]) view.from = DAYS[0];
  }

  function inRange(row) {
    if (view.from && row.day < view.from) return false;
    if (view.to && row.day > view.to) return false;
    if (view.stations && view.stations.indexOf(row.station) === -1) return false;
    return true;
  }

  function selected() {
    return ROWS.filter(inRange);
  }

  /* --------------------------------------------------------------- the cells */

  function codeCell(row) {
    if (!row.codes || !row.codes.length) {
      return h('span', { class: 'ec-none',
                         title: 'this test case is not in the catalogue' },
               [h('span', { text: '—' })]);
    }
    var wrap = h('span', { class: 'ec-codes' });
    row.codes.forEach(function (code, at) {
      var info = CODES[code] || {};
      if (at) wrap.appendChild(document.createTextNode(' '));
      wrap.appendChild(h('span', {
        class: 'ec-code' + (row.codes.length > 1 ? ' ec-code-maybe' : ''),
        title: [info.message || '', info.action ? '→ ' + info.action : '',
                info.bugs ? info.bugs : ''].filter(Boolean).join('\n\n')
      }, [h('span', { text: code })]));
    });
    /* Two codes on one row is not a diagnosis, and must not read as one. */
    if (row.codes.length > 1) {
      wrap.appendChild(h('span', { class: 'ec-maybe-note',
        title: 'the catalogue maps this test case to more than one code; the '
             + 'tracker records only that the case failed',
        text: ' ' + row.codes.length + ' possible' }));
    }
    return wrap;
  }

  /* Root cause reads as a labelled chip so the two answers are tellable apart
     down a column of eighty rows, which is the only way this column earns its
     width. An established cause says so: the row did not need somebody to
     decide it, and the reader should know which rows are settled. */
  function causeCell(row) {
    var value = valueOf(row, 'rootCause');
    if (view.admin) {
      var pick = h('select', { class: 'ec-edit ec-pick' });
      pick.appendChild(h('option', { value: '', text: '— not decided —' }));
      CAUSE_ORDER.forEach(function (key) {
        pick.appendChild(h('option', { value: key, text: CAUSES[key] }));
      });
      pick.value = value;
      pick.addEventListener('change', function () {
        stage(row, 'rootCause', pick.value);
      });
      return pick;
    }
    if (!value) return h('span', { class: 'ec-blank', text: 'not decided' });
    var wrap = h('span', { class: 'ec-cause ec-cause-' + value }, [
      h('span', { text: CAUSES[value] || value })
    ]);
    if (row.established) {
      wrap.appendChild(h('span', { class: 'ec-settled',
        title: 'established for this test case, not decided per unit — see '
             + 'errors/established.json',
        text: ' established' }));
    }
    return wrap;
  }

  /* One place edits are recorded, so the select and the textareas agree about
     what "back to what it was" means. */
  function stage(row, field, value) {
    var key = keyOf(row);
    var pending = view.dirty[key] || (view.dirty[key] = {});
    pending[field] = value;
    if (value === (row[field] || '')) {
      delete pending[field];
      if (!Object.keys(pending).length) delete view.dirty[key];
    }
    renderAdmin();
  }

  function editable(row, field, placeholder) {
    var value = valueOf(row, field);
    if (!view.admin) {
      return value
        ? h('span', { class: 'ec-said', text: value })
        : h('span', { class: 'ec-blank', text: '—' });
    }
    var box = h('textarea', {
      class: 'ec-edit', rows: '1', placeholder: placeholder,
      'data-key': keyOf(row), 'data-field': field
    });
    box.value = value;
    box.addEventListener('input', function () {
      stage(row, field, box.value);
    });
    return box;
  }

  function fiCell(row) {
    if (!row.fi) return h('span', { class: 'ec-blank', text: '—' });
    return h('a', {
      class: 'ec-fi', href: row.fi, target: '_blank',
      rel: 'noopener noreferrer', title: row.fi
    }, [h('span', { text: row.run || 'run' })]);
  }

  /* ------------------------------------------------------------------ table */

  var COLUMNS = [
    ['Error Code', codeCell],
    ['DUT_SN', function (row) {
      return h('span', { class: 'mono', text: row.dut }); }],
    ['Date', function (row) { return h('span', { text: row.day }); }],
    ['Station', function (row) {
      return h('span', { text: LABELS[row.station] || row.station }); }],
    ['FI', fiCell],
    ['Root Cause', causeCell],
    ['Corrective Action', function (row) {
      return editable(row, 'correctiveAction', 'what was done about it'); }],
    ['Note', function (row) { return editable(row, 'note', 'anything else'); }]
  ];

  /* What each column sorts on. Not the rendered text: the code column renders
     a chip and a case name, and sorting a table by its own markup is how a
     column ends up ordered by "<span". */
  var SORT_KEY = [
    function (row) { return (row.codes || [])[0] || '\uffff'; },
    function (row) { return row.dut; },
    function (row) { return row.day; },
    function (row) { return LABELS[row.station] || row.station; },
    function (row) { return row.run || ''; },
    function (row) { return valueOf(row, 'rootCause'); },
    function (row) { return valueOf(row, 'correctiveAction'); },
    function (row) { return valueOf(row, 'note'); }
  ];

  function compare(left, right) {
    var a = SORT_KEY[view.sort](left), b = SORT_KEY[view.sort](right);
    /* Blank last whichever way the arrow points. A column sorted to put eighty
       empty cells at the top is a column nobody sorted on purpose. */
    if (!a && b) return 1;
    if (a && !b) return -1;
    if (a === b) return 0;
    return (a < b ? -1 : 1) * (view.desc ? -1 : 1);
  }

  /* The default order, when nothing is sorted: settled cases first, then
     newest. An established root cause is the answer somebody already worked
     out, and burying it under three hundred undecided rows means the next
     person works it out again. */
  function ordered(rows) {
    var out = rows.slice();
    if (view.sort === null) {
      out.sort(function (a, b) {
        if (!!b.established !== !!a.established) return a.established ? -1 : 1;
        if (a.day !== b.day) return a.day < b.day ? 1 : -1;
        return a.dut < b.dut ? -1 : 1;
      });
      return out;
    }
    out.sort(compare);
    return out;
  }

  /* The failing test case is the join key and belongs on screen — it is what
     someone recognises from the tracker, and on a multi-code row it is the only
     thing that is certain. It rides under the code rather than taking a ninth
     column. */
  function renderTable(rows) {
    var head = byId('err-head'), body = byId('err-body');
    head.innerHTML = ''; body.innerHTML = '';
    var tr = h('tr', {});
    COLUMNS.forEach(function (column, at) {
      var on = view.sort === at;
      var button = h('button', {
        type: 'button', class: 'ec-sort' + (on ? ' on' : ''),
        title: 'sort by ' + column[0]
      }, [
        h('span', { text: column[0] }),
        h('span', { class: 'ec-arrow',
                    text: on ? (view.desc ? ' \u2193' : ' \u2191') : ' \u21c5' })
      ]);
      button.addEventListener('click', function () {
        if (view.sort === at) {
          /* Third click clears it, back to settled-first. Otherwise there is no
             way back to the default order without reloading. */
          if (view.desc) { view.sort = null; view.desc = false; }
          else { view.desc = true; }
        } else {
          view.sort = at; view.desc = false;
        }
        render();
      });
      tr.appendChild(h('th', { scope: 'col',
        'aria-sort': on ? (view.desc ? 'descending' : 'ascending') : 'none'
      }, [button]));
    });
    head.appendChild(tr);
    ordered(rows).forEach(function (row) {
      var classes = [];
      if (view.dirty[keyOf(row)]) classes.push('ec-dirty');
      if (row.established) classes.push('ec-est');
      var line = h('tr', { class: classes.join(' ') });
      COLUMNS.forEach(function (column, at) {
        var td = h('td', { class: at > 5 ? 'ec-note-cell' : '' });
        td.appendChild(column[1](row));
        if (at === 0) {
          td.appendChild(h('span', { class: 'ec-case', text: row.case }));
        }
        line.appendChild(td);
      });
      body.appendChild(line);
    });
  }

  /* ------------------------------------------------------------------ admin */

  function renderAdmin() {
    var host = byId('err-admin');
    var pending = Object.keys(view.dirty).length;
    host.innerHTML = '';

    if (!view.admin) {
      var signIn = h('button', { type: 'button', class: 'view-toggle ec-admin',
        title: 'sign in to record root cause, corrective action and notes' },
        [h('span', { text: 'Admin' })]);
      signIn.addEventListener('click', promptSignIn);
      host.appendChild(signIn);
      return;
    }

    host.appendChild(h('span', { class: 'ec-who',
      text: 'signed in as ' + view.admin }));

    var save = h('button', { type: 'button',
      class: 'view-toggle ec-save' + (pending ? ' on' : ''),
      disabled: pending ? null : 'disabled',
      title: pending ? 'write these to errors/annotations.json and commit'
                     : 'nothing edited yet' },
      [h('span', { text: pending ? 'Save ' + plural(pending, 'row') : 'Save' })]);
    save.addEventListener('click', save_);
    host.appendChild(save);

    var out = h('button', { type: 'button', class: 'view-toggle',
      title: 'sign out' }, [h('span', { text: 'Sign out' })]);
    out.addEventListener('click', function () {
      if (pending && !window.confirm(
          plural(pending, 'row') + ' edited but not saved. Sign out anyway?')) {
        return;
      }
      view.admin = null; view.dirty = {};
      render();
    });
    host.appendChild(out);
  }

  function promptSignIn() {
    var who = (window.prompt('Admin name (' + ADMINS.join(', ') + ')') || '')
      .trim().toLowerCase();
    if (!who) return;
    if (ADMINS.indexOf(who) === -1) {
      notice('“' + who + '” is not an admin name. Expected one of: '
             + ADMINS.join(', ') + '.', 'bad');
      return;
    }
    var pass = window.prompt('Password for ' + who) || '';
    if (!pass) return;
    /* Not checked here. The service checks it, because a check in this file is
       a check anybody can read and skip — signing in only opens the cells, and
       an edit is refused at save time if the credential is wrong. */
    view.admin = who;
    view.pass = pass;
    notice('Signed in as ' + who + '. Root cause, corrective action and note '
           + 'are editable; everything else stays read-only. Your password is '
           + 'checked when you save.', 'ok');
    render();
  }

  function notice(text, tone) {
    var host = byId('err-admin-note');
    host.hidden = false;
    host.className = 'banner' + (tone ? ' ' + tone : '');
    host.textContent = text;
  }

  function save_() {
    var edits = [];
    Object.keys(view.dirty).forEach(function (key) {
      var parts = key.split('|');
      var fields = view.dirty[key];
      var entry = { day: parts[0], station: parts[1], dut: parts[2],
                    case: parts.slice(3).join('|') };
      EDITABLE.forEach(function (field) {
        if (fields[field] !== undefined) entry[field] = fields[field];
      });
      edits.push(entry);
    });
    if (!edits.length) return;

    notice('Saving ' + plural(edits.length, 'row') + '…', '');
    var request = new XMLHttpRequest();
    request.open('POST', SAVE_URL, true);
    request.setRequestHeader('Content-Type', 'application/json');
    request.onreadystatechange = function () {
      if (request.readyState !== 4) return;
      if (request.status >= 200 && request.status < 300) {
        var reply = {};
        try { reply = JSON.parse(request.responseText || '{}'); } catch (e) {}
        /* Apply locally so the table shows what was written without a rebuild
           — the bundle only picks these up on the next `make errors`. */
        Object.keys(view.dirty).forEach(function (key) {
          var fields = view.dirty[key];
          ROWS.forEach(function (row) {
            if (keyOf(row) !== key) return;
            EDITABLE.forEach(function (field) {
              if (fields[field] !== undefined) row[field] = fields[field];
            });
            row.by = view.admin;
          });
        });
        view.dirty = {};
        notice('Saved ' + plural(edits.length, 'row') + '.'
               + (reply.commit ? ' Committed as ' + reply.commit + '.' : '')
               + ' The published table updates on the next rebuild.', 'ok');
        render();
      } else if (request.status === 401 || request.status === 403) {
        notice('Rejected: the service did not accept that name and password. '
               + 'Nothing was written. Your edits are still on screen.', 'bad');
      } else {
        offerManual(edits, request.status);
      }
    };
    request.send(JSON.stringify({
      user: view.admin, password: view.pass, edits: edits
    }));
  }

  /* No service reachable. Rather than lose the work, hand over the exact JSON
     to paste into errors/annotations.json — the page is static and published
     from a box with no writable backend, so this is the honest fallback. */
  function offerManual(edits, status) {
    var payload = {};
    edits.forEach(function (entry) {
      var key = [entry.day, entry.station, entry.dut, entry.case].join('|');
      var out = {};
      EDITABLE.forEach(function (field) {
        if (entry[field] !== undefined) out[field] = entry[field];
      });
      out.by = view.admin;
      payload[key] = out;
    });
    var host = byId('err-admin-note');
    host.hidden = false;
    host.className = 'banner bad';
    host.innerHTML = '';
    host.appendChild(h('p', { text:
      'No annotation service answered (' + (status || 'no response') + '), so '
      + 'nothing was written. Your edits are below — paste them into the '
      + '"entries" object in errors/annotations.json and commit, or start the '
      + 'service with `make annotate` and press Save again.' }));
    var box = h('textarea', { class: 'ec-manual', rows: '8', readonly: 'readonly' });
    box.value = JSON.stringify(payload, null, 1);
    host.appendChild(box);
  }

  /* ----------------------------------------------------------------- chrome */

  function renderPickers() {
    ['from', 'to'].forEach(function (which) {
      var input = byId('err-' + which);
      if (!input) return;
      input.value = view[which] || '';
      if (DAYS.length) {
        input.setAttribute('min', DAYS[0]);
        input.setAttribute('max', DAYS[DAYS.length - 1]);
      }
    });
  }

  function renderQuick() {
    var host = byId('err-quick');
    host.innerHTML = '';
    if (!DAYS.length) return;
    var last = DAYS[DAYS.length - 1];
    [['This week', 6], ['2 weeks', 13], ['Everything', null]].forEach(
      function (spec) {
        var from = spec[1] === null ? DAYS[0] : shift(last, -spec[1]);
        if (from < DAYS[0]) from = DAYS[0];
        var on = view.from === from && view.to === last;
        var button = h('button', {
          type: 'button', class: 'view-toggle' + (on ? ' on' : '')
        }, [h('span', { text: spec[0] })]);
        button.addEventListener('click', function () {
          view.from = from; view.to = last; render();
        });
        host.appendChild(button);
      });
  }

  /* The CSV carries more than the table does: the code's quick action,
     component and known bugs are one lookup away on screen (the code's title)
     but a spreadsheet cannot hover, and those columns are what somebody
     pivoting on error code actually wants. Built from the rows rather than
     scraped off the DOM for the same reason. */
  function csvRows(rows) {
    var lines = [['Error_Code', 'Possible_Codes', 'Test_Case', 'DUT_SN',
                  'Date_UTC', 'Station', 'FI_Link', 'Quick_Action', 'Component',
                  'Bugs', 'Root_Cause', 'Root_Cause_Established',
                  'Corrective_Action', 'Note', 'Noted_By']];
    ordered(rows).forEach(function (row) {
      var one = row.codes && row.codes.length === 1 ? row.codes[0] : '';
      var info = CODES[one] || {};
      var cause = valueOf(row, 'rootCause');
      lines.push([
        one, (row.codes || []).join('; '), row.case, row.dut, row.day,
        LABELS[row.station] || row.station, row.fi || '',
        info.action || '', info.component || '', info.bugs || '',
        /* The label, not the key: a spreadsheet reader should not have to know
           that "setup" means the harness. */
        cause ? (CAUSES[cause] || cause) : '',
        row.established ? 'yes' : '',
        valueOf(row, 'correctiveAction'), valueOf(row, 'note'), row.by || ''
      ]);
    });
    return lines;
  }

  function renderDownload(rows) {
    var host = byId('err-download');
    host.innerHTML = '';
    if (!window.FactoryCsv || !rows.length) return;
    window.FactoryCsv.attach(host, {
      label: 'Download CSV',
      title: 'the rows on screen, with each code\u2019s quick action and bugs',
      name: function () {
        return 'error-codes-' + view.from + '_to_' + view.to + '.csv';
      },
      rows: function () { return csvRows(selected()); }
    });
  }

  function renderNotes(rows) {
    var sub = byId('err-sub');
    sub.textContent = rows.length
      ? plural(rows.length, 'failure') + ' from ' + view.from + ' to ' +
        view.to + ' (UTC)'
      : 'No failure in this range at the stations picked above.';

    var settled = rows.filter(function (row) {
      return valueOf(row, 'rootCause'); }).length;
    var one = rows.filter(function (row) {
      return row.codes && row.codes.length === 1; }).length;
    var many = rows.filter(function (row) {
      return row.codes && row.codes.length > 1; }).length;
    var none = rows.length - one - many;

    byId('err-note').innerHTML = '';
    byId('err-note').appendChild(h('span', { text:
      'One row per failing unit, station and test case, from the same tracker '
      + 'the daily page reads. ' + one + ' resolve to a single error code, '
      + many + ' to more than one — the catalogue maps a test case to several '
      + 'codes when the code says how it failed and the tracker records only '
      + 'that it did — and ' + none + ' to none. FI is the line’s own column '
      + 'name for the link to the run. Root cause is one of two answers — '
      + '“' + CAUSES.setup + '” or “' + CAUSES.dut + '” — because that is the '
      + 'decision the line acts on; ' + settled + ' of these ' + rows.length
      + ' have one, and rows with a cause established for the whole test case '
      + 'sort to the top. Everything else goes in the note. ' }));
    byId('err-note').appendChild(h('a', {
      class: 'ec-cat', href: CAT.source || '#', target: '_blank',
      rel: 'noopener noreferrer',
      text: 'The full error-code sheet →'
    }));
    byId('err-note').appendChild(h('span', { text:
      ' ' + (CAT.codes || 0) + ' codes over ' + (CAT.cases || 0) + ' test '
      + 'cases, read ' + (CAT.readOn || 'unknown') + '.' }));

    var unknown = DATA.uncatalogued || [];
    var host = byId('err-unknown');
    host.innerHTML = '';
    if (!unknown.length) { host.hidden = true; return; }
    host.hidden = false;
    /* Named rather than dropped: a failure mode nobody has catalogued is the
       interesting one, and a table that hid these would read as complete. */
    host.appendChild(h('strong', { text: 'Not in the catalogue: ' }));
    host.appendChild(h('span', { text:
      unknown.length + ' test ' + (unknown.length === 1 ? 'case' : 'cases')
      + ', ' + unknown.reduce(function (n, item) { return n + item.rows; }, 0)
      + ' rows — ' + unknown.slice(0, 6).map(function (item) {
        return item.case + ' ×' + item.rows;
      }).join(', ') + (unknown.length > 6 ? ', …' : '')
      + '. Worth adding to the sheet.' }));
  }

  function render() {
    if (view.from && view.to && view.from > view.to) {
      var swap = view.from; view.from = view.to; view.to = swap;
    }
    var rows = selected();
    renderQuick();
    renderPickers();
    renderTable(rows);
    renderDownload(rows);
    renderNotes(rows);
    renderAdmin();
  }

  /* Section 2 reports its station selection here. */
  window.FactoryErrors = {
    stations: function (keys) {
      var next = (keys || []).slice().sort().join(',');
      var now = (view.stations || []).slice().sort().join(',');
      if (next === now) return;
      view.stations = keys.slice();
      if (view.ready) render();
    }
  };

  /* The retired retest page redirects here with #section=errors. Scroll to it,
     because landing at the top of a three-section page having asked for the
     fourth is indistinguishable from the link being broken. */
  function jumpIfAsked() {
    if (!/section=errors/.test(location.hash || '')) return;
    var section = byId('errors');
    if (section && section.scrollIntoView) {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function init() {
    if (!byId('err-body')) return;
    if (!ROWS.length) {
      byId('err-sub').textContent =
        'No error bundle — run `make errors`.';
      return;
    }
    defaults();
    view.ready = true;
    ['from', 'to'].forEach(function (which) {
      var input = byId('err-' + which);
      if (!input) return;
      input.addEventListener('change', function (event) {
        if (!event.target.value) return;
        view[which] = event.target.value;
        render();
      });
    });
    render();
    jumpIfAsked();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
