# Mega Cérebro no Windows

O iniciador usa o modelo informado como já testado pelo usuário:
`gemini/gemini-3.6-flash`. Não troca o modelo nem requer publicar a chave.

## Instalar na pasta existente

Baixe `windows/INSTALAR_MEGA_CEREBRO.zip`, extraia e abra
`INSTALAR_MEGA_CEREBRO.cmd`. Ele procura a pasta existente na Área de Trabalho;
se não encontrar, abre um seletor. Copia somente os quatro arquivos da correção,
faz backup de versões anteriores e abre o iniciador. Não baixa dependências,
não substitui o projeto e não modifica `.env`.

Depois, abra `INICIAR_MEGA_CEREBRO.cmd` dentro do projeto. Para testar e encerrar,
abra `TESTAR_MEGA_CEREBRO.cmd`. O teste usa a API Gemini e pode consumir cota.
O primeiro uso do Claude pode pedir confiança na pasta: aceite na interface local.

Pré-requisitos: Python 3 com `litellm[proxy]`, Node.js, Git for Windows e Claude
Code instalados. Use o mesmo Python em que o LiteLLM já funciona. O iniciador
prefere `py -3` e, se não existir, `python`. Não instala ou atualiza nada sozinho.

## O que é preservado

O instalador não traz um `settings.json` substituto. O iniciador lê os JSONs atuais
`settings.json` e `settings.local.json`, reconhece apenas os comandos originais
para scripts em `.claude/hooks`, e altera somente o campo `command` desses hooks.
Mantém número, ordem, eventos, filtros, timeouts, campos desconhecidos e comandos
personalizados. Arquivos JSON inválidos interrompem a operação antes da escrita.
Backups originais ficam em `.data/mega-brain/backups/<data-id>/`.
Comandos resultantes têm caminhos absolutos locais para funcionar mesmo após `cd`;
não envie esses settings locais modificados para o GitHub. O repositório mantém
sua configuração original. Se mover a pasta, o iniciador recalcula os caminhos.

O ambiente de conexão é aplicado via arquivo temporário `--settings`, sem hooks
ou permissões, mantendo os settings normais carregados. O token aleatório da
ponte fica nesse arquivo temporário e na memória dos processos; a chave Gemini
fica somente no ambiente do LiteLLM. A origem continua sendo `.env`, lido sem
interpolação, e as três variantes GEMINI_API_KEY, GOOGLE_API_KEY e
GOOGLE_GENERATIVE_AI_API_KEY são aceitas. Nunca imprime valores.

Configurações gerenciadas pela organização continuam tendo prioridade. O
iniciador não altera políticas, permissões ou o login salvo do Claude.

## Arquivos e conexões

| Arquivo desde a raiz | Função e conteúdo | Acionado por / conexão | Se ausente |
|---|---|---|---|
| `INICIAR_MEGA_CEREBRO.cmd` | Entrada Windows, texto batch | Duplo clique → Python | Sem atalho de início |
| `TESTAR_MEGA_CEREBRO.cmd` | Entrada para teste completo | Duplo clique → iniciador `--test` | Sem atalho de teste |
| `scripts/start_mega_brain.py` | Backup, migração pontual, ambiente, ciclo de vida e diagnóstico | Batch → LiteLLM e Claude | Ponte não inicializa |
| `.claude/hooks/run-hook.cjs` | Executor Node que preserva entrada, saída e código de retorno | Hooks → Python, Bash ou Node | Hooks migrados não executam |
| `tests/test_windows_launcher.py` | Testes sem credenciais | Unittest / GitHub Actions | Sem regressão automatizada |
| `scripts/build_windows_installer.py` | Gera pacote de instalação a partir dos fontes | Mantenedor → ZIP | Não regenera o instalador |

O iniciador funciona como uma recepção: prepara os acessos e chama os serviços;
os agentes e regras existentes continuam sendo os responsáveis pelo trabalho.
Python recebe diretamente hooks `.py`; Git Bash é usado para os quatro hooks
`.sh`, com sua localização descoberta automaticamente. Node recebe os `.js`.
Não há supressão de erros ou conversão de bloqueios em sucesso no executor.

A conexão é Claude Code → LiteLLM em 127.0.0.1 → Gemini. O token de acesso à
ponte coincide nos dois primeiros processos. A credencial Gemini é diferente.
A porta preferida é 4000; se ocupada, tenta 4001–4020 sem encerrar o serviço
existente. Ao sair, encerra somente o processo que criou e apaga arquivos
temporários. Se o Windows for desligado abruptamente, podem restar temporários
em `.data/mega-brain/runtime/`; eles contêm apenas token de uma ponte já encerrada,
nunca a chave Gemini. Nenhum log bruto do proxy é salvo.

## Verificação e limites

O início normal verifica Messages API e streaming antes de abrir Claude. O modo
`--test` também pede uma resposta curta ao próprio Claude, com hooks mantidos.
Isso valida uma troca de texto; não certifica todas as ferramentas, agentes,
pipelines ou chamadas paralelas. Não é um teste completo do produto.

Esta base tem dois módulos faltantes de `mega-brain-core`, usados por Synapse e
PreCompact. O iniciador informa a falta; não desativa esses hooks nem inventa o
núcleo. Para esses recursos funcionarem integralmente, é necessário restaurar os
módulos da distribuição original. O teste completo não informa sucesso enquanto
eles estiverem ausentes. O `--check` faz somente preflight, sem chamar Gemini.

Restaurar hooks: feche o Claude, copie os dois JSONs do backup desejado de volta
para `.claude/` (somente aqueles que existiam) e inicie pelo comando anterior.
Para remover os quatro arquivos novos, consulte também o manifesto do instalador
em `.data/mega-brain/installer-backups/`. O `.env` nunca entra nesse backup.

Referências: [LiteLLM com Claude e Gemini](https://docs.litellm.ai/docs/tutorials/claude_non_anthropic_models),
[Git Bash no Windows](https://code.claude.com/docs/en/setup),
[precedência dos settings](https://code.claude.com/docs/en/settings).
Integração oferecida pelo LiteLLM; Anthropic não dá suporte a modelos não Claude.
