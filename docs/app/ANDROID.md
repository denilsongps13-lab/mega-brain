# Mega Cérebro — Android

A versão Android reutiliza o mesmo frontend Next.js exportado estaticamente e o empacota com Capacitor 8. O engine Python, o PostgreSQL, o RAG, a memória e as chaves dos provedores continuam no servidor.

## Arquitetura

Android (Capacitor/WebView) → HTTPS/WSS → FastAPI → engine Mega Cérebro.

Nenhuma chave de Gemini, Groq, Anthropic ou OpenAI é colocada no APK.

## Primeiro acesso

No Android, informe:

1. **Servidor do Mega Cérebro** — URL HTTPS pública ou privada do backend, por exemplo `https://mega.exemplo.com`.
2. **Token de acesso da instalação** — valor de `APP_ACCESS_TOKEN`.

O endereço do servidor fica salvo localmente no dispositivo. O token continua apenas na sessão atual e é removido ao recarregar/sair.

Para desenvolvimento em rede local, a interface aceita endereços HTTP em faixas privadas 10.x, 172.x e 192.168.x, mas produção deve usar HTTPS.

## CORS / WebSocket

O backend aceita os origins nativos esperados (`https://localhost` e `capacitor://localhost`) além das origens web configuradas. Não use `*` em produção.

## Build local

Primeiro gere o frontend:

```bash
cd apps/web
npm ci
npm run build
```

Depois:

```bash
cd ../mobile
npm install
npx cap add android
npx cap sync android
cd android
./gradlew assembleDebug
```

O APK de debug ficará em:

`apps/mobile/android/app/build/outputs/apk/debug/app-debug.apk`

## Build no GitHub

O workflow **Mega Cerebro Android** gera automaticamente um APK de debug e publica o arquivo `mega-cerebro-android-debug.apk` como artifact do GitHub Actions.

## Publicação na Play Store

A versão de loja deve usar assinatura de release, Android App Bundle (AAB), política de privacidade, ícone/splash definitivos e backend HTTPS. Chaves de assinatura não devem ser commitadas no repositório.


## Login de teste

O APK de teste pode usar usuário e senha, mas esse modo é **desligado por padrão** no servidor.

Para ativar temporariamente, configure no arquivo `.env.app`:

```env
APP_TEST_LOGIN_ENABLED=1
APP_TEST_USERNAME=admin
APP_TEST_PASSWORD=admin
```

Depois reinicie os containers. As credenciais de teste são:

- Usuário: `admin`
- Senha: `admin`

O backend troca essas credenciais por um token de sessão temporário de 12 horas. Desative `APP_TEST_LOGIN_ENABLED` antes de qualquer publicação ou exposição pública.
