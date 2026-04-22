@echo off
setlocal

cd /d "%~dp0"
echo Starting portscout_win32_xp.exe
echo.

portscout_win32_xp.exe --no-pause %*
set EXITCODE=%ERRORLEVEL%

echo.
echo Exit code: %EXITCODE%
echo.
pause
exit /b %EXITCODE%
