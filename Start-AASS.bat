@echo off
setlocal
cd /d "%~dp0"
title AASS
if not exist ".venv\Scripts\python.exe" (
  call Install-AASS.bat
  exit /b
)
if exist ".git" (".venv\Scripts\python.exe" -I -S verify_release.py --source-checkout) else (".venv\Scripts\python.exe" -I -S verify_release.py)
if errorlevel 1 goto stopped
".venv\Scripts\python.exe" -u setup_wizard.py
set "AASS_EXIT=%ERRORLEVEL%"
if not "%AASS_EXIT%"=="0" pause
exit /b %AASS_EXIT%
:stopped
echo Release files could not be verified. Use an intact verified release; do not bypass protection.
pause
exit /b 2
