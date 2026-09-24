# factory_data_analysis — no dependencies beyond Python 3.9+ stdlib.

ifeq ($(OS),Windows_NT)
PY      ?= python
else
PY      ?= python3
endif
ANNOTATE_PORT ?= 8766
export PYTHONPATH := src
PORT    ?= 8787
LEVEL   ?= l10
DAYS    ?= 2
WINDOW  ?= 30
STATION ?= l10_sft

# shopfloor (SFIS traceability): SN is the top-level serial to mirror/render.
SN         ?=
# Every product level, because a partial sweep is indistinguishable from a
# missing unit once it reaches the page: a 4U that was never mirrored reads as
# "not in the traceability snapshot", which is what happened when this defaulted
# to 6U,L11 and 158 of 191 units were silently absent.
SFIS_LEVEL ?= 6U,4U,2U,L11
SFIS_DAYS  ?= 120
DAYS_RECONCILE ?= 7

.PHONY: sfis-reconcile sfis-doctor sfis-mirror sfis-level sfis-unit sfis-units sfis-gaps sfis-snapshots \
	sfis-dashboard review review-data \
	help trust demo collect build report serve test inspect levels refresh status \
        schedule-install schedule-uninstall schedule-status publish refresh-publish items \
        deploy deploy-status pega-recache pega-push \
        schedule-pega-push-install schedule-pega-push-uninstall \
        schedule-pega-push-status \
        dailyexcel daily-report file-bugs requests pega-stations release-source suite-map reconcile \
        errors annotate error-catalogue retest-slide \
        outcomes doe-deck chips fpy \
        weekly \
        weekly-deck ramp-deck archive \
        weekly-snapshot schedule-weekly-install schedule-weekly-uninstall \
        schedule-weekly-status schedule-weekly-install-macos \
        schedule-weekly-uninstall-macos schedule-weekly-status-macos \
        schedule-weekly-install-systemd schedule-weekly-uninstall-systemd \
        schedule-weekly-status-systemd \
        schedule-install-macos schedule-uninstall-macos schedule-status-macos \
        schedule-install-systemd schedule-uninstall-systemd schedule-status-systemd \
        update clean distclean

help:
	@echo "make trust              install Etched's internal CA bundle (fixes TLS errors)"
	@echo "make update             FULL UPDATE: collect + items + rebuild + publish"
	@echo "make refresh            one scheduler tick: collect + rebuild (WINDOW=30 days)"
	@echo "make status             last fetch vs last update, per station"
	@echo "make publish            publish dashboard/ (FACTORY_WEB_ROOT, else gh-pages)"
	@echo "make deploy             THE way code reaches production: rsync + rebuild there"
	@echo "make deploy-status      is the box running this checkout, or an older one?"
	@echo "make pega-recache FROM=2026-08-01  drop cached day-listings so they refetch"
	@echo "make pega-push          warm the controller cache here, push it to the box"
	@echo "make schedule-pega-push-install  do that hourly at :50 (laptop only)"
	@echo "make items [STATION=..]  flatten test cases to numeric test items"
	@echo "make dailyexcel         compile daily/*.xlsx (MLT/HTT tracker) into the dashboard"
	@echo "make daily-report [DAY=]  standup markdown from that day's tracker tab"
	@echo "make requests           re-check what we need from other systems"
	@echo "make suite-map [CASES=1] which suite YAML each station runs, from the sw tree"
	@echo "make reconcile [DAY=..] OCP vs the controllers run by run, + a CSV of the gaps"
	@echo "make errors           failing test cases joined to the error-code sheet"
	@echo "make annotate         the service the admin error table posts its edits to"
	@echo "make schedule-install   install the hourly job (launchd / systemd timer)"
	@echo "make schedule-weekly-install  install the Sunday 21:00 snapshot job"
	@echo "make weekly-snapshot    run that snapshot now: collect, deck, archive, publish"
	@echo "make demo               synthetic data + dashboard bundle (no API key needed)"
	@echo "make collect [DAYS=2]   fetch real runs from the EOS API into data/processed/"
	@echo "make build              compile data/processed/runs.json into the dashboard bundle"
	@echo "make report             print the hourly metrics as text"
	@echo "make serve [PORT=8787]  serve the dashboard at http://127.0.0.1:\$$(PORT)/"
	@echo "make test               run the unit tests"
	@echo "make inspect            show live API field names and how parse.py maps them"
	@echo "make clean              remove generated data and the dashboard bundle"
	@echo ""
	@echo "  shopfloor traceability (src/shopfloor, docs/sfis/README.md)"
	@echo "make sfis-doctor        can we reach pega-sfis and EOS, with what credential"
	@echo "make sfis-mirror SN=..  snapshot one root serial (VERDICTS=1 for EOS pass/fail)"
	@echo "make sfis-level          snapshot every unit at every level (the default)"
	@echo "make sfis-unit SN=..    render out/<SN>.yaml from the latest snapshot [offline]"
	@echo "make sfis-units         render every serial in the latest snapshot [offline]"
	@echo "make sfis-dashboard     compile the snapshot into the customize.html tree"
	@echo "make sfis-reconcile     EOS runs vs the shopfloor, per level, last 7 days"
	@echo "make sfis-gaps [SN=..]  traceability escapes and unlinked test DUTs"
	@echo "make sfis-snapshots     list the snapshots on disk"

