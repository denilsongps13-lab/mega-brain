# bootstrap.ps1 - Mega Brain post-install preparation (Windows)
# Windows PowerShell 5.1 compatible. Never prints secrets.
param(
    [Parameter(Mandatory = $true)][string]$AppDir
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$msg) { Write-Host "[Mega Brain] $msg" -ForegroundColor Cyan }
function Write-Err([string]$msg)  { Write-Host "[Mega Brain] ERRO: $msg" -ForegroundColor Red }

function Require-Winget {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { throw 'winget nao encontrado. Atualize o App Installer da Microsoft Store e execute o instalador novamente.' }
    return $winget.Source
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Test-Node {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) {
        $winget = Require-Winget
        Write-Step 'Node.js nao encontrado. Instalando Node.js LTS...'
        & $winget install --id OpenJS.NodeJS.LTS --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw "winget falhou ao instalar Node.js (codigo $LASTEXITCODE)" }
        Refresh-Path
        $node = Get-Command node.exe -ErrorAction SilentlyContinue
        if (-not $node) { throw 'Node.js nao foi encontrado apos a instalacao.' }
    }
    $ver = (& $node.Source --version 2>&1 | Select-Object -First 1)
    Write-Step "Node.js OK ($ver)"
    return $node.Source
}

function Get-PythonInvoke {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $v = (& $py.Source -3 --version 2>&1 | Out-String)
            if ($v -match 'Python 3\.\d+') { return @{ Path = $py.Source; Args = @('-3') } }
        } catch { }
    }
    foreach ($cand in 'python.exe', 'python3.exe', 'python', 'python3') {
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
    if (-not $p) {
        $winget = Require-Winget
        Write-Step 'Python 3 nao encontrado. Instalando Python 3.13...'
        & $winget install --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw "winget falhou ao instalar Python (codigo $LASTEXITCODE)" }
        Refresh-Path
        $p = Get-PythonInvoke
        if (-not $p) { throw 'Python 3 nao foi encontrado apos a instalacao.' }
    }
    $ver = (& $p.Path @($p.Args) -c "import sys;print(sys.version.split()[0])" 2>&1 | Select-Object -Last 1)
    Write-Step "Python OK ($ver)"
    return $p
}

function Ensure-Pip($py) {
    & $py.Path @($py.Args) -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'Ativando pip...'
        & $py.Path @($py.Args) -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel ativar o pip.' }
    }
}

function Ensure-LlmPlaceholders($nodeExe) {
    $js = @'
const fs = require('fs');
const p = '.env';
let t = fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '';
if (!t.trim()) t = '# Mega Brain environment (criado pelo instalador)\n';
let add = '';
for (const k of ['GEMINI_API_KEY', 'GROQ_API_KEY', 'MEGA_BRAIN_PRIMARY_MODEL', 'MEGA_BRAIN_FALLBACK_MODEL']) {
  if (!new RegExp('(^|\\n)' + k + '=', 'm').test(t)) add += (add ? '\n' : '') + k + '=';
}
if (add) fs.appendFileSync(p, (t.endsWith('\n') ? '' : '\n') + add + '\n', 'utf8');
'@
    & $nodeExe -e $js
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar .env.' }
}

function Install-ClaudeCode {
    $claude = Get-Command claude.cmd -ErrorAction SilentlyContinue
    if ($claude) {
        Write-Step 'Claude Code ja instalado.'
        return
    }
    Write-Step 'Instalando Claude Code...'
    & npm.cmd install -g @anthropic-ai/claude-code --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) {
        throw 'Falha ao instalar Claude Code pelo npm.'
    }
    Refresh-Path
    $claude = Get-Command claude.cmd -ErrorAction SilentlyContinue
    if (-not $claude) {
        Write-Step 'Claude Code instalado; o comando ficara disponivel em novas janelas do terminal.'
    } else {
        Write-Step 'Claude Code OK.'
    }
}

function Install-LiteLlm($py) {
    Write-Step 'Instalando/atualizando LiteLLM Proxy...'
    & $py.Path @($py.Args) -m pip install --disable-pip-version-check -q --upgrade "litellm[proxy]"
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar LiteLLM Proxy.' }
    & $py.Path @($py.Args) -c "import litellm; print('LiteLLM OK')"
    if ($LASTEXITCODE -ne 0) { throw 'LiteLLM instalado, mas nao foi possivel importa-lo.' }
}

function Main {
    if (-not (Test-Path $AppDir)) { throw "AppDir nao existe: $AppDir" }
    Push-Location $AppDir
    try {
        $nodeExe = Test-Node
        $py = Test-Python
        Ensure-Pip $py

        Write-Step 'Instalando dependencias npm do Mega Brain...'
        if (Test-Path 'package-lock.json') {
            & npm.cmd ci --no-fund --no-audit
            if ($LASTEXITCODE -ne 0) { & npm.cmd install --no-fund --no-audit }
        } else {
            & npm.cmd install --no-fund --no-audit
        }
        if ($LASTEXITCODE -ne 0) { throw 'npm install falhou.' }

        Write-Step 'Instalando dependencias Python do Mega Brain...'
        & $py.Path @($py.Args) -m pip install --disable-pip-version-check -q -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'pip falhou ao instalar requirements.txt.' }

        Install-LiteLlm $py
        Install-ClaudeCode

        Write-Step 'Executando setup do Mega Brain...'
        & $nodeExe bin\mega-brain.js setup --yes
        if ($LASTEXITCODE -ne 0) { throw 'mega-brain setup falhou.' }

        Ensure-LlmPlaceholders $nodeExe
        Write-Step 'Configuracao concluida. As chaves serao solicitadas no primeiro uso e nunca sao exibidas.'
    }
    finally { Pop-Location }
}

try {
    Main
    Write-Step 'Mega Brain instalado com sucesso.'
    exit 0
}
catch {
    Write-Err $_.Exception.Message
    exit 1
}
