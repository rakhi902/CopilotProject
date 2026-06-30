# Job Application Co-Pilot - task runner (works on macOS, Linux, and Windows).
#
# Needs GNU Make and a POSIX shell. macOS and Linux have both already; on Windows
# run it from Git Bash or WSL, or just run the command each target wraps (see
# `make help`) by hand.
#
# Typical first run (local dev uses SQLite, so there's nothing else to install):
#   make setup         # venv + dependencies + .env + migrate (creates the SQLite DB)
#   make backend       # run the API           (terminal 1)
#   make frontend      # serve the UI on :5500 (terminal 2)
#   make test          # run the test suite
#
# Or skip all of this and run ./run.sh, which does the same and opens the browser.

# Pick the right venv layout + bootstrap interpreter for the host OS.
ifeq ($(OS),Windows_NT)
    PY    := .venv/Scripts/python.exe
    SYSPY := py -3.10
else
    PY    := .venv/bin/python
    SYSPY := python3.10
endif

.DEFAULT_GOAL := help
.PHONY: help venv install install-dev env migrate setup backend frontend test coverage clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

venv: ## Create the Python 3.10 virtual environment in backend/.venv
	cd backend && $(SYSPY) -m venv .venv

install: venv ## Install runtime dependencies into the venv
	cd backend && $(PY) -m pip install --upgrade pip && $(PY) -m pip install -r requirements.txt

install-dev: venv ## Install runtime + test dependencies into the venv
	cd backend && $(PY) -m pip install --upgrade pip && $(PY) -m pip install -r requirements-dev.txt

env: ## Create backend/.env (if missing) with a generated JWT secret
	cd backend && $(PY) setup_env.py

migrate: ## Apply database migrations (creates/upgrades the local SQLite schema)
	cd backend && $(PY) -m alembic upgrade head

setup: install-dev env migrate ## One-shot: venv + dependencies + .env + migrations

backend: ## Run the FastAPI backend with autoreload (http://127.0.0.1:8000)
	cd backend && $(PY) -m uvicorn app.main:app --reload

frontend: ## Serve the static frontend (http://127.0.0.1:5500)
	cd frontend && $(SYSPY) -m http.server 5500

test: ## Run the pytest suite
	cd backend && $(PY) -m pytest

coverage: ## Run the test suite with a coverage report
	cd backend && $(PY) -m pytest --cov=app --cov-report=term-missing

clean: ## Remove caches and test artifacts
	cd backend && rm -rf .pytest_cache .coverage htmlcov && find . -type d -name __pycache__ -prune -exec rm -rf {} +
