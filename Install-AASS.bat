@echo off
setlocal
cd /d "%~dp0"
title AASS Automatic Installer
echo AASS automatic setup - keep this window open.
echo.
if defined AASS_PYTHON if exist "%AASS_PYTHON%" goto run_direct
set "AASS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%AASS_PYTHON%" goto run_direct
where py >nul 2>nul
if errorlevel 1 goto install_python
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 goto run_launcher
:install_python
echo Installing Python 3.12 using the official winget package...
where winget >nul 2>nul
if errorlevel 1 goto no_winget
winget install --id Python.Python.3.12 --exact --source winget --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto failed
if exist "%AASS_PYTHON%" goto run_direct
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 goto run_launcher
echo Python needs a new terminal session. Close this window and double-click Install-AASS.bat again.
set "AASS_EXIT=2"
goto finish
:run_direct
"%AASS_PYTHON%" -u install_aass.py %*
set "AASS_EXIT=%ERRORLEVEL%"
goto finish
:run_launcher
py -3.12 -u install_aass.py %*
set "AASS_EXIT=%ERRORLEVEL%"
goto finish
:no_winget
echo Install Python 3.12 from python.org or Microsoft App Installer from the Store, then rerun this file.
:failed
set "AASS_EXIT=2"
:finish
echo.
if not "%AASS_EXIT%"=="0" goto needs_attention
echo Setup finished.
if "%~1"=="" call Start-AASS.bat
exit /b 0
:needs_attention
echo Setup needs attention. Read the explanation above. Logs are in the .aass folder.
pause
exit /b %AASS_EXIT%
