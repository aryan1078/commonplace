@echo off
cd /d "%~dp0"
python scripts\setup_browser.py %*
if errorlevel 1 pause
