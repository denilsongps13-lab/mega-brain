export type Source = { source: string; text: string; chunk_id: string; score: number };
export type Provider = { id: string; model: string; status: string; streaming: string };
export type Message = { id: string; role: string; content: string; state: string; details?: { provider?: { provider: string; model: string; fallback: boolean }; context?: { sources: Source[]; memory: Record<string, unknown> } } };
export type Conversation = { id: string; title: string; created_at: string };
export type Job = { id: string; kind: string; objective: string; state: string; progress: number; result: Record<string, unknown>; created_at: string };
export type Doc = { id: string; name: string; size: number; job: Job; job_id: string };
export type Agent = { id: string; role: string; status: string; available: boolean; current: boolean; capabilities: string[] };
export type StreamEvent = { id?: number; type: string; text?: string; state?: string; provider?: string; model?: string; fallback?: boolean; message?: string; sources?: Source[]; memory?: Record<string, unknown> };
export const terminal = new Set(['done', 'error', 'partial', 'cancelled']);

function normalizeBase(value: string) {
  const raw = value.trim().replace(/\/$/, '');
  if (!raw) return '';
  const url = new URL(raw);
  if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Use um endereço HTTP ou HTTPS válido.');
  if (url.username || url.password) throw new Error('Não inclua usuário ou senha no endereço da API.');
  return url.toString().replace(/\/$/, '');
}

export function isNativeShell() {
  if (typeof window === 'undefined') return false;
  const native = (window as Window & { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
  return native?.isNativePlatform?.() === true || window.location.protocol === 'capacitor:';
}

export function getRuntimeApiUrl() {
  const configured = (process.env.NEXT_PUBLIC_API_URL || '').trim();
  return configured ? normalizeBase(configured) : '';
}
export const labels: Record<string,string> = { online:'Online', offline:'Offline', configured:'Configurado · não verificado', not_configured:'Não configurado', available:'Disponível', queued:'Na fila', thinking:'Pensando', planning:'Planejando', executing:'Executando', validating:'Validando', processing:'Processando', chunking:'Dividindo em trechos', indexing:'Indexando', done:'Concluído', partial:'Parcial · requer atenção', cancelled:'Cancelado', error:'Erro', active:'Ativo', placeholder:'Definição incompleta' };
export async function loginWithCredentials(username: string, password: string) {
  const base = getRuntimeApiUrl();
  if (isNativeShell() && !base) throw new Error('Este APK ainda não tem um servidor configurado.');
  const response = await fetch(base + '/api/login', {
    method: 'POST',
    cache: 'no-store',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({username, password})
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Falha no login (${response.status})`);
  }
  return response.json() as Promise<{access_token:string;token_type:string;expires_in:number}>;
}

export function client(token: string) {
  return async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
    const base = getRuntimeApiUrl();
    if (isNativeShell() && !base) throw new Error('Configure o endereço do servidor do Mega Cérebro.');
    const response = await fetch(base + path, { ...init, cache: 'no-store', headers: { Authorization: `Bearer ${token}`, ...(init.body && !(init.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...init.headers } });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : `Falha na solicitação (${response.status})`); }
    return response.json();
  };
}
export async function watchJob(token: string, id: string, kind: string, onEvent: (e: StreamEvent) => void, onConnection: (s: string) => void): Promise<() => void> {
  let stopped = false, after = 0, tries = 0;
  let socket: WebSocket | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const api = client(token);
  async function connect() {
    try {
      const { ticket } = await api<{ ticket: string }>('/api/ws-ticket', { method: 'POST', body: JSON.stringify({ job_id: id }) });
      if (stopped) return;
      const base = getRuntimeApiUrl() || location.origin;
      if (isNativeShell() && !getRuntimeApiUrl()) throw new Error('Servidor não configurado neste APK');
      const url = new URL(kind === 'chat' ? '/ws/chat' : '/ws/executions', base); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(url);
      socket.onopen = () => { onConnection('online'); socket?.send(JSON.stringify({ ticket, after })); };
      socket.onmessage = (message) => { const event: StreamEvent = JSON.parse(message.data); if (event.id) { after = event.id; tries = 0; } if (event.type === 'terminal') stopped = true; onEvent(event); };
      socket.onclose = () => { if (!stopped) retry(); else onConnection('available'); };
      socket.onerror = () => onConnection('offline');
    } catch { retry(); }
  }
  function retry() { onConnection('offline'); if (stopped) return; if (++tries > 6) { onEvent({ type: 'error', message: 'Conexão interrompida. Consulte Execuções para recuperar o resultado.' }); return; } timer = setTimeout(connect, Math.min(1000 * 2 ** tries, 15000)); }
  await connect();
  return () => { stopped = true; clearTimeout(timer); socket?.close(); };
}
