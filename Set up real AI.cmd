@echo off
cd /d "%~dp0"
python scripts\setup_desktop.py --setup-only
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements-transformers.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\download_model.py --size 1.5b
if errorlevel 1 goto failed
echo Model setup finished. Stop the demo servers, then launch Commonplace again.
pause
exit /b 0
:failed
echo Setup did not complete. Read the error above before retrying.
pause
exit /b 1
