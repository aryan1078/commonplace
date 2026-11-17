@echo off
set "PROJECT_DIR=%~dp0..\collab-platform"
if not exist "%PROJECT_DIR%\run.py" set "PROJECT_DIR=%~dp0.."
if not exist "%PROJECT_DIR%\run.py" (
  echo Keep this Recording Kit beside the collab-platform folder or inside the project.
  pause
  exit /b 1
)
cd /d "%PROJECT_DIR%"
title SERVER - leave this window open
call "Start browser demo.cmd"
