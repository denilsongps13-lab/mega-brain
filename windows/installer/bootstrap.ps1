# bootstrap.ps1 - Mega Brain post-install preparation (Windows)
# Safe Windows PowerShell (5.1) compatible. Never prints secrets.
param(
    [Parameter(Mandatory = $true)][string]$AppDir
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$msg) { Write-Host "[Mega Brain] $msg" -ForegroundColor Cyan }
function Write-Err([string]$msg)  { Write-Host "[Mega Brain] ERRO: $msg" -ForegroundColor Red }

function Test-Node {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) {
        Write-Step 'Node.js nao encontrado. Instalando via winget (OpenJS.NodeJS.LTS)...'
        & winget.exe install --id OpenJS.NodeJS.LTS --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw "winget falhou ao instalar Node.js (codigo $LASTEXITCODE)" }
        $nodeDir = Join-Path $env:LOCALAPPDATA 'Programs\nodejs'
        if (Test-Path (Join-Path $nodeDir 'node.exe')) { $env:Path = "$nodeDir;$env:Path" }
        $node = Get-Command node.exe -ErrorAction SilentlyContinue
        if (-not $node) { throw 'Node.js nao foi encontrado apos instalacao via winget.' }
    }
    $ver = (& $node.Source --version 2>&1 | Select-Object -First 1)
    Write-Step "Node.js OK ($ver)"
    return $node.Source
}

function Get-PythonInvoke {
    # Prefer py -3 launcher (never a Windows Store alias).
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $v = (& $py.Source -3 --version 2>&1 | Out-String)
        if ($v -match 'Python 3\.\d+') { return @{ Path = $py.Source; Args = @('-3') } }
    }
    # Fallback: real python/python3 that answer --version. Rejects broken Store aliases.
    foreach ($cand in 'python', 'python3') {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $v = (& $cmd.Source --version 2>&1 | Out-String)
            if ($v -match 'Python 3\.\d+') { return @{ Path = $cmd.Source; Args = @() } }
        } catch { }
    }
    return $null
}

function Test-Python {
    $p = Get-PythonInvoke
    if ($p) {
        $pyArgs = $p.Args
        $ver = (& $p.Path @pyArgs -c "import sys;print(sys.version.split()[0])" 2>&1 | Select-Object -Last 1)
        Write-Step "Python OK ($ver)"
        return $p
    }
    Write-Step 'Python 3 nao encontrado. Instalando via winget (Python.Python.3.13)...'
    & winget.exe install --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "winget falhou ao instalar Python (codigo $LASTEXITCODE)" }
    $pyDir = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313'
    $env:Path = "$pyDir;$(Join-Path $pyDir 'Scripts');$env:Path"
    $p = Get-PythonInvoke
    if (-not $p) { throw 'Python 3 nao foi encontrado apos instalacao via winget.' }
    $pyArgs = $p.Args
    $ver = (& $p.Path @pyArgs -c "import sys;print(sys.version.split()[0])" 2>&1 | Select-Object -Last 1)
    Write-Step "Python OK ($ver)"
    return $p
}

function Ensure-Pip($py) {
    $pyArgs = $py.Args
    & $py.Path @pyArgs -m pip --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'pip ausente - executando ensurepip...'
        & $py.Path @pyArgs -m ensurepip --upgrade 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel ativar o pip.' }
    }
}

function Ensure-LlmPlaceholders($nodeExe) {
    # Appends EMPTY GEMINI_API_KEY=/GROQ_API_KEY= lines when missing. Never
    # overwrites existing values, never prints them.
    $js = @'
const fs = require('fs');
const p = '.env';
let t = fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '';
if (!t.trim()) { t = '# Mega Brain environment (criado pelo instalador)\n'; }
let add = '';
for (const k of ['GEMINI_API_KEY', 'GROQ_API_KEY']) {
  if (!new RegExp('(^|\\n)' + k + '=', 'm').test(t)) {
    add += (add ? '\n' : '') + k + '=';
  }
}
if (add) {
  fs.appendFileSync(p, (t.endsWith('\n') ? '' : '\n') + add + '\n', 'utf8');
}
'@
    & $nodeExe -e $js
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao garantir campos de LLM no .env' }
}

function Main {
    if (-not (Test-Path $AppDir)) { throw "AppDir nao existe: $AppDir" }
    Push-Location $AppDir
    try {
        $nodeExe = Test-Node
        $py = Test-Python
        Ensure-Pip $py

        Write-Step 'Instalando dependencias npm...'
        if (Test-Path 'package-lock.json') {
            & npm.cmd ci --no-fund --no-audit
            if ($LASTEXITCODE -ne 0) { & npm.cmd install --no-fund --no-audit }
        } else {
            & npm.cmd install --no-fund --no-audit
        }
        if ($LASTEXITCODE -ne 0) { throw 'npm install falhou.' }
        Write-Step 'dependencias npm OK'

        Write-Step 'Instalando dependencias Python (requirements.txt)...'
        $pyArgs = $py.Args
        & $py.Path @pyArgs -m pip install --disable-pip-version-check -q -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'pip falhou ao instalar requirements.txt' }
        Write-Step 'requirements.txt OK'

        Write-Step 'Executando setup deterministico (mega-brain setup --yes)...'
        & $nodeExe bin\mega-brain.js setup --yes
        if ($LASTEXITCODE -ne 0) { throw 'mega-brain setup falhou' }
        Write-Step 'setup OK'

        Write-Step 'Garantindo campos GEMINI_API_KEY / GROQ_API_KEY no .env...'
        Ensure-LlmPlaceholders $nodeExe
        Write-Step '.env OK (chaves nunca sao impressas)'

        Write-Step 'Mega Brain instalado com sucesso. Atalhos criados no Menu Iniciar.'
        Write-Host ''
    }
    finally {
        Pop-Location
    }
}

try {
    Main
    exit 0
}
catch {
    Write-Err $_.Exception.Message
    exit 1
}