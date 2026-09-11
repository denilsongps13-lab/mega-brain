# Nexora + OpenWA

Ponte de integracao entre o WhatsApp (OpenWA) e o Mega Brain para atendimento comercial da Nexora.

## Fluxo inicial

1. OpenWA recebe um evento `message.received`.
2. O webhook envia somente os dados necessarios para a ponte Nexora.
3. A ponte valida o evento e encaminha a mensagem para o Mega Brain/LLM.
4. A resposta volta pela API do OpenWA.
5. Contatos com opt-out (`SAIR`, `PARAR`, `CANCELAR`) nao recebem novas promocoes.

## Configuracao esperada

```env
OPENWA_BASE_URL=http://openwa:2785
OPENWA_API_KEY=troque-por-um-segredo-forte
OPENWA_SESSION=nexora
NEXORA_WEBHOOK_SECRET=troque-por-um-segredo-forte
```

Nunca versionar chaves reais no GitHub.

## Proximo passo de execucao

Subir o OpenWA em um host com Docker e armazenamento persistente para a sessao do WhatsApp. Depois, iniciar a sessao `nexora`, escanear o QR Code e registrar o webhook da ponte.
