@echo off
title Voice Crucible - coordinator
rem Start the coordinator (job queue + watcher page). Stop with Ctrl+C.
call "%~dp0crucible.cmd" coordinator %*
if "%VC_NO_PAUSE%"=="" pause
