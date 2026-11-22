@echo off
title Voice Crucible - worker
setlocal
rem Start a worker on this machine. Pair it first (pair.cmd). Stop with Ctrl+C.
rem If the coordinator asked for an update and it was installed, the worker exits with code 75
rem and is started again here with the new version. The restart loop runs from a temporary copy of
rem this file: an update replaces the program files (this one too) while the worker runs.
if defined VC_WORKER_LOOP goto loop
set "VC_HOME=%~dp0"
set "VC_WORKER_LOOP=%TEMP%\voicecrucible-worker-%RANDOM%%RANDOM%.cmd"
copy /y "%~f0" "%VC_WORKER_LOOP%" >nul || (set "VC_WORKER_LOOP=" & goto loop)
call "%VC_WORKER_LOOP%" %* & del "%VC_WORKER_LOOP%" >nul 2>&1 & exit /b
:loop
call "%VC_HOME%crucible.cmd" worker %*
if %errorlevel%==75 goto loop
if "%VC_NO_PAUSE%"=="" pause
