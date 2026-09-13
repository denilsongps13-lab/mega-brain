---
description: Executa uma missao autonomamente com planejamento, ferramentas, verificacao e autocorrecao controlada
argument-hint: [missao] - Ex: "corrija o fallback Gemini para Groq e valide o fluxo"
---

# /execute - Executor Autonomo

## Uso
```text
/execute [missao]
```

## Objetivo
Delegar uma tarefa executavel ao agente `mega-brain--executor`, que deve trabalhar ate concluir ou encontrar um bloqueio real.

## Instrucoes

1. Trate `$ARGUMENTS` como a missao integral.
2. Invoque o agente `mega-brain--executor` com a missao recebida.
3. Nao transforme a execucao em apenas um tutorial: quando houver ferramentas e permissoes adequadas, execute as alteracoes.
4. Antes de alterar codigo, inspecione os arquivos diretamente relacionados.
5. Depois de alterar codigo, valide o resultado com o mecanismo mais forte disponivel: testes, lint, compilacao, execucao controlada, diff ou releitura.
6. Nao exponha credenciais e nao leia `.env` se a tarefa nao exigir explicitamente isso.
7. Nao repita indefinidamente uma falha. Use no maximo 3 tentativas de correcao para a mesma causa.
8. Se houver bloqueio externo, pare e informe exatamente o que bloqueou a conclusao.

## Saida obrigatoria
```text
STATUS: concluido | bloqueado | falhou
ALTERACOES:
- ...
VERIFICACOES:
- ...
PENDENCIAS:
- ...
```