trust:
	$(PY) -m factory.cli trust

demo:
	$(PY) -m factory.cli demo --days $(DAYS) --level $(LEVEL)

collect:
	$(PY) -m factory.cli collect --level $(LEVEL) --days $(DAYS)

build:
	$(PY) -m factory.cli build

report:
	$(PY) -m factory.cli report

serve:
	$(PY) -m factory.cli serve --port $(PORT)

# The page colleagues open for review. Bound on every interface so the
# hostname works; Ctrl-C stops it. See docs/review-server.md.
review:
	$(PY) -m factory.cli serve --host 0.0.0.0 --port $(PORT)

# Copy today's snapshot to the review host. Rebuild locally first
# (`make dailyexcel`); that host cannot reach pega.
REVIEW_HOST ?= quan@production-failure-analysis.usw2.i.etched.com
REVIEW_DIR  ?= factory_data_analysis
review-data:
	scp dashboard/data/dailyexcel.js dashboard/data/dailyfa.js \
	    $(REVIEW_HOST):$(REVIEW_DIR)/dashboard/data/

test:
	$(PY) -m unittest discover -s tests -v

inspect:
	$(PY) -m factory.cli inspect --level $(LEVEL) --days $(DAYS)

levels:
	$(PY) -m factory.cli levels

refresh:
	$(PY) -m factory.cli refresh --days $(WINDOW)

# The full update, end to end. Identical to what the hourly agent runs and to
# what the Update button on the served dashboard triggers — one script, so the
# three can never drift apart.
update:
	@FACTORY_REFRESH_DAYS=$(WINDOW) bash tools/hourly_refresh.sh

# Push dashboard/ to the gh-pages branch that GitHub Pages serves (private).
publish:
	@bash tools/publish.sh

# Collect and publish in one step — what the hourly agent does.
refresh-publish: refresh publish

# Put this checkout on the dashboard host and rebuild there.
#
# `make publish` publishes the BOX'S OWN tree; nothing in the hourly job updates
# the code. So a fix committed here is not on the site until this runs — which
# is how the box came to serve 75579de for eight commits while three separate
# fixes were reported as done. NO_UPDATE=1 syncs without rebuilding.
deploy:
	@bash tools/deploy.sh

# Is the box running this checkout? Non-zero and loud when it is not.
deploy-status:
	@bash tools/deploy.sh --status

# Throw away cached controller day-listings so the next build fetches them
# again. For after a spell where the controllers were timing out and every
# build quietly served the same stale copy. FROM= is required, TO= defaults to
# today, DRY_RUN=1 to look first.
pega-recache:
	$(PY) tools/pega_recache.py --from $(FROM) $(if $(TO),--to $(TO),) \
	    $(if $(DRY_RUN),--dry-run,)

# Warm the controller cache here and hand it to the box, which cannot read
# pega3/4/5 itself — 46 bytes a second over a DERP relay, against 0.09s from a
# laptop. Runs on a machine with the VPN; the box picks the cache up on its
# next hourly build. A workaround for a network fault, not a design: see
# "The box cannot reach the controllers" in docs/deploy.md.
pega-push:
	@bash tools/pega_push.sh

