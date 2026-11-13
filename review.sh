#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
# Double-clicking the desktop launcher opens a dedicated terminal window.
if [[ ! -t 0 || ! -t 1 ]]; then
  if command -v konsole >/dev/null 2>&1; then
    exec konsole --new-window -e "$ROOT/review.sh"
  elif command -v x-terminal-emulator >/dev/null 2>&1; then
    exec x-terminal-emulator -e "$ROOT/review.sh"
  elif command -v gnome-terminal >/dev/null 2>&1; then
    exec gnome-terminal -- "$ROOT/review.sh"
  elif command -v xfce4-terminal >/dev/null 2>&1; then
    exec xfce4-terminal --command="$ROOT/review.sh"
  elif command -v xterm >/dev/null 2>&1; then
    exec xterm -e "$ROOT/review.sh"
  else
    echo "No terminal emulator was detected. Open a terminal in: $ROOT"
    echo "Then run: ./review.sh"
    exit 2
  fi
fi
if [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
exec "$PYTHON_BIN" review_tui.py
