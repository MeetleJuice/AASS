@echo off
setlocal
cd /d "%~dp0"
title AASS Connection Check
if not exist ".venv\Scripts\python.exe" (
  echo Run Install-AASS.bat first, or place this file in your already installed AASS folder.
  pause
  exit /b 2
)
echo Checking the local worker and cloud judge. Provider charges may apply.
echo.
".venv\Scripts\python.exe" -u -m orchestration_canvas verify-live
set "AASS_EXIT=%ERRORLEVEL%"
echo.
if not "%AASS_EXIT%"=="0" echo Share the stage, http_status, provider_code and hint above. Keep API keys private.
pause
exit /b %AASS_EXIT%
