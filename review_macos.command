#!/bin/bash
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python review_tui.py
else
  exec python3 review_tui.py
fi
