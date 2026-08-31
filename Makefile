# Local shopfloor topology + test-record graph.
#
# Two phases, deliberately separate:
#   mirror   talks to pega-sfis and EOS, writes an immutable snapshot
#   unit     reads a snapshot only, writes YAML — works with both hosts down
#
# The second phase is the product. Everything else exists to feed it.

PY      ?= python3
SRC     := src
RUN     := PYTHONPATH=$(SRC) $(PY) -m shopfloor
SN      ?=
LEVEL   ?= 6U
DAYS    ?= 120

.PHONY: help doctor mirror mirror-level unit units gaps test clean snapshots

help:
	@echo "make doctor                    can we reach pega-sfis and EOS, with what credential"
	@echo "make mirror SN=268947020002    snapshot one root (add VERDICTS=1 for EOS pass/fail)"
	@echo "make mirror-level LEVEL=6U     snapshot every serial at a level (slow, complete)"
	@echo "make unit SN=268947020002      render out/<SN>.yaml from the latest snapshot [offline]"
	@echo "make units                     render every serial in the latest snapshot [offline]"
	@echo "make gaps SN=268947020002      findings: escapes, unlinked test DUTs, unknown slots"
	@echo "make test                      unit tests (no network)"
	@echo ""
	@echo "latest snapshot: $$(cat snapshots/latest 2>/dev/null || echo none)"

doctor:
	@$(RUN) doctor

# VERDICTS=1 resolves EOS pass/fail, which costs two extra API calls per run and
# is cached in the snapshot forever — a finished run's verdict never changes.
mirror:
	@test -n "$(SN)" || { echo "usage: make mirror SN=<serial>"; exit 2; }
	@$(RUN) mirror $(SN) --days $(DAYS) $(if $(VERDICTS),--verdicts,)

mirror-level:
	@$(RUN) mirror --level $(LEVEL) --days $(DAYS) $(if $(VERDICTS),--verdicts,)

unit:
	@test -n "$(SN)" || { echo "usage: make unit SN=<serial>"; exit 2; }
	@$(RUN) unit $(SN)

# Render everything the latest snapshot holds a tree for. Cheap: no network.
units:
	@for sn in $$(ls snapshots/$$(cat snapshots/latest)/sfis/serial/*.json 2>/dev/null \
	              | xargs -n1 basename | sed 's/.json//'); do \
	    $(RUN) unit $$sn 2>/dev/null || true; \
	done

gaps:
	@$(RUN) gaps $(SN)

test:
	@for t in tests/test_*.py; do $(PY) $$t || exit 1; done

snapshots:
	@ls -1 snapshots/ 2>/dev/null | grep -v latest || echo "(none)"

clean:
	@rm -rf out/*.yaml && find . -name __pycache__ -type d -prune -exec rm -rf {} +
