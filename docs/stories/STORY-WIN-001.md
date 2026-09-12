# STORY-WIN-001 — Inicialização Windows com Gemini

Problema: Claude Code chega a reconhecer o modelo, mas recebe 401; hooks
invocam `bash` fora do PATH no Windows. O teste direto anterior não prova
que o cliente usa o mesmo token ou o endpoint Anthropic.

Critérios:
- Preservar agents, commands, skills, rules, hooks e permissões.
- Converter somente comandos conhecidos; backup byte a byte antes de editar.
- Separar chave Gemini (somente no processo proxy) e token da ponte.
- Escutar somente em 127.0.0.1; nunca matar ou reutilizar serviço desconhecido.
- Testar `/v1/messages`, streaming e cliente, sem mostrar respostas de erro.
- Inicializar por duplo clique e encerrar apenas a ponte criada pelo iniciador.

Validação local: testes de regressão sem credenciais. Validação nativa Windows
agendada pelo workflow `windows-launcher.yml` ao abrir PR. Teste real Gemini
exige execução local; nenhuma chave foi fornecida ao autor da correção.

Limitação encontrada na base: os módulos
`mega-brain-core/core/synapse/runtime/hook-runtime.js` e
`mega-brain-core/hooks/unified/runners/precompact-runner.js` não estão no
repositório. Não foram inventados substitutos nem removidos os hooks.
O iniciador alerta; `--test` não declara validação completa se faltarem.
