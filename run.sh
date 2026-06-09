#!/usr/bin/env bash
# Launch Asclepius locally.
set -euo pipefail

cd "$(dirname "$0")"

# Load .env if present so ANTHROPIC_API_KEY etc. are available.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

PORT="${PORT:-8765}"
echo "Asclepius running at http://localhost:${PORT}"
exec ./.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port "${PORT}" "$@"
