'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Activity, ArrowUp, Bot, BrainCircuit, Check, ChevronRight, CircleStop, FileText, Menu, MessageSquare, Plus, Search, Settings, ShieldCheck, Sparkles, Upload, Workflow, X, Zap } from 'lucide-react';
import { type Agent, type Conversation, type Doc, type Job, type Message, type Provider, type Source, client, getRuntimeApiUrl, isNativeShell, labels, saveRuntimeApiUrl, terminal, watchJob } from '@/lib/api';

type Page = 'Chat' | 'Conversas' | 'Memória' | 'Documentos' | 'Agentes' | 'Execuções' | 'Status' | 'Configurações';
const nav = [{name:'Conversas', icon:MessageSquare}, {name:'Memória', icon:BrainCircuit}, {name:'Documentos', icon:FileText}, {name:'Agentes', icon:Bot}, {name:'Execuções', icon:Workflow}, {name:'Status', icon:Activity}, {name:'Configurações', icon:Settings}] as const;
const display = (s: string) => labels[s] || s;
function Badge({ state }: {state: string}) { return <span className={`badge ${['online','done','active'].includes(state) ? 'good' : ['error','offline'].includes(state) ? 'bad' : ''}`}><span className="dot"/>{display(state)}</span>; }
function Markdown({ children }: {children: string}) { return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{a: ({children, ...props}) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a>, img: () => <span>[Imagem externa omitida]</span>}}>{children}</ReactMarkdown></div>; }
function Sources({sources}: {sources: Source[]}) { return sources.length > 0 ? <details className="sources"><summary>{sources.length} fontes consultadas</summary>{sources.map((s,i) => <div key={`${s.chunk_id}-${i}`}><strong>{s.source}</strong><p>{s.text}</p></div>)}</details> : null; }

