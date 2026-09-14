@echo off
rem ============================================================
rem  Mega Brain - Windows launcher
rem  Runs the runtime status, preflight and LLM key state.
rem  NEVER prints secret values.
rem ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0mega-brain"

where node >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Node.js nao encontrado no PATH. Instale Node.js e tente novamente.
    echo.
    pause
    exit /b 1
)

title Mega Brain
echo.
echo  ==========================================================
echo   Mega Brain - Runtime
echo  ==========================================================
echo.
node bin\mega-brain.js start
if errorlevel 1 (
    echo.
    echo  Falha ao iniciar o runtime. Use:  node bin\mega-brain.js setup
    echo.
    pause
    exit /b 1
)

echo.
echo  ==========================================================
echo   Mega Brain - Preflight
echo  ==========================================================
echo.
node bin\mega-brain.js preflight
if errorlevel 1 (
    echo.
    echo  Preflight falhou. Rode  node bin\mega-brain.js setup  e repita.
    echo.
    pause
    exit /b 1
)

echo.
echo  ==========================================================
echo   Configuracao dos provedores de IA
echo  ==========================================================
node -e "try{const fs=require('fs');const p='.env';const has=fs.existsSync(p);const t=has?fs.readFileSync(p,'utf8'):'';const get=k=>{const re=new RegExp('^'+k+'=(.*)$','m');const m=t.match(re);return !!(m&&m[1]&&m[1].trim())};if(!has){console.log('  Gemini: nao configurado');console.log('  Groq:   nao configurado');}else{console.log('  Gemini: '+(get('GEMINI_API_KEY')?'configurado':'nao configurado'));console.log('  Groq:   '+(get('GROQ_API_KEY')?'configurado':'nao configurado'));}}catch(e){console.log('  (nao foi possivel ler .env)')}"
echo.
echo  Dica: edite o arquivo .env (em maos) para adicionar as chaves
echo  GEMINI_API_KEY e GROQ_API_KEY, depois rode:  node bin\mega-brain.js setup
echo.
pause