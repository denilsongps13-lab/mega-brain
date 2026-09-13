# Mega Cérebro no Windows

O pacote atual é `windows/INSTALAR_MEGA_CEREBRO_FINAL.zip`.
Extraia e abra `INSTALAR_MEGA_CEREBRO.cmd` para atualizar o projeto existente
com backup e preservação do `.env` e estados locais. Depois use
`INICIAR_MEGA_CEREBRO.cmd` na pasta do projeto.

A documentação completa está em [LEIA_ME_FINAL](../windows/LEIA_ME_FINAL.md),
incluindo Gemini principal, Groq de fallback, failover definido pelos provedores, requisitos,
backups e alcance dos testes. A inicialização normal não faz inferência de teste.
`TESTAR_MEGA_CEREBRO.cmd` solicita apenas uma resposta curta pelo Claude.

Os dois módulos referenciados pelos hooks já estão presentes nesta branch:
`mega-brain-core/core/synapse/runtime/hook-runtime.js` e
`mega-brain-core/hooks/unified/runners/precompact-runner.js`.
Esta atualização preserva esses adaptadores e os hooks existentes; a presença
deles não certifica todos os recursos opcionais da distribuição original.
