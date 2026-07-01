#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "Created .env from .env.example. Edit it if your tool paths need overrides."
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

PYTHON="$ROOT/.venv/bin/python"
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r requirements.txt
fi

echo "Starting AIO Downloader desktop app..."
"$PYTHON" -m app.desktop
