/* Download a table as CSV — the table as it is on screen.
 *
 * WHY IT READS THE DOM
 * Every table this is attached to is filtered, sorted or count-mode-switched by
 * the reader before they want the file. Rebuilding the CSV from the underlying
 * bundle would hand them the unfiltered thousand rows they had just narrowed to
 * forty, and they would not notice until the numbers in the file disagreed with
 * the screenshot beside it. Reading the rendered rows makes "what I am looking
 * at" and "what I downloaded" the same thing by construction.
 *
 * The cost is that a cell exports as the text it shows, decoration included:
 * "F1 P2" traces, "×3" repeat markers, a ▲ on a sorted heading. That is the
 * right trade for a tracker export — the file is a copy of the table, and a
 * copy that quietly differed from it would be worse.
 *
 * LINKS
 * The run links are the most useful thing on these tables and textContent
 * throws them away — the daily tracker's FI Test Link cell shows "73269536"
 * and hides the pega3 URL behind it. So any hrefs in a row are collected into
 * one trailing column rather than being lost, and the column only appears when
 * some row actually has one.
 */
(function () {
  'use strict';

  /* One field, quoted only where it has to be. Excel is the reader here, so
   * CRLF and a BOM below; both are what it expects and neither is visible. */
  function field(text) {
    var value = String(text === null || text === undefined ? '' : text);
    return /[",\r\n]/.test(value) ? '"' + value.replace(/"/g, '""') + '"' : value;
  }

  function toCsv(rows) {
    return rows.map(function (row) {
      return row.map(field).join(',');
    }).join('\r\n');
  }

  /* A cell's text, flattened onto one line.
   *
   * The failure columns hold several case names separated by newlines. Kept as
   * newlines they are legal CSV inside a quoted field and a nuisance in a
   * spreadsheet — one row becomes six and every other column goes blank. */
  function cellText(cell) {
    return (cell.textContent || '')
      .replace(/\s*\n\s*/g, '; ')
      .replace(/[ \t]+/g, ' ')
      .trim();
  }

  function hrefs(row) {
    var out = [];
    var links = row.querySelectorAll('a[href]');
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute('href');
      /* In-page anchors and javascript: are chrome, not data. */
      if (!href || href.charAt(0) === '#') continue;
      if (out.indexOf(href) === -1) out.push(href);
    }
    return out;
  }

  /* Only what is actually on screen. A row the page has hidden is a row the
   * reader has filtered away. */
  function visible(rows) {
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].hasAttribute('hidden')) continue;
      out.push(rows[i]);
    }
    return out;
  }

  function fromTable(table) {
    if (!table) return [];
    var head = table.tHead;
    /* The last header row: a two-tier heading puts the column names on the
     * lower one, and the upper one spans groups. */
    var headRows = head ? visible(head.rows) : [];
    var headers = headRows.length
      ? Array.prototype.map.call(headRows[headRows.length - 1].cells, cellText)
      : [];

    var bodyRows = [];
    for (var b = 0; b < table.tBodies.length; b++) {
      bodyRows = bodyRows.concat(visible(table.tBodies[b].rows));
    }

    var withLinks = bodyRows.some(function (row) { return hrefs(row).length; });
    var out = [headers.concat(withLinks ? ['Links'] : [])];
    bodyRows.forEach(function (row) {
      var cells = Array.prototype.map.call(row.cells, cellText);
      /* A row that spans the table — a group heading or an empty-state line —
       * is not a record. */
      if (row.cells.length === 1 && headers.length > 1) return;
      while (cells.length < headers.length) cells.push('');
      if (withLinks) cells.push(hrefs(row).join(' '));
      out.push(cells);
    });
    return out;
  }

  function download(name, text) {
    /* A BOM: without it Excel reads UTF-8 as its local codepage and the serials
     * survive but every ° and — does not. */
    var blob = new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', name);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    /* Freed on the next tick rather than immediately: revoking before the
     * browser has started the download cancels it in Safari. */
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  /* Put a button beside a table.
   *
   * `name` is a function so the filename can carry the day or the week that is
   * on screen at the moment of the click, not the one that was on screen when
   * the button was made.
   */
  function attach(host, options) {
    if (!host) return null;
    var button = document.createElement('button');
    button.setAttribute('type', 'button');
    button.setAttribute('class', 'csv-btn');
    button.textContent = options.label || 'Download CSV';
    button.setAttribute('title', options.title
      || 'the rows on screen, as filtered, as a CSV for Excel');
    button.addEventListener('click', function () {
      var table = typeof options.table === 'function'
        ? options.table() : options.table;
      var rows = fromTable(table);
      if (rows.length < 2) {
        /* Nothing to hand over. Said on the button rather than downloading an
         * empty file that looks like a data loss. */
        var was = button.textContent;
        button.textContent = 'Nothing to export';
        setTimeout(function () { button.textContent = was; }, 1600);
        return;
      }
      download(typeof options.name === 'function' ? options.name() : options.name,
               toCsv(rows));
    });
    host.appendChild(button);
    return button;
  }

  window.FactoryCsv = { field: field, toCsv: toCsv, fromTable: fromTable,
                        download: download, attach: attach };
})();
