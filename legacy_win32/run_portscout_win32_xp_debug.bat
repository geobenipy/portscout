@echo off
setlocal

cd /d "%~dp0"
set LOGFILE=%~dp0portscout_debug.log

echo ====================================== > "%LOGFILE%"
echo PortScout XP Debug Run >> "%LOGFILE%"
echo Date: %DATE% %TIME% >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Starting debug run...
echo Log file: %LOGFILE%
echo.

portscout_win32_xp.exe --no-pause %* >> "%LOGFILE%" 2>&1
set EXITCODE=%ERRORLEVEL%

echo. >> "%LOGFILE%"
echo Exit code: %EXITCODE% >> "%LOGFILE%"

echo ===== Log output =====
type "%LOGFILE%"
echo ======================
echo.
pause
exit /b %EXITCODE%
