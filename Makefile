# Organoid Protocol Atlas — developer convenience targets
# All targets are safe to run locally and in CI. No network required for 'test'.
# Targets that call external services (SRI, EuropePMC) require internet access.
#
# Usage:
#   make test            — run full offline test suite (used by CI)
#   make status          — system status: which analytics outputs exist
#   make all-analytics   — regenerate all pre-computed analytics artifacts
#   make serve           — start Datasette on localhost:8001
#   make kgx             — regenerate KGX nodes/edges from public exports

PYTHON  ?= python3
PYTEST  ?= $(PYTHON) -m pytest
PIPELINE = pipeline
TESTS    = tests

# --------------------------------------------------------------------------- #
# Testing (offline, no network)
# --------------------------------------------------------------------------- #

.PHONY: test
test:
	$(PYTEST) -q

.PHONY: test-verbose
test-verbose:
	$(PYTEST) -v

.PHONY: test-cov
test-cov:
	$(PYTEST) -q --cov=$(PIPELINE) --cov-report=term-missing

# --------------------------------------------------------------------------- #
# System status
# --------------------------------------------------------------------------- #

.PHONY: status
status:
	$(PYTHON) $(PIPELINE)/system_status.py

.PHONY: status-json
status-json:
	$(PYTHON) $(PIPELINE)/system_status.py --json

# --------------------------------------------------------------------------- #
# Analytics pipeline (all pre-computed outputs)
# --------------------------------------------------------------------------- #

.PHONY: failure-modes
failure-modes:
	$(PYTHON) $(PIPELINE)/aggregate_failure_modes.py

.PHONY: lineage
lineage:
	$(PYTHON) $(PIPELINE)/build_lineage.py

.PHONY: coverage-report
coverage-report:
	$(PYTHON) $(PIPELINE)/generate_coverage_report.py

.PHONY: assay-endpoints
assay-endpoints:
	$(PYTHON) $(PIPELINE)/aggregate_assay_endpoints.py

.PHONY: quality
quality:
	$(PYTHON) $(PIPELINE)/score_protocol_quality.py

.PHONY: mior
mior:
	$(PYTHON) $(PIPELINE)/score_mior.py

.PHONY: consistency
consistency:
	$(PYTHON) $(PIPELINE)/check_concentration_consistency.py

.PHONY: audit-units
audit-units:
	$(PYTHON) $(PIPELINE)/audit_units.py

.PHONY: consensus
consensus:
	$(PYTHON) $(PIPELINE)/compute_consensus.py --all

# Run the whole analytics pipeline in dependency order
.PHONY: all-analytics
all-analytics: failure-modes lineage coverage-report assay-endpoints quality mior consistency audit-units consensus
	@echo "Analytics pipeline complete — run 'make status' to verify"

# --------------------------------------------------------------------------- #
# KGX (Biolink knowledge graph export)
# --------------------------------------------------------------------------- #

.PHONY: kgx
kgx:
	$(PYTHON) $(PIPELINE)/export_kgx.py

# Validate KGX with kgx CLI if installed (optional)
.PHONY: validate-kgx
validate-kgx:
	@command -v kgx >/dev/null 2>&1 || { echo "kgx not installed — skipping (pip install kgx)"; exit 0; }
	kgx validate exports/kgx/

# --------------------------------------------------------------------------- #
# TRAPI
# --------------------------------------------------------------------------- #

.PHONY: trapi-meta
trapi-meta:
	$(PYTHON) $(PIPELINE)/trapi.py --meta

.PHONY: trapi-examples
trapi-examples:
	@for f in $(PIPELINE)/trapi_examples/*.json; do \
	  echo "--- $$f ---"; \
	  $(PYTHON) $(PIPELINE)/trapi.py --query $$f | python3 -m json.tool --no-ensure-ascii | head -30; \
	done

# --------------------------------------------------------------------------- #
# Serve (Datasette)
# --------------------------------------------------------------------------- #

.PHONY: serve
serve:
	bash serve/run.sh

# --------------------------------------------------------------------------- #
# Public export
# --------------------------------------------------------------------------- #

.PHONY: export
export:
	$(PYTHON) $(PIPELINE)/export_public.py

# --------------------------------------------------------------------------- #
# Dev setup
# --------------------------------------------------------------------------- #

.PHONY: install
install:
	pip install -r requirements-dev.txt

.PHONY: install-extras
install-extras:
	pip install -r requirements-dev.txt sentence-transformers scikit-learn kgx

# --------------------------------------------------------------------------- #
# Convenience
# --------------------------------------------------------------------------- #

.PHONY: clean-cache
clean-cache:
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -not -path './.git/*' -delete 2>/dev/null || true

.PHONY: help
help:
	@echo "Organoid Protocol Atlas — Makefile targets"
	@echo ""
	@echo "  Testing:"
	@echo "    test               Run full offline test suite"
	@echo "    test-verbose       Run tests with verbose output"
	@echo "    test-cov           Run tests with coverage report"
	@echo ""
	@echo "  Analytics pipeline:"
	@echo "    all-analytics      Regenerate all pre-computed outputs"
	@echo "    quality            Protocol quality scores"
	@echo "    mior               MIOR completeness report"
	@echo "    consistency        Cross-paper concentration consistency"
	@echo "    audit-units        Concentration unit validity audit"
	@echo "    consensus          Cross-paper reagent consensus"
	@echo "    failure-modes      Failure mode aggregation"
	@echo "    lineage            Protocol lineage graph"
	@echo "    coverage-report    Corpus coverage report"
	@echo "    assay-endpoints    Assay endpoint summary"
	@echo ""
	@echo "  Knowledge graph:"
	@echo "    kgx                Export Biolink KGX nodes/edges"
	@echo "    validate-kgx       Validate KGX with kgx CLI"
	@echo "    trapi-meta         Show TRAPI responder meta info"
	@echo "    trapi-examples     Run all canned TRAPI query examples"
	@echo ""
	@echo "  Server:"
	@echo "    serve              Start Datasette on localhost:8001"
	@echo ""
	@echo "  Status:"
	@echo "    status             System status (which artifacts exist)"
	@echo "    status-json        System status as JSON"
	@echo ""
	@echo "  Setup:"
	@echo "    install            Install dev dependencies"
	@echo "    install-extras     Install dev + sentence-transformers + kgx"
