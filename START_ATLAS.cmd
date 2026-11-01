@echo off
setlocal DisableDelayedExpansion
title AIDC ATLAS - Start
if not exist "%~dp0AIDC ATLAS.cmd" goto missing_launcher
call "%~dp0AIDC ATLAS.cmd" %*
exit /b %ERRORLEVEL%
:missing_launcher
echo AIDC ATLAS: the common launcher is missing.
echo Download and extract the complete project ZIP, then run START_ATLAS.cmd.
pause
exit /b 2
