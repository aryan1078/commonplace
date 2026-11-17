@echo off
cd /d "%~dp0"
python scripts\setup_browser.py --share --publish-status aryan1078/commonplace %*
if errorlevel 1 pause
