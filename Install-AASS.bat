@echo off
setlocal
cd /d "%~dp0"
title AASS Setup
echo AASS Setup - packages and local checks first. Cloud verification is a separate menu option.
if defined AASS_PYTHON if exist "%AASS_PYTHON%" goto direct
set "AASS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%AASS_PYTHON%" goto direct
where py >nul 2>nul
if errorlevel 1 goto missing
if exist ".git" (py -3.12 -I -S verify_release.py --source-checkout) else (py -3.12 -I -S verify_release.py --prepare-update)
if errorlevel 1 goto stopped
py -3.12 -u install_aass.py %*
goto result
:direct
if exist ".git" ("%AASS_PYTHON%" -I -S verify_release.py --source-checkout) else ("%AASS_PYTHON%" -I -S verify_release.py --prepare-update)
if errorlevel 1 goto stopped
"%AASS_PYTHON%" -u install_aass.py %*
:result
set "AASS_EXIT=%ERRORLEVEL%"
if not "%AASS_EXIT%"=="0" goto stopped
if "%~1"=="" call Start-AASS.bat
exit /b 0
:missing
echo Python 3.12 is required. Install it from https://www.python.org/downloads/windows/ and rerun.
set "AASS_EXIT=2"
:stopped
if not defined AASS_EXIT set "AASS_EXIT=2"
echo Setup needs attention. Read the specific stage above. Do not disable Windows protection.
pause
exit /b %AASS_EXIT%