LAUNCHD_PEGA_PUSH := com.etched.factory-pega-push
LAUNCHD_PEGA_PUSH_DEST := $(HOME)/Library/LaunchAgents/$(LAUNCHD_PEGA_PUSH).plist

# macOS only, deliberately: the thing being worked around is that the Linux box
# has no route, so scheduling this there would push a cache to itself.
schedule-pega-push-install:
	@if [ "$(UNAME_S)" != "Darwin" ]; then \
	    echo "This runs on a machine that can reach the controllers — a Mac on"; \
	    echo "the VPN. The dashboard host is the one being pushed TO."; \
	    exit 1; \
	fi
	@mkdir -p $(HOME)/Library/LaunchAgents data/logs
	@sed 's|__REPO__|$(REPO_DIR)|g' deploy/launchd/$(LAUNCHD_PEGA_PUSH).plist \
	    > $(LAUNCHD_PEGA_PUSH_DEST)
	@launchctl unload $(LAUNCHD_PEGA_PUSH_DEST) 2>/dev/null || true
	@launchctl load $(LAUNCHD_PEGA_PUSH_DEST)
	@echo "Installed $(LAUNCHD_PEGA_PUSH) — warms and pushes at :50 every hour."
	@echo "The box rebuilds from it at :05.  Logs: data/logs/pega_push.log"
	@echo "A sleeping laptop pushes nothing; the box then serves the last cache"
	@echo "it got. Retire this once the box has a direct path to the pegas."

schedule-pega-push-uninstall:
	@launchctl unload $(LAUNCHD_PEGA_PUSH_DEST) 2>/dev/null || true
	@rm -f $(LAUNCHD_PEGA_PUSH_DEST)
	@echo "Removed $(LAUNCHD_PEGA_PUSH)."

schedule-pega-push-status:
	@launchctl list | grep $(LAUNCHD_PEGA_PUSH) || echo "not loaded"
	@echo "---"
	@tail -12 data/logs/pega_push.log 2>/dev/null || echo "no log yet"

status:
	$(PY) -m factory.cli status

# Flatten test cases to test items (numeric layer) into data/processed/items.sqlite
items:
	$(PY) -m factory.cli items --station $(STATION)

# Compile the line's daily MLT/HTT tracker tabs (daily/*.xlsx) into the
# dashboard. Also runs as part of `make build`; this is for iterating on a new
# export without a full rebuild.
dailyexcel:
	$(PY) -m factory.cli dailyexcel

# Morning standup note from a tracker tab. Fetches pega3 first so the note
# is not stuck on last week's cache. DAY=2026-09-10 picks a day; OUT=C:\note.md
# writes somewhere else; COHORT=SohuLaneRepairTestCase makes it a retest note.
# OFFLINE=1 skips the fetch.
DAY        ?=
OUT        ?=
COHORT     ?=
PRODUCT    ?=
MASTER_JIRA?=
OFFLINE    ?=
daily-report:
	$(PY) -m factory.cli daily-report \
	    $(if $(DAY),--day $(DAY),) \
	    $(if $(OUT),--out $(OUT),) \
	    $(if $(COHORT),--cohort-case $(COHORT),) \
	    $(if $(PRODUCT),--product "$(PRODUCT)",) \
	    $(if $(MASTER_JIRA),--master-jira $(MASTER_JIRA),) \
	    $(if $(OFFLINE),--offline,)

# One Jira bug per failing test case, every serial in the body, parented
# under EPIC (default ETCH-44407). Prints the bug reports. CREATE=1 posts
# them; that needs JIRA_EMAIL and JIRA_API_TOKEN. CASES is optional and
# repeatable as a make list. OFFLINE=1 skips the pega3 fetch.
EPIC  ?= ETCH-44407
SINCE ?=
UNTIL ?=
CREATE ?=
CASES ?=
file-bugs:
	$(PY) -m factory.cli file-bugs \
	    --epic $(EPIC) \
	    $(if $(SINCE),--since $(SINCE),) \
	    $(if $(UNTIL),--until $(UNTIL),) \
	    $(if $(OUT),--out $(OUT),) \
	    $(if $(CREATE),--create,) \
	    $(if $(OFFLINE),--offline,) \
	    $(foreach c,$(CASES),--case $(c))

# The L10 daily tracker (FAT, SFT, RIN, 2U) from pega4. Also part of `make build`.

