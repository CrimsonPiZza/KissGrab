#!/usr/bin/env bash
set -euo pipefail

# Resolve symlinks so running a symlinked script from PATH works seamlessly
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  TARGET="$(readlink "$SOURCE")"
  if [[ "$TARGET" == /* ]]; then
    SOURCE="$TARGET"
  else
    SOURCE="$(dirname "$SOURCE")/$TARGET"
  fi
done
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"

if [[ -x "$VENV_PY" ]]; then
  exec "$VENV_PY" "$SCRIPT_DIR/main.py" "$@"
else
  exec python3 "$SCRIPT_DIR/main.py" "$@"
fi
