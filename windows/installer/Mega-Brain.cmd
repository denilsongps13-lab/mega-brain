@echo off
rem ============================================================
rem  Mega Brain - Windows launcher
rem  Opens the desktop interface (tkinter GUI) via pythonw.exe so
rem  no console window stays open. Pair with the "Mega Brain"
rem  shortcut or run directly.
rem  NEVER prints secret values.
rem ============================================================
setlocal
title Mega Brain

rem ------------------------------------------------------------
rem 1) Identify the payload directory (this cmd lives in {app},
rem    next to the mega-brain payload folder).
rem ------------------------------------------------------------
set "PAYLOAD=%~dp0mega-brain"
if not exist "%PAYLOAD%\" (
    echo.
    echo  Nao encontrei a pasta do Mega Brain em:
    echo    %PAYLOAD%
    echo  A instalacao pode estar corrompida. Reinstale o Mega Brain.
    echo.
    pause
    exit /b 1
)
cd /d "%PAYLOAD%"

rem ------------------------------------------------------------
rem 2) Resolve python.exe via the py launcher (used by bootstrap)
rem    and derive pythonw.exe from it (same folder).
rem ------------------------------------------------------------
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
    echo.
    echo  Python 3 nao foi encontrado. Rode o instalador do Mega Brain
    echo  novamente para instalar as dependencias.
    echo.
    pause
    exit /b 1
)

set "PYWEXE="
if /i not "%PYEXE:~-7%"=="pythonw" (
    for %%X in ("%PYEXE%") do (
        if exist "%%~dpXpythonw.exe" set "PYWEXE=%%~dpXpythonw.exe"
    )
)
if not defined PYWEXE set "PYWEXE=%PYEXE%"

rem ------------------------------------------------------------
rem 3) Launch the desktop interface.
rem    Default: GUI. Extra args (e.g. --selftest) pass through.
rem ------------------------------------------------------------
start "" "%PYWEXE%" "%~dp0mega-brain\windows\ui\megabrain-ui.pyw" %*
exit /b 0