# Station yield straight from the ESVM controllers, for comparison with the
# OCP/EOS-sourced page. Also part of `make build`.
pega-stations:
	$(PY) -m factory.cli pega-stations

# Profile each release's test cases from the sw source tree. Needs a clone of
# etched-ai/sw (FACTORY_SW_REPO, default ~/project/sw), so it runs on a laptop
# and the bundle it writes is committed for the box to publish.
release-source:
	$(PY) -m factory.cli release-source

# Wafer sort and final test, per die. Not part of `make build`: the only source
# reachable today is a snapshot in somebody's working directory, and the figures
# it gives are diagnostics rather than the published yield — see the module
# docstring. SPLM_TOKEN=... makes SPLM the source and this a real feed.
chips:
	$(PY) -m factory.cli chips

# Failing test cases joined to the error-code catalogue, for section 4 of the
# customize page. Also part of `make build`.
errors:
	$(PY) -m factory.cli errors

# The service the customize page's admin mode posts to: it writes
# errors/annotations.json and commits it. Runs where somebody can commit, which
# is a laptop — the box has no writable backend and no sudo to add one. Ctrl-C
# to stop.
annotate:
	$(PY) tools/annotate_server.py $(ANNOTATE_PORT)

# Re-read the line's error-code sheet into errors/catalogue.json. By hand, after
# the sheet changes: the committed copy is what every build reads, so no build
# depends on Google being up. SHEET=diff/error-codes.csv
error-catalogue:
	$(PY) tools/refresh_error_catalogue.py $(SHEET)

# Which suite YAML each station runs, derived from the sw tree: the file, the
# fact that ties it to the station's runs, and how its cases compare to the
# case names the logs carry. Printed here; `make release-source` is what puts
# it on the page, since the two share one committed bundle.
suite-map:
	$(PY) -m factory.cli suite-map $(if $(CASES),--cases,)


# OCP against the controllers, run by run, for one day, plus a CSV of the units
# each source is missing. Reads the two published run bundles, so `make build`
# first if they are stale. DAY=2026-08-20 to pick a day; default is the most
# recent day either source has.
reconcile:
	$(PY) -m factory.cli reconcile $(if $(DAY),--day $(DAY),)


# End-to-end first-pass yield, one row per test step — the weekly summary.
fpy:
	$(PY) -m factory.cli fpy

# Pack the week out: the bundle as it stood, plus a readable summary, under a
# dated folder in weekly/. The dashboard always shows the current seven days,
# so without this the comparison a month from now has nothing to compare to.
weekly:
	$(PY) -m factory.cli weekly

# The weekly deck: the flow with the numbers in it, plus the step table.
# Reads the bundle `make weekly` wrote, so run that first.
weekly-deck: weekly
	$(PY) tools/build_weekly_deck.py

# Pass / Retest Pass / Bonepile per unit, plus the MLT -> HTT flow, for
# doe.html. Also part of `make build`.
outcomes:
	$(PY) -m factory.cli outcomes

# The same four outcomes as slides, with the flow drawn as a Sankey.
# WEEKS="2026-W33 2026-W34" to pick weeks; default is every week in the bundle.
doe-deck: outcomes
	$(PY) tools/build_doe_deck.py $(WEEKS)

# Append the retest / bonepile-recovery slide to a hand-edited weekly deck.
# DECK= the deck to append to (default: the newest weekly-*.pptx), WEEK= which
# week. Writes <deck>_retest.pptx and never touches its input, because the deck
# it reads has hand-drawn callouts on it.
retest-slide: weekly
	$(PY) tools/build_retest_slide.py $(DECK) $(WEEK)

# The two slides the all-hands page hands out, into dashboard/data/ so
# `make publish` ships them. Not part of `make build`: the hourly pipeline is
# stdlib-only and this needs python-pptx. The Saturday snapshot runs it, and
# this target is for rebuilding mid-week by hand.
ramp-deck: weekly
	$(PY) tools/build_ramp_deck.py

# The whole weekly job by hand — the same script the Saturday timer runs.
weekly-snapshot:
	@bash tools/weekly_snapshot.sh

# Pack a week out for later comparison: the bundle as it stood, a readable
# summary and the deck, under weekly/<ISO week>/.
archive: weekly-deck
	$(PY) -m factory.cli archive

# Re-check what we need from other systems (routes, certs, IAM, API fields) and
# rebuild that page. Also runs as part of `make build`.
requests:
	$(PY) -m factory.cli requests

