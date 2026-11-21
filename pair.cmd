@echo off
rem Pair this computer as a worker. The code is shown by coordinator.cmd and in the watcher page.
set /p "VC_CODE=Pairing code (e.g. ABCDE-FGHJK): "
call "%~dp0crucible.cmd" pair %VC_CODE% %*
pause
