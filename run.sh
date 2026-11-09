#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

if [[ -x "$VENV_PY" ]]; then
  exec "$VENV_PY" "$SCRIPT_DIR/main.py" "$@"
else
  exec python3 "$SCRIPT_DIR/main.py" "$@"
fi