# ---------------------------------------------------------------- scheduler
# Hourly, at :05, on whichever machine this is: launchd on a laptop, a systemd
# *user* timer on the Linux dashboard host. The public target names stay the
# same so the README, STATUS and muscle memory do not fork per platform.
REPO_DIR      := $(shell pwd)
UNAME_S       := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
SCHED := macos
else
SCHED := systemd
endif

schedule-install:   schedule-install-$(SCHED)
schedule-uninstall: schedule-uninstall-$(SCHED)
schedule-status:    schedule-status-$(SCHED)

# The weekly snapshot is a second, independent job. The hourly one already
# rebuilds every page including the weekly ones; this is the deck and the
# archived copy of the week, which must happen once at a known moment.
#
# WEEKLY_AT is a systemd calendar expression carrying its own timezone: the box
# runs UTC and "Saturday 18:00" was asked for in Pacific, which is a different
# day there and moves an hour at each DST boundary.
# Sunday night, so the week captured has actually finished. Note what that
# means in UTC: 21:00 Pacific on Sunday is 04:00 Monday there, the ISO week has
# already rolled over, and "the current week" is a fresh empty one — which is
# why `factory.cli archive` defaults to the most recent *completed* week rather
# than to weeks[0].
WEEKLY_AT ?= Sun *-*-* 21:00:00 America/Los_Angeles
WEEKLY_AT_FALLBACK ?= Mon *-*-* 04:00:00 UTC

schedule-weekly-install:   schedule-weekly-install-$(SCHED)
schedule-weekly-uninstall: schedule-weekly-uninstall-$(SCHED)
schedule-weekly-status:    schedule-weekly-status-$(SCHED)

# -------------------------------------------------------------------- macOS
# launchd follows local time and DST, so :05 stays :05 through PST/PDT.
LAUNCHD_LABEL := com.etched.factory-analysis-refresh
LAUNCHD_DEST  := $(HOME)/Library/LaunchAgents/$(LAUNCHD_LABEL).plist

schedule-install-macos:
	@mkdir -p $(HOME)/Library/LaunchAgents data/logs
	@sed 's|__REPO__|$(REPO_DIR)|g' deploy/launchd/$(LAUNCHD_LABEL).plist > $(LAUNCHD_DEST)
	@launchctl unload $(LAUNCHD_DEST) 2>/dev/null || true
	@launchctl load $(LAUNCHD_DEST)
	@echo "Installed $(LAUNCHD_LABEL) — runs at :05 every hour."
	@echo "Logs: data/logs/refresh.log"

LAUNCHD_WEEKLY := com.etched.factory-analysis-weekly
LAUNCHD_WEEKLY_DEST := $(HOME)/Library/LaunchAgents/$(LAUNCHD_WEEKLY).plist

schedule-weekly-install-macos:
	@mkdir -p $(HOME)/Library/LaunchAgents data/logs
	@sed 's|__REPO__|$(REPO_DIR)|g' deploy/launchd/$(LAUNCHD_WEEKLY).plist \
	    > $(LAUNCHD_WEEKLY_DEST)
	@launchctl unload $(LAUNCHD_WEEKLY_DEST) 2>/dev/null || true
	@launchctl load $(LAUNCHD_WEEKLY_DEST)
	@echo "Installed $(LAUNCHD_WEEKLY) — Sundays at 21:00 local."
	@echo "Logs: data/logs/weekly.log"

schedule-weekly-uninstall-macos:
	@launchctl unload $(LAUNCHD_WEEKLY_DEST) 2>/dev/null || true
	@rm -f $(LAUNCHD_WEEKLY_DEST)
	@echo "Removed $(LAUNCHD_WEEKLY)."

schedule-weekly-status-macos:
	@launchctl list | grep $(LAUNCHD_WEEKLY) || echo "not loaded"
	@echo "---"
	@tail -12 data/logs/weekly.log 2>/dev/null || echo "no log yet"

schedule-uninstall-macos:
	@launchctl unload $(LAUNCHD_DEST) 2>/dev/null || true
	@rm -f $(LAUNCHD_DEST)
	@echo "Removed $(LAUNCHD_LABEL)."

