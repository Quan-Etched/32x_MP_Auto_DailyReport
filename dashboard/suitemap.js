/* Which suite YAML each station runs.
 *
 * The section above this one profiles releases, and it can only do that for
 * the two stations somebody had already written a file path down for. This one
 * derives the whole map: for every station in the registry, the suite config in
 * etched-ai/sw that produced its runs, the fact that ties the two together, and
 * how the cases that file defines compare to the case names the logs carry.
 *
 * The evidence tier is rendered as prominently as the mapping, because it is
 * half the answer. "host/system_test/BUILD deploys it under this name" and "the
 * filename looked right" are both mappings and they are not worth the same, and
 * a table that drew them identically would invite someone to act on the weaker
 * one as though it were the stronger.
 *
 * Two absences are shown as findings rather than swept up. A suite name the
 * line ran that nothing in the tree accounts for is either a station-local edit
 * nobody committed or a rename we have not followed. A suite config BUILD
 * packages for a line that no run names is either dead weight or a stage nobody
 * is measuring. Both are questions for a person; neither is an error here.
 */
(function () {
  'use strict';

  var DATA = (window.__FACTORY_RELEASE_SOURCE__ || {}).suiteMap || {};
  var REPO_URL = 'https://github.com/etched-ai/sw';

  /* The two readings are never added together — one run appears once from its
   * controller and again from EOS, under two different suite names. */
  var SOURCE_LABEL = {
    eos: 'EOS', pega2: 'pega2', pega3: 'pega3', pega4: 'pega4', pega5: 'pega5'
  };

  /* Buckets that appear in the list beside the stations without being one.
   * Neither gets a coverage bar: their cases come from unrelated files. */
  var NOT_A_STATION = { engineering: true, unclassified: true };

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
  /* The case lists are empty on a station whose YAML and logs agree, and an
   * empty one returns nothing rather than an empty <details> nobody can open. */
  function add(parent, node) { if (node) parent.appendChild(node); return node; }
  function plural(count, word) {
    return count + ' ' + word + (count === 1 ? '' : 's');
  }

  function tierNote(key) {
    var found = (DATA.tiers || []).filter(function (tier) {
      return tier.key === key;
    })[0];
    return found || { key: key, label: key, note: '' };
  }

  function fileLink(path) {
    /* Linked at the commit the map was read at, not at master: master will
     * have moved by the time somebody clicks, and a line count or a case list
     * quoted here has to resolve to the file it was read from. */
    var at = (DATA.tree || {}).commit || 'master';
    return h('a', {
      class: 'map-path', href: REPO_URL + '/blob/' + at + '/' + path,
      target: '_blank', rel: 'noopener noreferrer',
      title: 'open ' + path + ' at ' + at + ' on GitHub'
    }, [document.createTextNode(path.replace(DATA.suiteRoot + '/', ''))]);
  }

  function runsChip(runs) {
    var sources = Object.keys(runs || {}).sort(function (a, b) {
      return runs[b] - runs[a];
    });
    if (!sources.length) return null;
    return h('span', {
      class: 'map-runs',
      /* Spelt out on the chip, because a reader who adds the two numbers
       * himself gets a total that counts every run twice. */
      title: 'Two independent readings of the same runs, not a total: a ' +
             'controller names the suite it ran, EOS names the test class.',
      text: sources.map(function (key) {
        return runs[key] + ' ' + (SOURCE_LABEL[key] || key);
      }).join(' · ')
    });
  }

  /* ------------------------------------------------------------- coverage */

  function coverageBar(cover) {
    if (!cover.comparable) {
      return h('p', { class: 'map-nocover', text:
        'No case names to compare against. EOS is the only system whose runs ' +
        'carry test-class names and it cannot read this level, so the ' +
        cover.defined + ' cases the YAML defines are neither confirmed nor ' +
        'contradicted here.' });
    }
    var wrap = h('div', { class: 'map-cover' });
    var seen = cover.exercised;
    var dark = cover.dark.length;
    var extra = cover.extra.length;
    var total = seen + dark + extra || 1;

    var bar = h('div', { class: 'map-bar', role: 'img',
      'aria-label': seen + ' of ' + cover.defined + ' defined cases seen in a ' +
        'log, ' + dark + ' defined and unseen, ' + extra + ' seen and not defined'
    });
    [['seen', seen], ['dark', dark], ['extra', extra]].forEach(function (part) {
      if (!part[1]) return;
      bar.appendChild(h('span', {
        class: 'map-seg ' + part[0],
        style: 'flex: ' + (part[1] / total)
      }));
    });
    wrap.appendChild(bar);
    wrap.appendChild(h('div', { class: 'map-cover-keys' }, [
      h('span', { class: 'map-key seen',
                  text: seen + ' defined and run' }),
      dark ? h('span', { class: 'map-key dark',
                         text: dark + ' defined, never run' }) : null,
      extra ? h('span', { class: 'map-key extra',
                          text: extra + ' run, not defined' }) : null
    ]));
    return wrap;
  }

  function caseList(names, kind, heading) {
    if (!names.length) return null;
    var details = h('details', { class: 'map-cases ' + kind });
    details.appendChild(h('summary', { text: heading + ' (' + names.length + ')' }));
    var list = h('ul', {});
    names.forEach(function (name) { list.appendChild(h('li', { text: name })); });
    details.appendChild(list);
    return details;
  }

  /* --------------------------------------------------------------- a suite */

  function suiteRow(suite) {
    var row = h('div', { class: 'map-suite' });
    var tier = tierNote(suite.tier);

    row.appendChild(h('div', { class: 'map-suite-head' }, [
      h('span', { class: 'tier t-' + suite.tier, text: tier.label,
                  title: tier.note }),
      fileLink(suite.path),
      h('span', { class: 'src-count',
                  text: plural(suite.caseCount, 'case') }),
      runsChip(suite.runs)
    ]));
    row.appendChild(h('p', { class: 'map-evidence', text: suite.evidence }));

    var facts = [];
    if (suite.deployedAs) {
      facts.push('deployed as ' + suite.deployedAs);
    }
    if (suite.runner) {
      facts.push('packaged by ' + suite.runner +
                 (suite.line ? ' (' + suite.line + ' line)' : ''));
    }
    if (suite.suiteName) facts.push('suite_name: ' + suite.suiteName);
    if (suite.runName) facts.push('run_name: ' + suite.runName);
    if (facts.length) {
      row.appendChild(h('p', { class: 'map-facts', text: facts.join(' · ') }));
    }

    /* A second file matching the same name is worth showing rather than
     * quietly losing: rack/L11/L10_SFT.yaml carries L10 SFT's run_name too,
     * and which of the two the line deploys is decided elsewhere. */
    if ((suite.alsoMatches || []).length) {
      row.appendChild(h('p', { class: 'map-warn', text:
        'The same name also matches ' + suite.alsoMatches.join(', ') +
        '. This file won on stronger evidence where the tiers differ, and ' +
        'otherwise on being the suite the other one sits beneath — so the ' +
        'name alone did not decide it.' }));
    }
    if (suite.error) {
      row.appendChild(h('p', { class: 'map-warn', text: suite.error }));
    }

    var seen = h('details', { class: 'map-cases observed' });
    seen.appendChild(h('summary', {
      text: 'Suite names the logs carry (' + suite.observed.length + ')' }));
    var table = h('table', { class: 'map-obs' });
    suite.observed.forEach(function (entry) {
      table.appendChild(h('tr', {}, [
        h('td', { class: 'mono', text: entry.suite }),
        h('td', { class: 'num', text: String(entry.runs) }),
        h('td', { text: SOURCE_LABEL[entry.source] || entry.source }),
        h('td', { class: 'fixtures',
                  text: (entry.stationIds || []).join(', ') })
      ]));
    });
    seen.appendChild(table);
    row.appendChild(seen);
    return row;
  }

  /* ------------------------------------------------------------- a station */

  function stationCard(station) {
    var loose = !!NOT_A_STATION[station.station];
    var card = h('div', { class: 'map-card' + (loose ? ' engineering' : '') });

    card.appendChild(h('div', { class: 'map-card-head' }, [
      h('strong', { class: 'map-station', text: station.label }),
      station.controller
        ? h('span', { class: 'map-ctl', text: station.controller,
                      title: 'the controller that drives this station' })
        : null,
      h('span', { class: 'spacer' }),
      runsChip(station.runs)
    ]));

    if (loose) {
      card.appendChild(h('p', { class: 'map-note', text:
        station.station === 'engineering'
          ? 'Not a station. Debug builds, dry runs, validation cuts and suites ' +
            'named after whoever ran them — kept because a _krish FAT run is ' +
            'still evidence about which file FAT runs from, and pooled here so ' +
            'they stay out of every station\'s numbers.'
          : 'Not a station. Runs that matched no entry in the registry — kept ' +
            'visible because a suite nobody has placed is a question for ' +
            'somebody, not noise to drop.' }));
    }

    station.suites.forEach(function (suite) {
      card.appendChild(suiteRow(suite));
    });

    /* Coverage is a claim about a station, so the pooled engineering bucket
     * does not get one: its cases come from unrelated files. */
    if (!loose) {
      add(card, coverageBar(station.coverage));
      add(card, caseList(station.coverage.dark, 'dark',
        'Defined in the YAML, and no log in the window shows it'));
      add(card, caseList(station.coverage.extra, 'extra',
        'Seen in a log, and this YAML does not define it at HEAD'));
    }
    return card;
  }

  /* ----------------------------------------------------------- the absences */

  function unmatched(host) {
    var rows = DATA.unmatched || [];
    if (!rows.length) return;
    host.appendChild(h('h3', { class: 'src-h3', text:
      'Ran, and nothing in the tree accounts for it' }));
    host.appendChild(h('p', { class: 'src-note', text:
      'Every one of these produced runs on the line, and no suite config on ' +
      ((DATA.tree || {}).ref || 'the ref read') + ' carries the name — by any ' +
      'of the ' + (DATA.tiers || []).length + ' routes above. Each is a ' +
      'station-local edit nobody committed, a rename this mapping has not ' +
      'followed, or a suite the tree has since deleted while its runs stayed ' +
      'in the window. In all three the definition of what those runs measured ' +
      'is not in the repository as it stands.' }));
    var table = h('table', { class: 'map-obs wide' });
    table.appendChild(h('tr', {}, [
      h('th', { text: 'Station' }), h('th', { text: 'Suite name' }),
      h('th', { class: 'num', text: 'Runs' }), h('th', { text: 'From' })
    ]));
    rows.forEach(function (row) {
      table.appendChild(h('tr', {}, [
        h('td', { text: row.station }),
        h('td', { class: 'mono', text: row.suite }),
        h('td', { class: 'num', text: String(row.runs) }),
        h('td', { text: SOURCE_LABEL[row.source] || row.source })
      ]));
    });
    host.appendChild(table);
  }

  function unrun(host) {
    var rows = (DATA.unrun || []).filter(function (row) { return row.packaged; });
    var unpackaged = (DATA.unrun || []).length - rows.length;
    if (!rows.length) return;

    var details = h('details', { class: 'map-cases unrun' });
    details.appendChild(h('summary', {
      text: 'Packaged for a line, and no run in the window names it (' +
            rows.length + ')' }));
    details.appendChild(h('p', { class: 'src-note', text:
      'BUILD assigns each of these a runner package, so they are wired up ' +
      'rather than abandoned — but nothing ran them in this window. A suite ' +
      'that is built and never run is either dead weight in the tree or a ' +
      'stage nobody is measuring.' + (unpackaged
        ? ' A further ' + unpackaged + ' suite configs are in the tree with no ' +
          'runner package at all.' : '') }));
    var table = h('table', { class: 'map-obs wide' });
    table.appendChild(h('tr', {}, [
      h('th', { text: 'Suite config' }), h('th', { class: 'num', text: 'Cases' }),
      h('th', { text: 'Package' }), h('th', { text: 'Line' })
    ]));
    rows.forEach(function (row) {
      table.appendChild(h('tr', {}, [
        h('td', {}, [fileLink(row.path)]),
        h('td', { class: 'num', text: String(row.caseCount) }),
        h('td', { class: 'mono', text: row.runner || '' }),
        h('td', { text: row.line || '' })
      ]));
    });
    details.appendChild(table);
    host.appendChild(details);
  }

  function legend(host) {
    var wrap = h('div', { class: 'map-legend' });
    (DATA.tiers || []).forEach(function (tier) {
      wrap.appendChild(h('span', { class: 'tier t-' + tier.key,
                                   text: tier.label, title: tier.note }));
    });
    host.appendChild(wrap);
    host.appendChild(h('p', { class: 'src-note', text:
      (DATA.tiers || []).map(function (tier) {
        return tier.label + ' — ' + tier.note;
      }).join(' ') }));
  }

  function note(host) {
    var tree = DATA.tree || {};
    var counts = DATA.counts || {};
    var pins = (DATA.pins || []).map(function (pin) { return pin.source; });

    host.appendChild(h('p', { class: 'src-note', text:
      'Read from etched-ai/sw at ' + (tree.ref || '?') + ' — ' +
      (tree.commit || '?') +
      (tree.committedAt ? ', ' + tree.committedAt : '') +
      (tree.subject ? ', "' + tree.subject + '"' : '') + '. ' +
      /* Deliberately not the working tree. The clone this was built from sat
       * two months behind master on a feature branch, and a station map from
       * that describes one engineer's checkout rather than the line. */
      'The shared ref, not the builder\'s checkout: a laptop sits on whatever ' +
      'branch its owner last worked on' +
      (tree.aheadOfWorkingTree
        ? ' — this one on ' + tree.workingBranch + ' at ' + tree.workingHead +
          ', which is not what this section describes'
        : '') + '. ' +
      counts.deployed + ' suites are deployed by host/system_test/BUILD and ' +
      counts.pinned + ' are pinned by a release script (' + pins.join(', ') +
      '). Every one of those facts is read out of the tree at build time, so a ' +
      'rename in sw surfaces as a suite that stopped matching rather than as a ' +
      'mapping that quietly went stale.' }));

    /* A pin that stopped resolving is the mechanism working, and it is worth
     * naming the constant that moved rather than only showing the drop in
     * confidence it caused. */
    (DATA.pinsGone || []).forEach(function (gone) {
      host.appendChild(h('p', { class: 'map-warn', text:
        gone.source + ' no longer defines ' + gone.constant + ' (' + gone.why +
        '), so that pin is gone and any station relying on it has fallen back ' +
        'to weaker evidence.' }));
    });

    host.appendChild(h('p', { class: 'src-note', text:
      'The tree is read at one ref while the logs span ' + (DATA.days || 30) +
      ' days of releases, so a case in one set and not the other is a ' +
      'question, not a defect: it may be new, unreachable, dropped, or simply ' +
      'outside the window. The per-release section above is where that ' +
      'comparison is exact, because there each file is read at its own ' +
      'release\'s commit.' +
      ((DATA.problems || []).length
        ? ' Incomplete: ' + DATA.problems.join('; ') + '.' : '') }));
  }

  /* ------------------------------------------------------------------ run */

  function init() {
    var view = byId('map-view');
    if (!view) return;
    var host = byId('map-body');

    if (!DATA || !(DATA.stations || []).length) {
      byId('map-sub').textContent = DATA && DATA.error
        ? 'Not built: ' + DATA.error
        : 'Not built for this window — run `make suite-map` where a clone of ' +
          'etched-ai/sw is checked out, then commit release_profile/' +
          'release_source.js.';
      return;
    }

    var counts = DATA.counts || {};
    /* Counted, not assumed: the engineering bucket is one non-station in the
     * list and an unclassified one can join it, and "across 12 stations" when
     * two of them are not stations is the kind of small wrongness nobody
     * checks. */
    var real = DATA.stations.filter(function (station) {
      return !NOT_A_STATION[station.station];
    }).length;
    byId('map-sub').textContent =
      counts.attributed + ' of ' + counts.files + ' suite configs in ' +
      DATA.suiteRoot + ' are accounted for by a run on the line, across ' +
      plural(real, 'station') + '.';

    legend(host);
    DATA.stations.forEach(function (station) {
      host.appendChild(stationCard(station));
    });
    unmatched(host);
    unrun(host);
    note(host);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
