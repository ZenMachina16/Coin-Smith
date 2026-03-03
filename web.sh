#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-3000}"

# Build the React UI if dist/ doesn't exist yet
if [[ ! -d "web/dist" ]]; then
  echo "Building React UI…" >&2
  cd web && npm install --silent && npm run build --silent && cd ..
fi

echo "http://127.0.0.1:${PORT}"
exec venv/bin/python server.py
