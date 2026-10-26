@echo off
setlocal
cd /d "%~dp0"
title AASS
if not exist ".venv\Scripts\python.exe" (
  echo Run Install-AASS.bat first.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -u local_app.py
set "AASS_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %AASS_EXIT%
