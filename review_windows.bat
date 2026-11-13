@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" review_tui.py
) else (
  py -3 review_tui.py
)
if errorlevel 1 pause
