# factory_data_analysis — no dependencies beyond Python 3.9+ stdlib.

PY      ?= python3
export PYTHONPATH := src
PORT    ?= 8787
LEVEL   ?= l10
DAYS    ?= 2
WINDOW  ?= 30
STATION ?= l10_sft

.PHONY: help trust demo collect build report serve test inspect levels refresh status \
        schedule-install schedule-uninstall schedule-status publish refresh-publish items \
        dailyexcel requests l10 pega-stations builds validation fpy weekly archive \
        schedule-install-macos schedule-uninstall-macos schedule-status-macos \
        schedule-install-systemd schedule-uninstall-systemd schedule-status-systemd \
        update clean distclean

help:
	@echo "make trust              install Etched's internal CA bundle (fixes TLS errors)"
	@echo "make update             FULL UPDATE: collect + items + rebuild + publish"
	@echo "make refresh            one scheduler tick: collect + rebuild (WINDOW=30 days)"
	@echo "make status             last fetch vs last update, per station"
	@echo "make publish            publish dashboard/ (FACTORY_WEB_ROOT, else gh-pages)"
	@echo "make items [STATION=..]  flatten test cases to numeric test items"
	@echo "make dailyexcel         compile daily/*.xlsx (MLT/HTT tracker) into the dashboard"
	@echo "make requests           re-check what we need from other systems"
	@echo "make l10                build the L10 daily tracker (FAT/SFT/RIN/2U) from pega4"
	@echo "make schedule-install   install the hourly job (launchd / systemd timer)"
	@echo "make demo               synthetic data + dashboard bundle (no API key needed)"
	@echo "make collect [DAYS=2]   fetch real runs from the EOS API into data/processed/"
	@echo "make build              compile data/processed/runs.json into the dashboard bundle"
	@echo "make report             print the hourly metrics as text"
	@echo "make serve [PORT=8787]  serve the dashboard at http://127.0.0.1:\$$(PORT)/"
	@echo "make test               run the unit tests"
	@echo "make inspect            show live API field names and how parse.py maps them"
	@echo "make clean              remove generated data and the dashboard bundle"

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

# The L10 daily tracker (FAT, SFT, RIN, 2U) from pega4. Also part of `make build`.
l10:
	$(PY) -m factory.cli l10

# Station yield straight from the ESVM controllers, for comparison with the
# OCP/EOS-sourced page. Also part of `make build`.
pega-stations:
	$(PY) -m factory.cli pega-stations

# Mark each run as a new build or a retest, with what a returning unit failed
# last time. Also part of `make build`.
builds:
	$(PY) -m factory.cli builds

# One suite's validation run, unit by unit, with the reconciliation that
# explains why other pages report a different count for the same day.
validation:
	$(PY) -m factory.cli validation

# End-to-end first-pass yield, one row per test step — the weekly summary.
fpy:
	$(PY) -m factory.cli fpy

# Pack the week out: the bundle as it stood, plus a readable summary, under a
# dated folder in weekly/. The dashboard always shows the current seven days,
# so without this the comparison a month from now has nothing to compare to.
weekly:
	$(PY) -m factory.cli weekly

# Pack a week out for later comparison: the bundle as it stood plus a readable
# summary, under a dated folder in weekly/.
archive: fpy
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
	       dashboard/data/requests.js dashboard/data/l10daily.js dashboard/data/pega_stations.js dashboard/data/builds.js dashboard/data/validation.js
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

# Also drops the cached HTTP responses, forcing a full refetch next collect.
distclean: clean
	rm -rf data/raw/*
