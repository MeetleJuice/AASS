@echo off
setlocal
cd /d "%~dp0"
title AASS
if not exist ".venv\Scripts\python.exe" (
  echo Run Install-AASS.bat first.
  pause
  exit /b 2
)
if exist ".git" (".venv\Scripts\python.exe" -I -S verify_release.py --source-checkout) else (".venv\Scripts\python.exe" -I -S verify_release.py)
if errorlevel 1 goto stopped
".venv\Scripts\python.exe" -u local_app.py
set "AASS_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %AASS_EXIT%
:stopped
echo Release files could not be verified. Use an intact verified release; do not bypass protection.
pause
exit /b 2
