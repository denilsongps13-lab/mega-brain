# Auditoria — Mega Cérebro app

Base: `5ff1a0459680eeb1521e45024b2d7f97706a76e8`, main em 20/09/2026.
Branch: `feat/mega-cerebro-app`. Nenhuma branch antiga removida.

| Capacidade | Implementação existente | Integração |
| --- | --- | --- |
| Execução | engine/executor/executor.py, planner.py, validate.py | TaskExecutor + phase_observer; ferramentas adaptadas para execução web |
| Modelos | engine/intelligence/pipeline/mce/llm_router.py | LLMRouter.stream_prompt, preservando fallback |
| Memória de projeto | engine/executor/memory.py | ProjectMemory, sem migração |
| RAG | engine/intelligence/rag/chunker.py, hybrid_index.py | split_text, Chunk, HybridIndex/BM25; índice do app separado |
| Documentos | engine/intelligence/pipeline/extractors | extract_pdf, extract_docx |
| Agentes | agents/_registry/ecosystem-registry.yaml, squads | catálogo real; placeholders identificados |
| Desktop | bin e windows | preservados; nova interface independente |
| Voice/JARVIS | engine/jarvis/voice | legado não importado pela API; não necessário ao MVP |

Não há API de aplicativo FastAPI/Next.js na main. As árvores das branches
animated-brain-exec-diagnostics e mega-brain-v7-commercial também não contêm
uma implementação Next.js/FastAPI reaproveitável. A main já inclui estabilização
pré-app e interface desktop.

Achados: ScopedTools.read não consulta o bloqueio de segredos; search pode ler
arquivos sensíveis; allowlist de executáveis permite Python/Node arbitrários;
verificação git sem subcomando pode falhar. A superfície web precisa restringir
arquivos e usar isolamento de processo/container para comandos.

Limites reais: Gemini simula streaming sobre resultado completo no próprio
router. Catálogo de agentes inclui placeholders. TaskExecutor usa plano estático
curto, não delega automaticamente ao catálogo de squads e não replana com o
conteúdo retornado por cada ferramenta. Não apresentar essa capacidade como
orquestração geral de múltiplos agentes. Lint legado já era não bloqueante no CI.

Arquitetura: Next.js (export estático, React/TS/Tailwind/PWA) → mesma origem
Nginx → FastAPI → adaptadores → engine existente. PostgreSQL armazena dados do
app; memória e RAG permanecem em arquivos. Um processo API, fila limitada e
workers canceláveis por subprocesso. Evolução multiusuário exige autenticação
por usuário e ownership; MVP é instalação privada de operador único.
