@echo off
rem Voice Crucible setup. It only runs the bundled uv.exe: first a small base environment, then
rem "crucible setup", which shows every download (source, size, license) and asks before installing.
rem --inexact: this first step never removes components that are already installed.
setlocal
call "%~dp0env.cmd"
"%VC_UV%" sync --frozen --inexact --python 3.12 --project "%VC%."
if errorlevel 1 goto end
"%UV_PROJECT_ENVIRONMENT%\Scripts\python.exe" -m voicecrucible.cli setup %*
:end
if "%VC_NO_PAUSE%"=="" pause
