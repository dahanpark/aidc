@echo off
setlocal DisableDelayedExpansion
title AIDC ATLAS
if not exist "%~dp0scripts\start_atlas.ps1" goto missing_launcher
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_atlas.ps1" %*
set "ATLAS_EXIT_CODE=%ERRORLEVEL%"
if "%ATLAS_EXIT_CODE%"=="0" exit /b 0
echo.
echo AIDC ATLAS could not start. Check Python 3.10+ and runtime\launcher-error.txt.
pause
exit /b %ATLAS_EXIT_CODE%
:missing_launcher
echo AIDC ATLAS: scripts\start_atlas.ps1 is missing.
echo Extract the complete project ZIP before running this file.
pause
exit /b 2
