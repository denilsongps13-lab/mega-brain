#!/usr/bin/env bash
set -Eeuo pipefail

echo "=========================================="
echo "      MEGA BRAIN - FINALIZACAO"
echo "=========================================="
echo

ROOT="$(pwd)"
echo "Projeto: $ROOT"

# Confere arquivos esperados sem destruir nada
if [ ! -f "package.json" ] && [ ! -f "requirements.txt" ]; then
  echo "ERRO: execute este arquivo na raiz do projeto Mega Brain."
  exit 1
fi

echo
echo "[1/7] Verificando ferramentas..."
command -v node >/dev/null 2>&1 && echo "Node: $(node --version)" || echo "Node nao encontrado"
command -v npm >/dev/null 2>&1 && echo "npm: $(npm --version)" || echo "npm nao encontrado"
command -v python3 >/dev/null 2>&1 && echo "Python: $(python3 --version)" || echo "Python nao encontrado"
command -v git >/dev/null 2>&1 && echo "Git: $(git --version)" || echo "Git nao encontrado"

echo
echo "[2/7] Protegendo configuracao de API..."
if [ -f ".env" ]; then
  echo ".env existente encontrado. NAO sera alterado."
else
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo ".env criado a partir de .env.example."
    echo "ATENCAO: se sua API estava apenas em Secrets do Codespaces, ela continuara sendo lida do ambiente."
  else
    touch .env
    echo ".env vazio criado."
  fi
fi

# Carrega .env somente se existir; não imprime segredos
if [ -f ".env" ]; then
  set +u
  set -a
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
  set -u
fi

echo
echo "[3/7] Detectando APIs configuradas..."
FOUND=0
for KEY in GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_GENERATIVE_AI_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY YOUTUBE_API_KEY PINECONE_API_KEY HUGGINGFACE_TOKEN; do
  if [ -n "${!KEY:-}" ]; then
    echo "OK: $KEY configurada"
    FOUND=1
  fi
done
if [ "$FOUND" -eq 0 ]; then
  echo "Nenhuma chave foi detectada no ambiente atual."
  echo "Se a chave estiver em Codespaces Secrets, reabra/reconstrua o Codespace e execute novamente."
fi

echo
echo "[4/7] Instalando dependencias Node..."
if [ -f "package-lock.json" ]; then
  npm ci || npm install
elif [ -f "package.json" ]; then
  npm install
else
  echo "package.json nao encontrado; pulando Node."
fi

echo
echo "[5/7] Instalando dependencias Python..."
if [ -f "requirements.txt" ]; then
  python3 -m pip install --user -r requirements.txt || python3 -m pip install -r requirements.txt
else
  echo "requirements.txt nao encontrado; pulando Python."
fi

echo
echo "[6/7] Criando pastas locais esperadas..."
mkdir -p knowledge workspace logs 2>/dev/null || true

echo
echo "[7/7] Executando verificacao final..."
if [ -f "package.json" ] && node -e 'const p=require("./package.json"); process.exit(p.scripts&&p.scripts.check?0:1)' 2>/dev/null; then
  npm run check
else
  echo "Script npm 'check' nao encontrado. Fazendo verificacao basica."
  [ -d "node_modules" ] && echo "OK: node_modules presente" || true
  [ -d "engine" ] && echo "OK: engine presente" || true
  [ -d "agents" ] && echo "OK: agents presente" || true
  [ -d ".claude" ] && echo "OK: .claude presente" || true
fi

echo
echo "------------------------------------------"
echo "Teste opcional da API Gemini/Google"
echo "------------------------------------------"
GKEY="${GEMINI_API_KEY:-${GOOGLE_API_KEY:-${GOOGLE_GENERATIVE_AI_API_KEY:-}}}"
if [ -n "$GKEY" ] && command -v curl >/dev/null 2>&1; then
  HTTP="$(curl -sS -o /tmp/mega_brain_models.json -w "%{http_code}" \
    "https://generativelanguage.googleapis.com/v1beta/models?key=${GKEY}" || true)"
  if [ "$HTTP" = "200" ]; then
    echo "OK: API Gemini/Google respondeu corretamente."
  else
    echo "Aviso: API Gemini/Google respondeu HTTP ${HTTP:-sem resposta}."
    echo "A chave nao foi exibida nem alterada."
  fi
else
  echo "Teste Gemini ignorado (chave nao detectada ou curl indisponivel)."
fi

echo
echo "=========================================="
echo " FINALIZACAO CONCLUIDA"
echo "=========================================="
echo "A configuracao de API existente foi preservada."
echo
echo "Proximos comandos do Mega Brain, conforme o projeto:"
echo "  /ingest <fonte>"
echo "  /process-jarvis"
echo "  /jarvis-briefing"
echo "  /conclave \"sua pergunta\""
echo
