@echo off
setlocal

cd /d "%~dp0"
echo Starting portable PortScout XP build
echo.

"%~dp0portscout_win32_xp_portable\portscout_win32_xp_portable.exe" --no-pause %*
set EXITCODE=%ERRORLEVEL%

echo.
echo Exit code: %EXITCODE%
echo.
pause
exit /b %EXITCODE%