schedule-status-macos:
	@launchctl list | grep $(LAUNCHD_LABEL) || echo "not loaded"
	@echo "---"
	@tail -12 data/logs/refresh.log 2>/dev/null || echo "no log yet"

# ------------------------------------------------------------------- systemd
# User units, so none of this needs root — the dashboard host grants exactly one
# sudo permission (dnf install) and this uses none of it.
SYSTEMD_DIR  := $(HOME)/.config/systemd/user
SYSTEMD_UNIT := factory-refresh

schedule-install-systemd:
	@mkdir -p $(SYSTEMD_DIR) data/logs
	@sed 's|__REPO__|$(REPO_DIR)|g' deploy/systemd/$(SYSTEMD_UNIT).service \
	    > $(SYSTEMD_DIR)/$(SYSTEMD_UNIT).service
	@cp deploy/systemd/$(SYSTEMD_UNIT).timer $(SYSTEMD_DIR)/$(SYSTEMD_UNIT).timer
	@systemctl --user daemon-reload
	@systemctl --user enable --now $(SYSTEMD_UNIT).timer
	@# A user timer dies at logout unless the user lingers, which is precisely
	@# the failure this host exists to eliminate. Say so loudly if it is refused.
	@loginctl enable-linger $(USER) 2>/dev/null \
	    && echo "Linger enabled — the timer runs whether or not you are logged in." \
	    || echo "WARNING: could not enable linger. The timer will STOP when you log out. Ask #infra-help for: loginctl enable-linger $(USER)"
	@# Don't wait out a 30-day collect just to install a timer.
	@systemctl --user start --no-block $(SYSTEMD_UNIT).service
	@echo "Installed $(SYSTEMD_UNIT).timer — runs at :05 every hour; first tick started now."

schedule-uninstall-systemd:
	@systemctl --user disable --now $(SYSTEMD_UNIT).timer 2>/dev/null || true
	@rm -f $(SYSTEMD_DIR)/$(SYSTEMD_UNIT).timer $(SYSTEMD_DIR)/$(SYSTEMD_UNIT).service
	@systemctl --user daemon-reload
	@echo "Removed $(SYSTEMD_UNIT)."

SYSTEMD_WEEKLY := factory-weekly

schedule-weekly-install-systemd:
	@mkdir -p $(SYSTEMD_DIR) data/logs
	@# Validate the zoned expression before installing it. systemd only learned
	@# to parse a timezone in a calendar spec in v252; on anything older the
	@# timer would fail to load and the week would silently never be archived.
	@ONCAL="$(WEEKLY_AT)"; \
	if ! systemd-analyze calendar "$$ONCAL" >/dev/null 2>&1; then \
	    ONCAL="$(WEEKLY_AT_FALLBACK)"; \
	    echo "NOTE: this systemd cannot parse a zoned calendar; using $$ONCAL."; \
	    echo "      That is 18:00 Pacific in summer and 17:00 in winter."; \
	fi; \
	sed "s|__REPO__|$(REPO_DIR)|g" deploy/systemd/$(SYSTEMD_WEEKLY).service \
	    > $(SYSTEMD_DIR)/$(SYSTEMD_WEEKLY).service; \
	sed "s|__ONCALENDAR__|$$ONCAL|" deploy/systemd/$(SYSTEMD_WEEKLY).timer \
	    > $(SYSTEMD_DIR)/$(SYSTEMD_WEEKLY).timer
	@systemctl --user daemon-reload
	@systemctl --user enable --now $(SYSTEMD_WEEKLY).timer
	@loginctl enable-linger $(USER) 2>/dev/null \
	    && echo "Linger enabled — the timer runs whether or not you are logged in." \
	    || echo "WARNING: could not enable linger. Ask #infra-help for: loginctl enable-linger $(USER)"
	@# Not started now: firing it on install would archive a partial week and
	@# overwrite the copy a later run would have made properly.
	@systemctl --user list-timers $(SYSTEMD_WEEKLY).timer --no-pager | head -3

schedule-weekly-uninstall-systemd:
	@systemctl --user disable --now $(SYSTEMD_WEEKLY).timer 2>/dev/null || true
	@rm -f $(SYSTEMD_DIR)/$(SYSTEMD_WEEKLY).timer $(SYSTEMD_DIR)/$(SYSTEMD_WEEKLY).service
	@systemctl --user daemon-reload
	@echo "Removed $(SYSTEMD_WEEKLY)."

