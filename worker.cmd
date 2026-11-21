@echo off
rem Start a worker on this machine. Pair it first (pair.cmd). Stop with Ctrl+C.
rem If the coordinator asked for an update and it was installed, the worker exits with code 75
rem and is started again here with the new version.
:start
call "%~dp0crucible.cmd" worker %*
if %errorlevel%==75 goto start
if "%VC_NO_PAUSE%"=="" pause
