@echo off
rem Run any Voice Crucible command, e.g.  crucible render --lines <export folder>
setlocal
call "%~dp0env.cmd"
if not exist "%UV_PROJECT_ENVIRONMENT%\Scripts\python.exe" (
  echo Voice Crucible is not set up yet - run setup.cmd first.
  exit /b 1
)
"%UV_PROJECT_ENVIRONMENT%\Scripts\python.exe" -m voicecrucible.cli %*
