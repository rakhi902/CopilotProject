#!/usr/bin/env bash
# One-click setup + launcher for local development (macOS / Linux).
#
# Zero setup: local development uses a SQLite file, so there's no database server
# to install. Safe to run any time; it skips whatever is already done:
#   1. find Python 3
#   2. create the virtualenv (backend/.venv) if missing
#   3. install the dependencies if they aren't installed yet
#   4. create backend/.env (with a generated JWT secret) if missing
#   5. run the database migrations (creates the local SQLite database)
#   6. start the API and the frontend, then open your browser
#
# Stop both servers with Ctrl-C.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"

step() { printf "\n\033[1;36m==>\033[0m %s\n" "$1"; }

# 1. Find a suitable Python 3 (3.10-3.12).
step "Looking for Python 3"
PYTHON_BIN=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PYTHON_BIN="$cand"; break; fi
done
if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3 wasn't found. Install it (e.g. 'brew install python@3.11') and re-run ./run.sh."
  exit 1
fi
echo "Using $("$PYTHON_BIN" --version)"

# 2. Create the virtualenv if it isn't there.
if [ ! -x "$PY" ]; then
  step "Creating the virtual environment (backend/.venv)"
  "$PYTHON_BIN" -m venv "$VENV"
fi

# 3. Install dependencies only if they're missing from the venv.
step "Checking dependencies"
DEP_CHECK='import fastapi, uvicorn, sqlalchemy, alembic, pydantic_settings, langgraph, langchain_groq, fpdf, docx, pypdf, jose, passlib, bs4'
if "$PY" -c "$DEP_CHECK" >/dev/null 2>&1; then
  echo "Dependencies already installed."
else
  echo "Installing dependencies (first run can take a minute)..."
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r "$BACKEND/requirements.txt"
fi

# 4. Make sure backend/.env exists (for your JWT secret and Groq key).
step "Preparing backend/.env"
"$PY" "$BACKEND/setup_env.py"
echo "  (Add your GROQ_API_KEY to backend/.env for AI generation: https://console.groq.com/keys)"

# 5. Create / update the local SQLite database via the migrations.
step "Running database migrations (SQLite)"
( cd "$BACKEND" && "$PY" -m alembic upgrade head )

# 6. Start the servers and open the browser.
step "Starting the servers"
( cd "$BACKEND" && "$PY" -m uvicorn app.main:app --reload ) &
BACKEND_PID=$!
( cd "$FRONTEND" && "$PY" -m http.server 5500 ) &
FRONTEND_PID=$!

cleanup() {
  echo
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "  Backend API -> http://127.0.0.1:8000"
echo "  Frontend UI -> http://127.0.0.1:5500"

sleep 2
if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:5500"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:5500"
fi

# Keep the script in the foreground so the servers stay up until Ctrl-C.
wait
