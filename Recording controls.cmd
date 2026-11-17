@echo off
cd /d "%~dp0"
title Commonplace recording controls
if not exist ".venv\Scripts\python.exe" (
  echo Start the application first using Start browser demo.cmd.
  pause
  exit /b 1
)
.venv\Scripts\python.exe scripts\recording_console.py
if errorlevel 1 pause
