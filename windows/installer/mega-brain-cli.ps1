# Mega Brain one-command launcher for Windows.
# Starts a local LiteLLM Anthropic-compatible gateway and then Claude Code.
# Secrets are read from .env and are never printed.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ClaudeArgs
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root
$EnvFile = Join-Path $Root '.env'
$RuntimeDir = Join-Path $env:LOCALAPPDATA 'MegaBrain\runtime'
$ConfigFile = Join-Path $RuntimeDir 'litellm.generated.yaml'
$Port = 4141

function Write-Step([string]$Text) { Write-Host "[Mega Brain] $Text" -ForegroundColor Cyan }
function Write-Fail([string]$Text) { Write-Host "[Mega Brain] ERRO: $Text" -ForegroundColor Red }

function Get-Python {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        try {
            & $py.Source -3 -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return @{ Path = $py.Source; Args = @('-3') } }
        } catch { }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { return @{ Path = $python.Source; Args = @() } }
    throw 'Python 3 nao encontrado. Reinstale o Mega Brain.'
}

function Import-DotEnv {
    if (-not (Test-Path $EnvFile)) { return }
    foreach ($line in Get-Content -LiteralPath $EnvFile -ErrorAction SilentlyContinue) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith('#') -or -not $trim.Contains('=')) { continue }
        $parts = $trim.Split('=', 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}

function Set-DotEnvValue([string]$Name, [string]$Value) {
    $lines = @()
    if (Test-Path $EnvFile) { $lines = @(Get-Content -LiteralPath $EnvFile) }
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^' + [regex]::Escape($Name) + '=')) {
            $lines[$i] = "$Name=$Value"
            $updated = $true
            break
        }
    }
    if (-not $updated) { $lines += "$Name=$Value" }
    Set-Content -LiteralPath $EnvFile -Value $lines -Encoding UTF8
    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
}

function Read-Secret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Ensure-Keys {
    if (-not $env:GEMINI_API_KEY) {
        Write-Host ''
        Write-Host 'Primeira configuracao: sua chave Gemini e necessaria.' -ForegroundColor Yellow
        $gemini = Read-Secret 'Cole a GEMINI_API_KEY (o valor ficara oculto)'
        if (-not $gemini) { throw 'GEMINI_API_KEY nao informada.' }
        Set-DotEnvValue 'GEMINI_API_KEY' $gemini
    }
    if (-not $env:GROQ_API_KEY) {
        Write-Host ''
        Write-Host 'Opcional: adicione GROQ_API_KEY para fallback automatico.' -ForegroundColor Yellow
        $groq = Read-Secret 'Cole a GROQ_API_KEY ou pressione Enter para pular'
        if ($groq) { Set-DotEnvValue 'GROQ_API_KEY' $groq }
    }
}

function Escape-YamlDoubleQuoted([string]$Value) {
    if ($Value -match '[\r\n]') { throw 'Nome de modelo invalido.' }
    return $Value.Replace('\\', '\\\\').Replace('"', '\"')
}

function Write-LiteLlmConfig {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    $primary = if ($env:MEGA_BRAIN_PRIMARY_MODEL) { $env:MEGA_BRAIN_PRIMARY_MODEL } else { 'gemini/gemini-2.5-flash' }
    $fallback = if ($env:MEGA_BRAIN_FALLBACK_MODEL) { $env:MEGA_BRAIN_FALLBACK_MODEL } else { 'groq/openai/gpt-oss-120b' }
    $p = Escape-YamlDoubleQuoted $primary
    $f = Escape-YamlDoubleQuoted $fallback

    $fallbackBlock = ''
    if ($env:GROQ_API_KEY) {
        $fallbackBlock = @"
  - model_name: mega-brain-fallback
    litellm_params:
      model: "$f"
      api_key: os.environ/GROQ_API_KEY
"@
    }

    $fallbackRouter = ''
    if ($env:GROQ_API_KEY) {
        $fallbackRouter = @"
  fallbacks:
    - mega-brain-primary: ["mega-brain-fallback"]
"@
    }

    $yaml = @"
model_list:
  - model_name: mega-brain-primary
    litellm_params:
      model: "$p"
      api_key: os.environ/GEMINI_API_KEY
$fallbackBlock
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 0
  retry_after: 0
  allowed_fails: 0
  cooldown_time: 0
  disable_cooldowns: true
$fallbackRouter
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
litellm_settings:
  drop_params: true
  request_timeout: 600
"@
    Set-Content -LiteralPath $ConfigFile -Value $yaml -Encoding UTF8
}

function Test-Port([int]$TcpPort) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', $TcpPort, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(250)
        if ($ok -and $client.Connected) { $client.EndConnect($iar); $client.Close(); return $true }
        $client.Close()
    } catch { }
    return $false
}

function Find-ClaudeCommand {
    foreach ($name in @('claude.exe', 'claude.cmd', 'claude')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return @{ Path = $cmd.Source; Prefix = @() } }
    }
    $npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
    if ($npx) { return @{ Path = $npx.Source; Prefix = @('-y', '@anthropic-ai/claude-code') } }
    throw 'Claude Code nao encontrado e npx indisponivel. Reinstale o Mega Brain.'
}

$proxy = $null
try {
    Import-DotEnv
    Ensure-Keys
    $py = Get-Python

    # Unique local-only gateway token; never persisted.
    $env:LITELLM_MASTER_KEY = 'mb-' + [guid]::NewGuid().ToString('N')
    Write-LiteLlmConfig

    if (Test-Port $Port) {
        throw "A porta local $Port ja esta em uso. Feche outra instancia do Mega Brain e tente novamente."
    }

    Write-Step 'Iniciando gateway local Gemini -> Groq...'
    $pyArgs = @($py.Args) + @('-m', 'litellm', '--config', $ConfigFile, '--host', '127.0.0.1', '--port', "$Port")
    $proxy = Start-Process -FilePath $py.Path -ArgumentList $pyArgs -WindowStyle Hidden -PassThru

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if ($proxy.HasExited) { throw "LiteLLM encerrou antes de iniciar (codigo $($proxy.ExitCode))." }
        if (Test-Port $Port) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'LiteLLM nao ficou pronto em 30 segundos.' }

    $env:ANTHROPIC_BASE_URL = "http://127.0.0.1:$Port"
    $env:ANTHROPIC_AUTH_TOKEN = $env:LITELLM_MASTER_KEY
    $env:ANTHROPIC_API_KEY = $env:LITELLM_MASTER_KEY
    $env:ANTHROPIC_DEFAULT_SONNET_MODEL = 'mega-brain-primary'
    $env:ANTHROPIC_DEFAULT_OPUS_MODEL = 'mega-brain-primary'
    $env:ANTHROPIC_DEFAULT_HAIKU_MODEL = 'mega-brain-primary'
    $env:DISABLE_AUTOUPDATER = '1'

    $claude = Find-ClaudeCommand
    Write-Step 'Gateway pronto. Abrindo Claude Code...'
    & $claude.Path @($claude.Prefix) @ClaudeArgs
    exit $LASTEXITCODE
}
catch {
    Write-Fail $_.Exception.Message
    Write-Host ''
    Write-Host 'Pressione Enter para fechar.' -ForegroundColor DarkGray
    [void](Read-Host)
    exit 1
}
finally {
    if ($proxy -and -not $proxy.HasExited) {
        try { Stop-Process -Id $proxy.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
}
