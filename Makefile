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
        update clean distclean

help:
	@echo "make trust              install Etched's internal CA bundle (fixes TLS errors)"
	@echo "make update             FULL UPDATE: collect + items + rebuild + publish"
	@echo "make refresh            one scheduler tick: collect + rebuild (WINDOW=30 days)"
	@echo "make status             last fetch vs last update, per station"
	@echo "make publish            push dashboard/ to GitHub Pages (private)"
	@echo "make items [STATION=..]  flatten test cases to numeric test items"
	@echo "make schedule-install   install the hourly launchd agent"
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

# ---------------------------------------------------------------- scheduler
# Hourly launchd agent. launchd follows local time and DST, so :05 stays :05
# through PST/PDT.
LAUNCHD_LABEL := com.etched.factory-analysis-refresh
LAUNCHD_DEST  := $(HOME)/Library/LaunchAgents/$(LAUNCHD_LABEL).plist
REPO_DIR      := $(shell pwd)

schedule-install:
	@mkdir -p $(HOME)/Library/LaunchAgents data/logs
	@sed 's|__REPO__|$(REPO_DIR)|g' deploy/launchd/$(LAUNCHD_LABEL).plist > $(LAUNCHD_DEST)
	@launchctl unload $(LAUNCHD_DEST) 2>/dev/null || true
	@launchctl load $(LAUNCHD_DEST)
	@echo "Installed $(LAUNCHD_LABEL) — runs at :05 every hour."
	@echo "Logs: data/logs/refresh.log"

schedule-uninstall:
	@launchctl unload $(LAUNCHD_DEST) 2>/dev/null || true
	@rm -f $(LAUNCHD_DEST)
	@echo "Removed $(LAUNCHD_LABEL)."

schedule-status:
	@launchctl list | grep $(LAUNCHD_LABEL) || echo "not loaded"
	@echo "---"
	@tail -12 data/logs/refresh.log 2>/dev/null || echo "no log yet"

clean:
	rm -rf data/processed/* dashboard/data/metrics.js dashboard/data/stations.js
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

# Also drops the cached HTTP responses, forcing a full refetch next collect.
distclean: clean
	rm -rf data/raw/*
