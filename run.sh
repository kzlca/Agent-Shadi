#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10+ first."
  exit 1
fi
if [ ! -d .venv ]; then "$PYTHON_BIN" -m venv .venv; fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Do not force Playwright's browser CDN download. In some regions the CDN
# returns HTTP 403 even while normal internet access works. Structura can use
# the distro-provided Chromium/Chrome executable instead.
BROWSER_INFO="$(python - <<'PY'
from pathlib import Path
from app.collectors.browser_runtime import find_system_chromium
from playwright.sync_api import sync_playwright
system = find_system_chromium()
if system:
    print(f"SYSTEM:{system}")
else:
    with sync_playwright() as p:
        bundled = Path(p.chromium.executable_path)
        print(f"BUNDLED:{bundled}" if bundled.is_file() else "MISSING:")
PY
)"
case "$BROWSER_INFO" in
  SYSTEM:*)
    export STRUCTURA_CHROMIUM_EXECUTABLE="${BROWSER_INFO#SYSTEM:}"
    echo "Using system browser: $STRUCTURA_CHROMIUM_EXECUTABLE"
    ;;
  BUNDLED:*)
    echo "Using existing Playwright browser: ${BROWSER_INFO#BUNDLED:}"
    ;;
  MISSING:*)
    echo
    echo "NOTICE: No Chromium/Chrome browser was found. The application will still start;"
    echo "Telegram/Rubika collection will become available after installing Chromium."
    echo "On Manjaro/Arch run: sudo pacman -S --needed chromium"
    echo "Then restart Agent Shadi."
    echo
    ;;
esac

mkdir -p data
chmod 700 data 2>/dev/null || true
echo
echo "Agent Shadi is starting. Keep this terminal open."
echo "Open http://127.0.0.1:8765 in your browser."
echo "Stop the server with Ctrl+C."
python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
