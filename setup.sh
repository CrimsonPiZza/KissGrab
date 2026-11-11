#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_NAME="$(uname -s)"
INSTALL_FULL_FFMPEG=false
AUTO_YES=false

for arg in "$@"; do
  case "$arg" in
    --full|--bake)
      INSTALL_FULL_FFMPEG=true
      ;;
    -y|--yes)
      AUTO_YES=true
      ;;
    -h|--help)
      cat <<'EOF'
Usage: ./setup.sh [OPTIONS]

First-time setup helper for KissKH Episode Range Downloader.
Checks and installs Homebrew (macOS), ffmpeg, Python virtualenv (.venv),
kisskh-downloader, and Playwright + Chromium.

Options:
  --full, --bake   Install ffmpeg-full (adds libass for baked-in hardsubs)
  -y, --yes        Skip confirmation prompts and accept defaults
  -h, --help       Show this help message
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (use --help for usage)"
      exit 1
      ;;
  esac
done

confirm() {
  local prompt_text="$1"
  if [[ "$AUTO_YES" == "true" ]]; then
    return 0
  fi
  read -r -p "$prompt_text [Y/n]: " reply
  case "${reply:-Y}" in
    [Yy]|[Yy][Ee][Ss]|"")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

find_brew() {
  if command -v brew >/dev/null 2>&1; then
    command -v brew
    return 0
  fi
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

echo "================================================================"
echo "  KissKH Downloader - First-Time Setup"
echo "================================================================"
echo

# 1. Homebrew (macOS)
BREW_BIN=""
if [[ "$OS_NAME" == "Darwin" ]]; then
  if BREW_BIN="$(find_brew)"; then
    echo "[ok] Homebrew found: $BREW_BIN"
    eval "$("$BREW_BIN" shellenv)"
  else
    echo "[!] Homebrew is not installed on this Mac."
    echo "    Homebrew makes installing ffmpeg and Python effortless."
    if confirm "Install Homebrew now using the official installer?"; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      if BREW_BIN="$(find_brew)"; then
        eval "$("$BREW_BIN" shellenv)"
        ZPROFILE="$HOME/.zprofile"
        SHELLENV_LINE="eval \"\$($BREW_BIN shellenv)\""
        if [[ ! -f "$ZPROFILE" ]] || ! grep -qF "$BREW_BIN shellenv" "$ZPROFILE" 2>/dev/null; then
          echo >> "$ZPROFILE"
          echo "$SHELLENV_LINE" >> "$ZPROFILE"
          echo "[ok] Added Homebrew to $ZPROFILE"
        fi
        echo "[ok] Homebrew installed: $BREW_BIN"
      else
        echo "[error] Homebrew installation finished, but 'brew' was not found."
        exit 1
      fi
    else
      echo "[skip] Skipped Homebrew install."
    fi
  fi
fi

# 2. ffmpeg
echo
has_ffmpeg_sub_filter() {
  local bin="$1"
  "$bin" -hide_banner -filters 2>/dev/null | grep -qE '[[:space:]]subtitles[[:space:]]'
}

if [[ "$INSTALL_FULL_FFMPEG" == "true" ]]; then
  if [[ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ]] || [[ -x /usr/local/opt/ffmpeg-full/bin/ffmpeg ]]; then
    echo "[ok] ffmpeg-full (with baked-in subtitle support) is already installed."
  elif [[ -n "$BREW_BIN" ]]; then
    echo "[*] Installing ffmpeg-full via Homebrew..."
    "$BREW_BIN" install ffmpeg-full
    echo "[ok] ffmpeg-full installed."
  else
    echo "[warn] Homebrew is required to install ffmpeg-full automatically on macOS."
  fi
elif command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG_PATH="$(command -v ffmpeg)"
  echo "[ok] ffmpeg found: $FFMPEG_PATH"
  if ! has_ffmpeg_sub_filter "$FFMPEG_PATH" \
     && [[ ! -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ]] \
     && [[ ! -x /usr/local/opt/ffmpeg-full/bin/ffmpeg ]]; then
    echo "    Note: Soft-embedding subtitles in MP4 works right now."
    echo "    (Optional) Run './setup.sh --full' later if you also want baked-in hardsubs."
  fi
else
  echo "[!] ffmpeg is not installed (needed for video muxing & embedding subtitles)."
  if [[ "$OS_NAME" == "Darwin" ]] && [[ -n "$BREW_BIN" ]]; then
    if confirm "Install ffmpeg via Homebrew now?"; then
      "$BREW_BIN" install ffmpeg
      echo "[ok] ffmpeg installed."
    else
      echo "[warn] Continuing without ffmpeg (only separate .srt downloads will work)."
    fi
  elif [[ "$OS_NAME" == "Linux" ]]; then
    echo "    Please install ffmpeg with your package manager (e.g. 'sudo apt install ffmpeg')."
  fi
fi

# 3. Python 3 & Virtual Environment
echo
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif [[ -n "$BREW_BIN" ]]; then
  echo "[!] python3 not found. Installing python via Homebrew..."
  "$BREW_BIN" install python
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "[error] python3 is required. Please install Python 3.10+ and re-run ./setup.sh."
  exit 1
fi
echo "[ok] Python found: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "[*] Creating virtual environment in .venv..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "[*] Installing/updating Python dependencies..."
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r "$SCRIPT_DIR/requirements.txt"
echo "[ok] kisskh-downloader installed in .venv."

# 4. Playwright + Chromium (automatic kkey auth)
echo
if "$VENV_PY" -c "import playwright" >/dev/null 2>&1; then
  echo "[ok] Playwright Python package is installed."
else
  echo "[!] Playwright is needed to auto-generate KissKH 'kkey' tokens."
  if confirm "Install Playwright + Chromium now?"; then
    "$VENV_PY" -m pip install playwright
    "$VENV_PY" -m playwright install chromium
    echo "[ok] Playwright + Chromium installed."
  else
    echo "[skip] You can install it later inside the app under [4] Setup & Diagnostics."
  fi
fi

echo
echo "================================================================"
echo "  Setup Complete!"
echo "  Start the app anytime with:  ./run.sh"
echo "================================================================"