schedule-weekly-status-systemd:
	@systemctl --user list-timers $(SYSTEMD_WEEKLY).timer --no-pager 2>/dev/null | head -4 || echo "not loaded"
	@systemctl --user is-active $(SYSTEMD_WEEKLY).service >/dev/null 2>&1 \
	    && echo "state: a snapshot is running now" \
	    || echo "state: idle — $$(systemctl --user show -p Result --value $(SYSTEMD_WEEKLY).service 2>/dev/null) on last run"
	@echo "---"
	@tail -12 data/logs/weekly.log 2>/dev/null || echo "no log yet"

schedule-status-systemd:
	@systemctl --user list-timers $(SYSTEMD_UNIT).timer --no-pager 2>/dev/null | head -4 || echo "not loaded"
	@systemctl --user is-active $(SYSTEMD_UNIT).service >/dev/null 2>&1 \
	    && echo "state: a refresh is running now" \
	    || echo "state: idle — $$(systemctl --user show -p Result --value $(SYSTEMD_UNIT).service 2>/dev/null) on last run"
	@loginctl show-user $(USER) -p Linger 2>/dev/null || true
	@echo "---"
	@tail -12 data/logs/refresh.log 2>/dev/null || echo "no log yet"

clean:
	rm -rf data/processed/* dashboard/data/metrics.js dashboard/data/stations.js \
	       dashboard/data/runs.js dashboard/data/dailyexcel.js \
	       dashboard/data/requests.js dashboard/data/pega_stations.js
	rm -f out/*.yaml
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

# Also drops the cached HTTP responses, forcing a full refetch next collect.
distclean: clean
	rm -rf data/raw/*


# --- shopfloor traceability -------------------------------------------------
# Part-SN topology + test records from pega-sfis and EOS. Two phases on purpose:
# `sfis-mirror` talks to both upstreams and writes an immutable snapshot;
# `sfis-unit` and `sfis-gaps` read only that snapshot, so they still answer when
# pega-sfis is down -- which is the whole reason the tool exists.
# See docs/sfis/README.md for the model and docs/sfis/JOIN.md for the join.

SFIS := $(PY) -m shopfloor

sfis-doctor:
	@$(SFIS) doctor

# VERDICTS=1 resolves EOS pass/fail: two extra API calls per run, cached in the
# snapshot forever because a finished run's verdict never changes.
sfis-mirror:
	@test -n "$(SN)" || { echo "usage: make sfis-mirror SN=<serial>"; exit 2; }
	@$(SFIS) mirror $(SN) --days $(SFIS_DAYS) $(if $(VERDICTS),--verdicts,)

sfis-level:
	@$(SFIS) mirror --level $(SFIS_LEVEL) --days $(SFIS_DAYS) $(if $(VERDICTS),--verdicts,)

sfis-unit:
	@test -n "$(SN)" || { echo "usage: make sfis-unit SN=<serial>"; exit 2; }
	@$(SFIS) unit $(SN)

sfis-units:
	@for sn in $$(ls snapshots/$$(cat snapshots/latest)/sfis/serial/*.json 2>/dev/null \
	              | xargs -n1 basename | sed 's/.json//'); do \
	    $(SFIS) unit $$sn 2>/dev/null || true; \
	done

# dashboard/data/trace.js, which customize.html loads if it is there. NOT part of
# `make build`: the hourly refresh must not start failing because pega-sfis is
# unreachable, and the page is written to render without this file. The
# traceability refresh is its own pair of steps:
#
#     make sfis-level LEVEL=6U && make sfis-dashboard
#
# NOYAML=1 drops the per-unit YAML text from the bundle -- smaller file, but the
# page loses its download button.
sfis-dashboard:
	@$(SFIS) trace $(if $(NOYAML),--no-yaml,)

# The close-loop check: take EOS's serials and look for each on the shopfloor.
# Live on both sides, because the question is whether the join is holding NOW.
sfis-reconcile:
	@$(SFIS) reconcile --days $(DAYS_RECONCILE) $(if $(LEVELS),--levels $(LEVELS),) $(if $(CSV),--csv $(CSV),)

sfis-gaps:
	@$(SFIS) gaps $(SN)

sfis-snapshots:
	@ls -1 snapshots/ 2>/dev/null | grep -v latest || echo "(none)"
