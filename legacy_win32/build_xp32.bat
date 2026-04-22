@echo off
setlocal

set ROOT=%~dp0
set PYTHON=%ROOT%toolchain\python34\python.exe
set PYINSTALLER=%ROOT%toolchain\python34\Scripts\pyinstaller.exe
set SCRIPT=%ROOT%portscout_win32.py
set DIST=%ROOT%
set WORK=%ROOT%build_local
set SPEC=%ROOT%

if not exist "%PYINSTALLER%" (
    echo PyInstaller not found: %PYINSTALLER%
    exit /b 1
)

"%PYINSTALLER%" --clean --onefile --name portscout_win32_xp --distpath "%DIST%" --workpath "%WORK%" --specpath "%SPEC%" "%SCRIPT%"
if errorlevel 1 exit /b %errorlevel%

"%PYINSTALLER%" --clean --onedir --name portscout_win32_xp_portable --distpath "%DIST%" --workpath "%WORK%_dir" --specpath "%SPEC%" "%SCRIPT%"
exit /b %errorlevel%
