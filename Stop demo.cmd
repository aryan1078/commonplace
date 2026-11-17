@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
echo stop>logs\stop-requested
echo The demo launcher will stop its own servers. Saved documents stay on disk.
pause
