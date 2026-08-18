/* What a release contains, read from the source it was built from.
 *
 * The rest of this page is built from test logs: what ran, how often, how it
 * went. This section answers the question that comes first — what was in the
 * release at all — which a log cannot, because a test case that was added and
 * never reached, or removed and so never seen again, leaves no trace in one.
 * "It stopped failing" and "it stopped running" look identical from the
 * outside, and only one of them is good news.
 *
 * Every factory suite name carries the commit it was built from
 * (mlt_2026.220.0-git2f1c2f23), so the suite YAML at that commit is the
 * authority on the release's contents. The diffs between consecutive releases
 * are the part nobody can currently get without opening two YAML files side by
 * side.
 */
(function () {
  'use strict';

  var DATA = window.__FACTORY_RELEASE_SOURCE__;
  var REPO_URL = 'https://github.com/etched-ai/sw';

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

  function label(suite) {
    /* mlt_validation_2026.225.0-gitb937ca2c -> "MLT 2026.225.0 validation" */
    var station = suite.indexOf('htt') !== -1 ? 'HTT' : 'MLT';
    var version = (/(\d{4}\.\d+\.\d+)/.exec(suite) || [])[1] || suite;
    var marks = [];
    if (/validation/i.test(suite)) marks.push('validation');
    if (/debug/i.test(suite)) marks.push('debug');
    return station + ' ' + version + (marks.length ? ' ' + marks.join(' ') : '');
  }

  function commitLink(release) {
    return h('a', {
      class: 'src-commit', href: REPO_URL + '/commit/' + release.commit,
      target: '_blank', rel: 'noopener noreferrer',
      title: release.subject || 'open this commit on GitHub'
    }, [document.createTextNode(release.commit)]);
  }

  /* ------------------------------------------------------------- releases */

  function renderReleases(host) {
    var wrap = h('div', { class: 'src-grid' });

    (DATA.releases || []).forEach(function (release) {
      var card = h('div', { class: 'src-card' });
      card.appendChild(h('div', { class: 'src-head' }, [
        h('strong', { class: 'src-name', text: label(release.suite) }),
        h('span', { class: 'src-count', text: release.caseCount + ' test cases' })
      ]));
      card.appendChild(h('div', { class: 'src-meta' }, [
        commitLink(release),
        h('span', { text: ' · committed ' + (release.committedAt || '—') }),
        h('span', { text: ' · ' + release.runs + ' run' +
                          (release.runs === 1 ? '' : 's') + ' on the line' })
      ]));
      if (release.subject) {
        card.appendChild(h('div', { class: 'src-subject', text: release.subject }));
      }
      if (release.error) {
        card.appendChild(h('div', { class: 'src-warn', text: release.error }));
      }

      /* The list is long and the count is the headline, so it opens on
       * request rather than pushing every other release off the screen. */
      var details = h('details', { class: 'src-cases' });
      details.appendChild(h('summary', { text: 'Test cases' }));
      var list = h('ul', {});
      (release.cases || []).forEach(function (name) {
        list.appendChild(h('li', { text: name }));
      });
      details.appendChild(list);
      card.appendChild(details);
      wrap.appendChild(card);
    });

    host.appendChild(h('h3', { class: 'src-h3', text: 'Releases that ran' }));
    host.appendChild(wrap);
  }

  /* ---------------------------------------------------------------- diffs */

  function renderDiffs(host) {
    var diffs = DATA.diffs || [];
    host.appendChild(h('h3', { class: 'src-h3', text: 'What changed between them' }));
    if (!diffs.length) {
      host.appendChild(h('p', { class: 'src-none', text:
        'No release in this window changed the test-case list. Every suite ' +
        'that ran holds the same cases as the release before it — so a change ' +
        'in results over these days is a change in the units or the ' +
        'environment, not in what was being asked of them.' }));
      return;
    }

    diffs.forEach(function (diff) {
      var card = h('div', { class: 'src-diff' });
      card.appendChild(h('div', { class: 'src-diff-head' }, [
        h('span', { class: 'src-from', text: label(diff.from) }),
        h('span', { class: 'src-arrow', text: '→' }),
        h('span', { class: 'src-to', text: label(diff.to) }),
        h('span', { class: 'src-count',
                    text: diff.unchanged + ' unchanged' })
      ]));
      [['added', 'Added', 'add'], ['dropped', 'Dropped', 'drop']]
        .forEach(function (pair) {
          var names = diff[pair[0]] || [];
          if (!names.length) return;
          var row = h('div', { class: 'src-change ' + pair[2] });
          row.appendChild(h('span', { class: 'src-change-k',
                                      text: pair[1] + ' ' + names.length }));
          names.forEach(function (name) {
            row.appendChild(h('code', { text: name }));
          });
          card.appendChild(row);
        });
      host.appendChild(card);
    });
  }

  /* ----------------------------------------------------------- provenance */

  function renderNote(host) {
    var sources = DATA.sources || {};
    var repo = DATA.repo || {};
    var readers = {};
    (DATA.releases || []).forEach(function (r) {
      if (r.reader) readers[r.reader] = true;
    });

    host.appendChild(h('p', { class: 'src-note', text:
      'Read from the suite YAML in etched-ai/sw at the commit each release ' +
      'names — MLT from ' + (sources.mlt || '?') + ', HTT from ' +
      (sources.htt || '?') + '. Wrapper cases that nest other tests ' +
      '(ServerNestedTestCase, SltModuleNestedTestCase) are structure rather ' +
      'than tests and are not counted. ' +
      (readers.scanner ? 'Some releases were read with the fallback scanner, ' +
        'which finds every case a file defines but cannot expand an aliased ' +
        'sub-suite. ' : '') +
      'Generated where a clone of that repository exists — the dashboard host ' +
      'has none, so this section is built on a laptop and committed. Clone at ' +
      (repo.head || 'unknown') + '.' }));
  }

  /* ------------------------------------------------------------------ run */

  function init() {
    var view = byId('src-view');
    if (!view) return;
    var host = byId('src-body');
    if (!DATA || !(DATA.releases || []).length) {
      /* Absent rather than broken: the box cannot build this, so the section
       * says which command produces it instead of rendering an empty shell. */
      byId('src-sub').textContent =
        'Not built for this window — run `make release-source` where a clone ' +
        'of etched-ai/sw is checked out, then commit dashboard/data/' +
        'release_source.js.';
      return;
    }

    byId('src-sub').textContent =
      (DATA.releases.length + ' releases the line ran in the last ' +
       ((DATA.window || {}).days || 7) + ' days, with the test cases each one ' +
       'holds — read from source, not from logs.');

    renderReleases(host);
    renderDiffs(host);
    renderNote(host);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
