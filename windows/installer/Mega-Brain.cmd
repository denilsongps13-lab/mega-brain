@echo off
rem Mega Brain - one-command Windows launcher.
rem Default: local LiteLLM gateway + Claude Code.
rem Optional: mega-brain gui  -> desktop interface.
setlocal
title Mega Brain

set "PAYLOAD=%~dp0mega-brain"
if not exist "%PAYLOAD%\" (
    echo.
    echo  Nao encontrei a pasta do Mega Brain em:
    echo    %PAYLOAD%
    echo  Reinstale o Mega Brain.
    echo.
    pause
    exit /b 1
)

if /I "%~1"=="gui" goto GUI

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PAYLOAD%\windows\installer\mega-brain-cli.ps1" %*
exit /b %ERRORLEVEL%

:GUI
set "PYEXE="
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)"') do set "PYEXE=%%P"
)
if not defined PYEXE (
    where python >nul 2>&1
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
    echo Python 3 nao encontrado. Reinstale o Mega Brain.
    pause
    exit /b 1
)
set "PYWEXE="
for %%X in ("%PYEXE%") do if exist "%%~dpXpythonw.exe" set "PYWEXE=%%~dpXpythonw.exe"
if not defined PYWEXE set "PYWEXE=%PYEXE%"
start "" "%PYWEXE%" "%PAYLOAD%\windows\ui\megabrain-ui.pyw"
exit /b 0
