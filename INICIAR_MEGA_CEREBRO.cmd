@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0scripts\start_mega_brain_v2.py" %*
) else (
  python "%~dp0scripts\start_mega_brain_v2.py" %*
)
set "MEGA_RESULT=%ERRORLEVEL%"
if not "%MEGA_RESULT%"=="0" pause
exit /b %MEGA_RESULT%
