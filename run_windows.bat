@echo off
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -c "from pathlib import Path; from app.collectors.browser_runtime import find_system_chromium; from playwright.sync_api import sync_playwright; b=find_system_chromium(); p=sync_playwright().start(); q=Path(p.chromium.executable_path); print('Using system browser: '+b if b else ('Using Playwright browser: '+str(q) if q.is_file() else 'NOTICE: No browser found. Install Google Chrome or Microsoft Edge, then restart Agent Shadi.')); p.stop()"
if not exist data mkdir data
echo.
echo Agent Shadi starting. Keep this window open.
echo Open http://127.0.0.1:8765 in your browser.
python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
pause
