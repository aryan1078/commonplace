@echo off
cd /d "%~dp0"
python scripts\setup_desktop.py %*
if errorlevel 1 pause
