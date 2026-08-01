# EduForge AI — developer entry points.
#
# The venv is Linux-native and lives at ./.venv. This project ships in a Linux
# container, so developing against a Linux interpreter keeps dev and prod on the
# same footing — and on WSL it avoids the 9P filesystem bridge, which makes pip
# roughly two orders of magnitude slower.
#
# From Windows, drive these through WSL:  wsl -e bash -lc "cd ~/EduForge-AI && make test"

PY      := ./.venv/bin/python
PIP     := $(PY) -m pip
# NB: `python -m importlinter.cli` silently exits 0 without checking anything.
# Only the console script actually runs the contracts.
IMPORTS := ./.venv/bin/lint-imports
BACKEND := backend
export PYTHONPATH := $(BACKEND)

DOCKER      := docker
IMAGE       := eduforge-ai
CONTAINER   := eduforge-ai

.DEFAULT_GOAL := help
# `samples` must be declared phony: samples/ is a real directory, so without this
# make considers the target already built and does nothing.
.PHONY: help venv install dev test test-contract lint boundaries hygiene fmt typecheck schema fixtures evals samples check clean docker-build docker-run

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv:  ## Create the virtual environment
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip setuptools wheel

install: venv  ## Install runtime + dev dependencies
	$(PIP) install -q -e "$(BACKEND)[dev]"

dev:  ## Run the API with reload at http://localhost:8000
	$(PY) -m uvicorn api.main:app --reload --app-dir $(BACKEND) --port 8000

test:  ## Run the full test suite
	$(PY) -m pytest $(BACKEND)/tests -q

test-contract:  ## Run only the contract suite (the MS-0 gate)
	$(PY) -m pytest $(BACKEND)/tests/contract -q

lint:  ## Lint
	$(PY) -m ruff check $(BACKEND) scripts

boundaries:  ## Enforce module boundaries (a stage importing a stage fails here)
	$(IMPORTS) --config $(BACKEND)/pyproject.toml

fmt:  ## Auto-format and fix
	$(PY) -m ruff format $(BACKEND) scripts
	$(PY) -m ruff check --fix $(BACKEND) scripts

typecheck:  ## Static type check
	$(PY) -m mypy $(BACKEND)/contracts $(BACKEND)/core

schema:  ## Regenerate the published JSON Schema and fixtures
	$(PY) scripts/generate_schema.py

hygiene:  ## Fail if generated files or secrets are tracked
	$(PY) scripts/check_repo_hygiene.py

check:  ## Everything CI runs
	$(PY) scripts/generate_schema.py --check
	$(PY) scripts/check_repo_hygiene.py
	$(PY) -m ruff check $(BACKEND) scripts
	$(IMPORTS) --config $(BACKEND)/pyproject.toml
	$(PY) -m pytest $(BACKEND)/tests -q

evals:  ## Score the reference packages on the 9-dimension rubric
	$(PY) -m pytest $(BACKEND)/tests/unit/test_evals.py -q
	$(PY) scripts/build_samples.py

samples:  ## Regenerate samples/ (packages, PDFs, eval reports) from the fixtures
	$(PY) scripts/build_samples.py

evals:  ## Score the reference packages on the 9-dimension rubric
	 -m pytest /tests/unit/test_evals.py -q
	 scripts/build_samples.py

samples:  ## Regenerate samples/ (packages, PDFs, and eval reports) from fixtures
	 scripts/build_samples.py

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +

docker-build:  ## Build the production image (see Dockerfile)
	$(DOCKER) build -t $(IMAGE) .

docker-run:  ## Run the image locally on :8000 using ./.env (needs docker-build first)
	$(DOCKER) run --rm -p 8000:8000 --env-file .env --name $(CONTAINER) $(IMAGE)
