@echo off
cd /d "%~dp0"
if "%~1"=="" goto interactive
if not exist ".venv\Scripts\python.exe" goto install
".venv\Scripts\python.exe" -u launch_aass.py %*
if errorlevel 1 pause
exit /b
:interactive
if not exist ".venv\Scripts\python.exe" goto install
call Start-AASS.bat
exit /b
:install
call Install-AASS.bat
