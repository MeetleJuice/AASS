@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 launch_aass.py %*
) else (
  python launch_aass.py %*
)
if %errorlevel% neq 0 pause
