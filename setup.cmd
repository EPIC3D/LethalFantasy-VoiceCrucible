@echo off
title Voice Crucible - setup
rem Voice Crucible setup. It only runs the bundled uv.exe: first a small base environment, then
rem "crucible setup", which shows every download (source, size, license) and asks before installing.
rem --inexact: this first step never removes components that are already installed.
rem Started from the watcher ("Run setup"), it starts the coordinator again when it is done.
setlocal
call "%~dp0env.cmd"
"%VC_UV%" sync --frozen --inexact --python 3.12 --project "%VC%."
if errorlevel 1 goto end
"%UV_PROJECT_ENVIRONMENT%\Scripts\python.exe" -m voicecrucible.cli setup %*
if errorlevel 1 goto end
if "%VC_RESTART_COORDINATOR%"=="1" (
  echo.
  echo Setup is done - starting the coordinator again in its own window.
  start "" "%~dp0coordinator.cmd"
)
:end
if "%VC_NO_PAUSE%"=="" pause
