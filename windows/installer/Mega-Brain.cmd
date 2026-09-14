@echo off
rem ============================================================
rem  Mega Brain - Windows launcher
rem  Opens the reference-matched animated desktop interface via pythonw.exe.
rem  Falls back to earlier UIs only if the latest entrypoint is missing.
rem  NEVER prints secret values.
rem ============================================================
setlocal
title Mega Brain

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
    echo  Python 3 nao foi encontrado. Rode o instalador do Mega Brain novamente.
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

set "UI=%PAYLOAD%\windows\ui\megabrain-ui-v3.pyw"
if not exist "%UI%" set "UI=%PAYLOAD%\windows\ui\megabrain-ui-v2.pyw"
if not exist "%UI%" set "UI=%PAYLOAD%\windows\ui\megabrain-ui.pyw"
start "" "%PYWEXE%" "%UI%" %*
exit /b 0