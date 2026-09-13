# Mega Cérebro — Windows, Gemini e Groq

Extraia o ZIP e abra `INSTALAR_MEGA_CEREBRO.cmd`. Se necessário, selecione a
pasta existente do projeto que contém `.claude`. O instalador atualiza somente
os arquivos da correção e abre o sistema. Depois, use `INICIAR_MEGA_CEREBRO.cmd`
nessa pasta. Feche o Claude para encerrar a ponte criada por esta sessão.

Seu `.env` é preservado e nunca entra no pacote nem nos backups. Os arquivos de
estado existentes também são preservados. Cada substituição tem backup em
`.data/mega-brain/installer-backups`; os settings têm backup separado antes de
alterar apenas comandos de hooks reconhecidos. Agents, skills, rules, commands,
permissions e hooks personalizados permanecem intactos. Este é um atualizador
para o projeto existente, não uma cópia vazia do Mega Cérebro.

Requer Python 3.13, Node.js, Git Bash, Claude Code e LiteLLM **1.100.1** com
extras proxy já instalados. O launcher lê as duas credenciais apenas no `.env`
local ao iniciar. Nenhuma credencial de provedor é passada ao processo Claude.
A autenticação Claude → LiteLLM usa um token local aleatório por sessão.

Gemini `gemini/gemini-3.6-flash` permanece principal. Em limite local, HTTP 429,
timeout ou indisponibilidade, a requisição segue para Groq
`openai/gpt-oss-120b`. Usa a API oficial Groq compatível com OpenAI
(`https://api.groq.com/openai/v1`); não usa a API nem credenciais da OpenAI.
Essa via evita a falha de `service_tier` opcional do adaptador Groq no LiteLLM
1.100.1. Referência: https://console.groq.com/docs/openai

Não há limitador local de RPM nem cooldown artificial. Gemini é tentado primeiro
em cada nova requisição. HTTP 429/503 ou indisponibilidade acionam Groq na mesma
requisição. Quando Gemini volta a responder, ele já é usado na próxima chamada.
A sexta chamada não é bloqueada localmente; as cotas são aplicadas pelos provedores.
O módulo legado de limite permanece disponível para compatibilidade, mas não é
carregado pelo launcher. O Router também tem seu cooldown padrão desativado.
Retries estão desativados e há somente um destino de fallback. Se ambos falham,
a requisição termina com erro. Não há sondagens periódicas nem inferência na
inicialização. Streaming que já entregou conteúdo não é reiniciado em outro
provedor: isso evita duplicação de texto e ferramentas.

O fallback tem contexto/capacidades próprios ; não há corte
silencioso de histórico para forçar uma chamada incompatível. O fallback não
transforma o limite de uma conta Groq em capacidade ilimitada.

Para o único teste com suas credenciais reais, abra `TESTAR_MEGA_CEREBRO.cmd`.
Ele faz uma solicitação curta pelo Claude com os hooks ativos, sem imprimir
corpos de erro dos provedores. Os testes de desenvolvimento usam somente
credenciais sintéticas e servidores locais.

## Estados verificados no código

- `system/REGISTRY/BATCH-HISTORY.json`: `health_scorer.py` e
  `.claude/commands/process-jarvis.md` leem `batches` como lista, incluindo
  timestamps e métricas por batch. A lista vazia é baseline válido, não um
  processamento concluído. O instalador nunca substitui histórico existente.
- `system/REGISTRY/INSIGHTS-STATE.json`: não há consumidor de runtime para esse
  caminho nesta árvore; a versão anterior era um placeholder. O template agora
  segue o esqueleto de `_load_insights_state` em `pipeline/mce/orchestrate.py`
  (`persons`, `themes`, `version`, `change_log`, `contradictions`, metadados).
  Os dados reais ficam em `.data/artifacts/insights/`, normalmente por slug.
  O schema legado exige envelope `insights_state`, enquanto o writer moderno
  salva diretamente o objeto; o loader aceita ambos. Não copiamos/migramos
  dados do usuário para um caminho presumido. O template adiciona
  `total_insights: 0` para compatibilidade com o health scorer.

## Validação desta distribuição

Test/Validate/Quality Gate referenciavam `pyproject.toml`, `tests/python`,
`tests/e2e` e validadores capability/provenance/UAE ausentes deste checkout.
Foram conectados aos testes disponíveis e novos contratos reais do launcher,
Router, rate limit e instalador. Isso não certifica funcionalidades enterprise
que não estão publicadas neste repositório. Os checks JSON/YAML e gitleaks
foram preservados. O lint geral continua informativo para a dívida preexistente;
a compilação Python é bloqueante, com dois erros de sintaxe corrigidos em Vapi.
