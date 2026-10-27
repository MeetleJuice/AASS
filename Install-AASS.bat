@echo off
setlocal
cd /d "%~dp0"
title AASS Setup
echo AASS - preparing your permanent desktop application. Keep this window open.
if defined AASS_PYTHON if exist "%AASS_PYTHON%" goto direct
set "AASS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%AASS_PYTHON%" goto direct
where py >nul 2>nul
if errorlevel 1 goto missing
set "AASS_RUN=py -3.12"
goto run
:direct
set "AASS_RUN="%AASS_PYTHON%""
:run
if "%~1"=="--start-managed" goto start
if exist "RELEASE-MANIFEST.json" (
  %AASS_RUN% -I -S verify_release.py
  if errorlevel 1 goto stopped
)
if "%~1"=="" (%AASS_RUN% -u desktop_bootstrap.py) else (%AASS_RUN% -u install_aass.py %*)
goto result
:start
if exist ".aass\managed-install.json" (%AASS_RUN% -u desktop_launcher.py --root "%~dp0.") else (%AASS_RUN% -u desktop_bootstrap.py)
:result
set "AASS_EXIT=%ERRORLEVEL%"
if not "%AASS_EXIT%"=="0" goto stopped
exit /b 0
:missing
echo Python 3.12 with Tcl/Tk is required. Install it from https://www.python.org/downloads/windows/ and rerun.
set "AASS_EXIT=2"
:stopped
if not defined AASS_EXIT set "AASS_EXIT=2"
echo Setup needs attention. Read the specific stage above. Keep Windows protection enabled.
pause
exit /b %AASS_EXIT%