export default function Home() {
  const [token,setToken] = useState(''), [inputToken,setInputToken] = useState('');
  const [page,setPage] = useState<Page>('Chat'), [sidebar,setSidebar] = useState(false);
  const [error,setError] = useState(''), [loading,setLoading] = useState(false);
  const [conversations,setConversations] = useState<Conversation[]>([]), [cid,setCid] = useState<string>();
  const [messages,setMessages] = useState<Message[]>([]), [draft,setDraft] = useState('');
  const [mode,setMode] = useState<'chat'|'execution'>('chat'), [activeJob,setActiveJob] = useState<Job>();
  const [jobs,setJobs] = useState<Job[]>([]), [docs,setDocs] = useState<Doc[]>([]), [agents,setAgents] = useState<Agent[]>([]);
  const [providers,setProviders] = useState<Provider[]>([]), [status,setStatus] = useState<Record<string,unknown>>({});
  const [memory,setMemory] = useState<Record<string,unknown>>({}), [sources,setSources] = useState<Source[]>([]), [query,setQuery] = useState('');
  const [connection,setConnection] = useState('offline'), [model,setModel] = useState('Nenhum modelo em uso');
  const [uploading,setUploading] = useState(false);
  const [nativeShell,setNativeShell] = useState(false), [serverUrl,setServerUrl] = useState('');
  const stop = useRef<(() => void) | undefined>(undefined), end = useRef<HTMLDivElement>(null);
  const api = useCallback(<T,>(path: string, init?: RequestInit) => client(token)<T>(path, init), [token]);

  const refresh = useCallback(async () => {
    const [c,j,d,p,s] = await Promise.all([api<Conversation[]>('/api/chat/conversations'),api<Job[]>('/api/executions'),api<Doc[]>('/api/documents'),api<Provider[]>('/api/providers'),api<Record<string,unknown>>('/api/status')]);
    setConversations(c); setJobs(j); setDocs(d); setProviders(p); setStatus(s);
  }, [api]);
  useEffect(() => {
    const native = isNativeShell();
    const timer = window.setTimeout(() => {
      setNativeShell(native);
      if (native) setServerUrl(getRuntimeApiUrl());
    }, 0);
    if ('serviceWorker' in navigator && !native) navigator.serviceWorker.register('/sw.js').catch(() => {});
    return () => { window.clearTimeout(timer); stop.current?.(); };
  }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior:'smooth' }); }, [messages]);
  useEffect(() => {
    if (!token) return;
    const timer = setInterval(() => { refresh().catch(() => setConnection('offline')); }, 5000);
    return () => clearInterval(timer);
  }, [token, refresh]);

  async function login(e: React.FormEvent) {
    e.preventDefault(); setLoading(true); setError('');
    try {
      if (nativeShell) saveRuntimeApiUrl(serverUrl);
      const a = client(inputToken);
      const s = await a<Record<string,unknown>>('/api/status');
      const c = await a<Conversation[]>('/api/chat/conversations');
      setStatus(s); setConversations(c); setToken(inputToken); setInputToken(''); setConnection('available');
    }
    catch(e) { setError((e as Error).message); } finally { setLoading(false); }
  }
  async function navigate(next: Page) {
    setPage(next); setSidebar(false); setError('');
    try {
      await refresh();
      if (next === 'Agentes') { const a = await api<{agents:Agent[]}>('/api/agents'); setAgents(a.agents); }
      if (next === 'Memória') { const m = await api<{memory:Record<string,unknown>; sources:Source[]}>('/api/memory'); setMemory(m.memory); setSources(m.sources); }
    } catch(e) { setError((e as Error).message); }
  }
  function newChat() { if (activeJob && !terminal.has(activeJob.state)) { setError('Aguarde ou cancele a execução atual.'); return; } stop.current?.(); setCid(undefined); setMessages([]); setPage('Chat'); setActiveJob(undefined); setSidebar(false); }
  async function openConversation(id:string) {
    if (activeJob && !terminal.has(activeJob.state)) { setError('Aguarde ou cancele a execução atual.'); return; }
    try {
      stop.current?.(); setActiveJob(undefined); setMessages(await api<Message[]>(`/api/chat/conversations/${id}`)); setCid(id); setPage('Chat'); setSidebar(false);
      const allJobs = await api<Job[]>('/api/executions');
      const pending = allJobs.find(j => j.kind === 'chat' && !terminal.has(j.state) && (j as Job & {conversation_id?:string}).conversation_id === id);
      if (pending) { setActiveJob(pending); await subscribe(pending, id, true); }
    } catch(e) { setError((e as Error).message); }
  }
  async function subscribe(job: Job, conversation?:string, replay=false) {
    stop.current?.();
    if (replay && conversation) setMessages(prev => prev.map(m => m.role === 'assistant' && !terminal.has(m.state) ? {...m,content:''} : m));
    stop.current = await watchJob(token, job.id, job.kind, async event => {
      if (event.type === 'delta') setMessages(prev => prev.map((m,i) => i === prev.length - 1 ? {...m,content:m.content+(event.text || '')} : m));
      if (event.type === 'provider') setModel(`${event.provider} / ${event.model}${event.fallback ? ' · fallback' : ''}`);
      if (event.type === 'phase') setActiveJob(prev => prev ? {...prev,state:event.state || prev.state} : prev);
      if (event.type === 'error') setError(event.message || 'Falha na execução');
      if (event.type === 'terminal') {
        try { const latest = await api<Job>(`/api/executions/${job.id}`); setActiveJob(latest); if(conversation) setMessages(await api<Message[]>(`/api/chat/conversations/${conversation}`)); await refresh(); }
        catch(e) { setError((e as Error).message); }
      }
    }, setConnection);
  }
  async function send(e: React.FormEvent) {
    e.preventDefault(); if(!draft.trim() || loading || (activeJob && !terminal.has(activeJob.state))) return;
    setLoading(true); setError(''); const text = draft;
    try {
      if(mode === 'chat') {
        const created = await api<{id:string;conversation_id:string;message_id:string}>('/api/chat',{method:'POST',body:JSON.stringify({content:text,conversation_id:cid})});
        setCid(created.conversation_id); setMessages(prev => [...prev,{id:crypto.randomUUID(),role:'user',content:text,state:'done'},{id:created.message_id,role:'assistant',content:'',state:'processing'}]);
        const job = await api<Job>(`/api/executions/${created.id}`); setActiveJob(job); await subscribe(job,created.conversation_id);
      } else { const job = await api<Job>('/api/executions',{method:'POST',body:JSON.stringify({objective:text})}); setActiveJob(job); setPage('Execuções'); await subscribe(job); }
      setDraft(''); await refresh();
    } catch(e) { setError((e as Error).message); } finally { setLoading(false); }
  }
  async function cancel() { if(!activeJob) return; try { await api(`/api/executions/${activeJob.id}/cancel`,{method:'POST'}); setActiveJob(await api<Job>(`/api/executions/${activeJob.id}`)); } catch(e) { setError((e as Error).message); } }
  async function upload(file?:File) {
    if(!file) return; setUploading(true); setError('');
    try { if(file.size > 20*1024*1024) throw new Error('Limite de 20 MB por arquivo'); const form = new FormData(); form.append('file',file); await api('/api/documents',{method:'POST',body:form}); await refresh(); }
    catch(e) { setError((e as Error).message); } finally { setUploading(false); }
  }
  async function searchMemory(e:React.FormEvent) { e.preventDefault(); try { const m = await api<{memory:Record<string,unknown>;sources:Source[]}>(`/api/memory?q=${encodeURIComponent(query)}`); setMemory(m.memory); setSources(m.sources); } catch(e) { setError((e as Error).message); } }
  const busy = loading || !!activeJob && !terminal.has(activeJob.state);

  if (!token) return <main className="login"><div className="login-card"><div className="brain-logo"><BrainCircuit size={38}/></div><span className="eyebrow">INTELIGÊNCIA CONECTADA</span><h1>Mega Cérebro</h1><p>Seu conhecimento.<br/>Uma nova forma de executar.</p><form onSubmit={login}>{nativeShell && <><label htmlFor="server">Servidor do Mega Cérebro</label><input id="server" type="url" value={serverUrl} onChange={e=>setServerUrl(e.target.value)} placeholder="https://seu-servidor.com" autoComplete="url" required/></>}<label htmlFor="access">Token de acesso da instalação</label><input id="access" type="password" value={inputToken} onChange={e=>setInputToken(e.target.value)} placeholder="Informe seu token privado" autoComplete="off" required minLength={32}/><button className="primary" disabled={loading}>{loading ? 'Conectando…' : 'Acessar meu cérebro'}<ChevronRight size={18}/></button></form>{error && <p role="alert" className="error">{error}</p>}<small><ShieldCheck size={14}/>Acesso privado · credenciais dos modelos ficam no servidor</small></div></main>;

  return <div className="app-shell">
    {sidebar && <button aria-label="Fechar menu" className="overlay" onClick={()=>setSidebar(false)}/>}
    <aside className={sidebar ? 'sidebar open' : 'sidebar'}>
      <a href="#" className="brand" onClick={e=>{e.preventDefault();newChat();}}><BrainCircuit size={31}/><span>Mega Cérebro<small>WORKSPACE PESSOAL</small></span></a>
      <button className="new-chat" onClick={newChat}><Plus size={18}/>Novo chat<span>↗</span></button>
      <span className="nav-label">ESPAÇO DE TRABALHO</span>
      <nav>{nav.map(item=><button key={item.name} className={page===item.name || page==='Chat' && item.name==='Conversas' ? 'selected' : ''} onClick={()=>navigate(item.name)}><item.icon size={18}/>{item.name}{item.name==='Documentos' && docs.length > 0 && <em>{docs.length}</em>}</button>)}</nav>
      <div className="recent"><span className="nav-label">CONVERSAS RECENTES</span>{conversations.slice(0,5).map(c=><button key={c.id} onClick={()=>openConversation(c.id)}><MessageSquare size={14}/><span>{c.title}</span></button>)}{!conversations.length && <small>Suas conversas aparecem aqui.</small>}</div>
      <div className="sidebar-footer"><span className="avatar">MC</span><div>Meu workspace<small>Instalação privada</small></div><ShieldCheck size={16}/></div>
    </aside>
    <div className="main-shell">
      <header><div className="header-title"><button className="icon-button mobile-menu" aria-label="Abrir menu" onClick={()=>setSidebar(true)}><Menu size={22}/></button><span>{page==='Chat'?'Novo pensamento':page}</span><span className="divider">/</span><span className="muted">Mega Cérebro</span></div><div className="header-status"><span className="online-dot"/><span>{status.backend==='online'?'Backend conectado':'Backend indisponível'}</span><span className="connection" title={`WebSocket: ${display(connection)}`}>WS · {display(connection)}</span></div></header>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="Fechar aviso" onClick={()=>setError('')}><X size={16}/></button></div>}
      {page==='Chat' ? <div className="chat-view">
        <div className="chat-scroll">
          {!messages.length ? <section className="welcome"><div className="neural-mark"><BrainCircuit size={66} strokeWidth={1.2}/><span className="orbit-dot"/></div><span className="eyebrow">PENSE MAIOR. CONECTE TUDO.</span><h1>O que vamos construir hoje?</h1><p>Converse com seu conhecimento ou transforme<br className="desktop-break"/> um objetivo em uma sequência de ações.</p><div className="suggestions"><button onClick={()=>{setMode('chat');setDraft('Quais informações da minha memória podem me ajudar a organizar o próximo projeto?');}}><BrainCircuit size={21}/><strong>Conectar ideias</strong><span>Explore o que você já sabe</span><ChevronRight size={16}/></button><button onClick={()=>{setMode('execution');setDraft('Analise o projeto autorizado, identifique problemas e execute os testes disponíveis.');}}><Zap size={21}/><strong>Executar um objetivo</strong><span>Do planejamento à validação</span><ChevronRight size={16}/></button><button onClick={()=>navigate('Documentos')}><FileText size={21}/><strong>Explorar documentos</strong><span>Adicione fontes ao seu cérebro</span><ChevronRight size={16}/></button></div><div className="private-note"><ShieldCheck size={14}/>Você mantém o controle. Ações restritas passam pelo executor protegido.</div></section> : <div className="messages">{messages.map(m=><article className={`message ${m.role}`} key={m.id}><div className="message-icon">{m.role==='user'?'EU':<BrainCircuit size={21}/>}</div><div className="message-body"><div className="message-label">{m.role==='user'?'Você':'Mega Cérebro'}{m.details?.provider && <small>{m.details.provider.provider} · {m.details.provider.model}{m.details.provider.fallback?' · fallback':''}</small>}</div>{m.content ? <Markdown>{m.content}</Markdown> : <span className="thinking">{busy?'Processando seu pensamento…':display(m.state)}</span>}{m.details?.context && <><Sources sources={m.details.context.sources}/><details className="sources"><summary>Memória utilizada</summary><pre>{JSON.stringify(m.details.context.memory,null,2)}</pre></details></>}{['error','cancelled'].includes(m.state) && <Badge state={m.state}/>}</div></article>)}<div ref={end}/></div>}
        </div>
        <div className="composer-wrap"><form className="composer" onSubmit={send}><div className="mode-row"><button type="button" className={mode==='chat'?'mode active':'mode'} onClick={()=>setMode('chat')}><MessageSquare size={14}/>Conversar</button><button type="button" className={mode==='execution'?'mode active':'mode'} onClick={()=>setMode('execution')}><Zap size={14}/>Executar objetivo</button>{busy && <Badge state={activeJob?.state || 'processing'}/>}</div><textarea aria-label="Mensagem" value={draft} onChange={e=>setDraft(e.target.value)} maxLength={16000} placeholder={mode==='chat'?'Pergunte, conecte ideias ou explore seu conhecimento…':'Descreva o objetivo para o projeto autorizado…'} rows={2} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit();}}}/><div className="composer-bottom"><button type="button" className="attach" onClick={()=>navigate('Documentos')}><Plus size={18}/><span>Adicionar fonte</span></button><span className="model-label" title={model}><span className="dot"/>{model}</span>{busy?<button type="button" className="send cancel" aria-label="Cancelar execução" onClick={cancel}><CircleStop size={22}/></button>:<button className="send" aria-label="Enviar mensagem" disabled={!draft.trim()}><ArrowUp size={22}/></button>}</div></form><p className="composer-note">O Mega Cérebro pode cometer erros. Revise informações e resultados importantes.</p></div>
      </div> : <main className="content-page">
        <div className="page-heading"><span className="eyebrow">MEGA CÉREBRO / WORKSPACE</span><h1>{page}</h1><p>{{Conversas:'Retome ideias e continue de onde parou.',Memória:'Contexto persistente do projeto e fontes recuperadas.',Documentos:'Transforme seus arquivos em conhecimento consultável.',Agentes:'Conheça os papéis definidos no seu engine.',Execuções:'Acompanhe tarefas, validações e resultados.',Status:'Uma visão transparente dos serviços da instalação.',Configurações:'Sua instalação, seus modelos, seu controle.'}[page]}</p></div>
        {page==='Conversas' && <div className="list">{conversations.map(c=><button className="list-row" key={c.id} onClick={()=>openConversation(c.id)}><MessageSquare/><div><strong>{c.title}</strong><small>{new Date(c.created_at).toLocaleString('pt-BR')}</small></div><ChevronRight/></button>)}{!conversations.length&&<Empty text="Sua primeira conversa começa com uma ideia." action={newChat}/>}</div>}
        {page==='Memória' && <><form className="search-bar" onSubmit={searchMemory}><Search size={19}/><input aria-label="Pesquisar memória" placeholder="Pesquisar na memória e nas fontes…" value={query} onChange={e=>setQuery(e.target.value)} maxLength={1000}/><button className="primary">Pesquisar</button></form><div className="cards">{Object.entries(memory).filter(([,v])=>v!==null && (!Array.isArray(v)||v.length)).map(([k,v])=><section className="card" key={k}><h3>{k}</h3><pre>{typeof v==='string'?v:JSON.stringify(v,null,2)}</pre></section>)}</div>{!Object.values(memory).some(v=>Array.isArray(v)?v.length:v)&&<Empty text="A memória será preenchida pelas execuções do projeto."/>}<Sources sources={sources}/></>}
        {page==='Documentos' && <><label className="upload-zone"><Upload size={28}/><strong>{uploading?'Enviando arquivo…':'Adicionar conhecimento'}</strong><span>PDF, TXT, Markdown ou DOCX · até 20 MB</span><input aria-label="Enviar documento" type="file" accept=".pdf,.txt,.md,.markdown,.docx" disabled={uploading} onChange={e=>{upload(e.target.files?.[0]);e.target.value='';}}/></label><div className="list">{docs.map(d=><div className="list-row" key={d.id}><FileText/><div><strong>{d.name}</strong><small>{Math.ceil(d.size/1024)} KB · {d.job.result.chunks ? `${d.job.result.chunks} trechos indexados` : 'Processamento pelo engine'}</small>{Boolean(d.job.result.error) && <p className="error">{String(d.job.result.error)}</p>}<progress value={d.job.progress} max={100} aria-label={`Progresso de ${d.name}`}/></div><Badge state={d.job.state}/></div>)}</div></>}
        {page==='Agentes' && <><div className="info-panel"><Bot size={22}/><p>Este catálogo mostra as definições reais do repositório. O executor atual utiliza seu planejador e ferramentas; delegação automática aos squads ainda não está integrada.</p></div><div className="cards">{agents.map(a=><section className="card agent-card" key={a.id}><Bot size={25}/><Badge state={a.available?a.status:'offline'}/><h3>{a.id}</h3><p>{a.role}</p><small>Nenhuma tarefa delegada nesta versão</small></section>)}</div></>}
        {page==='Execuções' && <>{activeJob && <section className="execution-detail card"><div className="section-title"><h2>Execução selecionada</h2><Badge state={activeJob.state}/></div><p>{activeJob.objective}</p><div className="phases">{['thinking','planning','executing','validating','done'].map(s=><span key={s} className={activeJob.state===s?'current':''}>{s==='done'?<Check size={14}/>:<span className="dot"/>}{display(s)}</span>)}</div>{!terminal.has(activeJob.state)&&<button className="secondary" onClick={cancel}><CircleStop size={16}/>Cancelar</button>}{Boolean(activeJob.result.report_markdown) && <Markdown>{String(activeJob.result.report_markdown)}</Markdown>}{Boolean(activeJob.result.error) && <p className="error">{String(activeJob.result.error)}</p>}{Boolean(activeJob.result.limitation) && <p className="error">{String(activeJob.result.limitation)}</p>}</section>}<div className="list">{jobs.map(j=><button className="list-row" key={j.id} onClick={async()=>{if(busy && activeJob?.id!==j.id){setError('Aguarde ou cancele a execução atual.');return;}setActiveJob(j);if(!terminal.has(j.state))await subscribe(j);}}><Workflow/><div><strong>{j.objective}</strong><small>{j.kind} · {new Date(j.created_at).toLocaleString('pt-BR')}</small></div><Badge state={j.state}/></button>)}</div>{!jobs.length&&<Empty text="Nenhuma execução ainda. Descreva um objetivo no chat." action={newChat}/>}</>}
        {page==='Status' && <><div className="cards">{Object.entries(status).filter(([k,v])=>typeof v==='string'&&!['scope','provider'].includes(k)).map(([k,v])=><section className="card status-card" key={k}><Activity size={20}/><h3>{k}</h3><Badge state={String(v)}/></section>)}</div><h2 className="subheading">Provedores de inteligência</h2><ProviderCards providers={providers}/><div className="info-panel"><ShieldCheck size={22}/><p>“Configurado” verifica SDK e credenciais, sem fazer uma chamada paga. A conexão real e o fallback aparecem ao conversar. WebSocket ativo: {display(connection)}.</p></div></>}
        {page==='Configurações' && <><section className="card"><h2>Instalação privada</h2><p>O token de acesso fica apenas nesta aba e é removido ao recarregar. Chaves de Gemini, Groq, Claude e OpenAI são configuradas exclusivamente no servidor.</p><button className="secondary" onClick={()=>{stop.current?.();setToken('');setMessages([]);setActiveJob(undefined);setError('');}}>Sair da instalação</button></section><h2 className="subheading">Modelos configurados no backend</h2><ProviderCards providers={providers}/><section className="card"><h2>Instalar como aplicativo</h2><p>No navegador do celular, use “Adicionar à tela inicial” ou “Instalar aplicativo”. É necessário HTTPS, exceto em localhost. O processamento de IA requer conexão.</p><p>A interface também possui versão Android com Capacitor. No aplicativo, o endereço HTTPS do servidor é configurado na tela de entrada e fica salvo somente no dispositivo.</p></section></>}
      </main>}
    </div>
    <div className="mobile-tabbar" aria-label="Navegação principal">
      <button className={page==='Chat'?'active':''} onClick={()=>{setPage('Chat');setSidebar(false);}}><MessageSquare size={19}/><span>Chat</span></button>
      <button className={page==='Memória'?'active':''} onClick={()=>navigate('Memória')}><BrainCircuit size={19}/><span>Memória</span></button>
      <button className={page==='Documentos'?'active':''} onClick={()=>navigate('Documentos')}><FileText size={19}/><span>Arquivos</span></button>
      <button className={page==='Agentes'?'active':''} onClick={()=>navigate('Agentes')}><Bot size={19}/><span>Agentes</span></button>
      <button onClick={()=>setSidebar(true)}><Menu size={19}/><span>Mais</span></button>
    </div>
  </div>;
}
function Empty({text,action}:{text:string;action?:()=>void}) { return <div className="empty"><Sparkles size={30}/><p>{text}</p>{action&&<button className="secondary" onClick={action}>Iniciar conversa<Plus size={15}/></button>}</div>; }
function ProviderCards({providers}:{providers:Provider[]}) { return <div className="cards">{providers.map(p=><section className="card provider-card" key={p.id}><div className="section-title"><h3>{p.id==='anthropic'?'Claude / Anthropic':p.id}</h3><Badge state={p.status}/></div><p>{p.model}</p><small>{p.streaming==='buffered'?'Streaming após resposta completa':'Streaming nativo'}</small></section>)}</div>; }
