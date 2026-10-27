@echo off
setlocal
cd /d "%~dp0"
call Install-AASS.bat --start-managed
exit /b %ERRORLEVEL%
