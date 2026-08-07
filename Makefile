# factory_data_analysis — no dependencies beyond Python 3.9+ stdlib.

PY      ?= python3
export PYTHONPATH := src
PORT    ?= 8787
LEVEL   ?= l10
DAYS    ?= 2

.PHONY: help demo collect build report serve test inspect levels clean distclean

help:
	@echo "make demo               synthetic data + dashboard bundle (no API key needed)"
	@echo "make collect [DAYS=2]   fetch real runs from the EOS API into data/processed/"
	@echo "make build              compile data/processed/runs.json into the dashboard bundle"
	@echo "make report             print the hourly metrics as text"
	@echo "make serve [PORT=8787]  serve the dashboard at http://127.0.0.1:\$$(PORT)/"
	@echo "make test               run the unit tests"
	@echo "make inspect            show live API field names and how parse.py maps them"
	@echo "make clean              remove generated data and the dashboard bundle"

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

clean:
	rm -rf data/processed/* dashboard/data/metrics.js
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

# Also drops the cached HTTP responses, forcing a full refetch next collect.
distclean: clean
	rm -rf data/raw/*
