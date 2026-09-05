import fs from 'fs-extra';
import { resolve } from 'path';

const DATA_DIR = resolve(process.cwd(), 'workspace', 'reputacao');
const LEADS_FILE = resolve(DATA_DIR, 'leads.json');

const PACOTES = {
  entrada: { nome: 'Entrada', preco: 99, cobranca: 'unica' },
  gestao: { nome: 'Gestao', preco: 197, cobranca: 'mensal' },
  premium: { nome: 'Premium', preco: 397, cobranca: 'mensal' },
};

async function loadLeads() {
  await fs.ensureDir(DATA_DIR);
  if (!(await fs.pathExists(LEADS_FILE))) await fs.writeJson(LEADS_FILE, [], { spaces: 2 });
  return fs.readJson(LEADS_FILE);
}

async function saveLeads(leads) {
  await fs.ensureDir(DATA_DIR);
  await fs.writeJson(LEADS_FILE, leads, { spaces: 2 });
}

function diagnosticar({ nota = 0, avaliacoes = 0, semResposta = 0, negativas = 0 }) {
  nota = Number(nota) || 0;
  avaliacoes = Number(avaliacoes) || 0;
  semResposta = Number(semResposta) || 0;
  negativas = Number(negativas) || 0;
  const problemas = [];
  let score = 0;
  if (nota > 0 && nota < 4.2) { problemas.push('nota abaixo de 4,2'); score += 3; }
  if (avaliacoes < 30) { problemas.push('baixo volume de avaliacoes'); score += 2; }
  if (semResposta > 0) { problemas.push(`${semResposta} avaliacao(oes) sem resposta`); score += 2; }
  if (negativas > 0) { problemas.push(`${negativas} avaliacao(oes) negativa(s) para tratar`); score += 2; }
  if (!problemas.length) problemas.push('perfil ja possui boa base; foco em consistencia e crescimento');
  const prioridade = score >= 6 ? 'alta' : score >= 3 ? 'media' : 'baixa';
  return { score, prioridade, problemas };
}

function abordagem(empresa, diag) {
  const ponto = diag.problemas[0];
  return `Ola! Tudo bem? Dei uma olhada na reputacao online da ${empresa} e identifiquei um ponto que pode ser melhorado: ${ponto}. Trabalhamos com gestao de reputacao para ajudar empresas a conseguir mais avaliacoes de clientes reais, responder corretamente aos clientes e melhorar a apresentacao do negocio na internet. Posso te mostrar uma analise gratuita, sem compromisso?`;
}

export async function runReputacao(args) {
  const action = args[0] || 'help';
  if (action === 'pacotes') return { pacotes: PACOTES };
  if (action === 'listar') return { leads: await loadLeads() };
  if (action === 'analisar') {
    const empresa = args[1];
    if (!empresa) throw new Error('Uso: mega-brain reputacao analisar "Empresa" --nota 4.1 --avaliacoes 20 --sem-resposta 5 --negativas 2');
    const get = (flag, fallback = 0) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : fallback; };
    const dados = { nota: get('--nota'), avaliacoes: get('--avaliacoes'), semResposta: get('--sem-resposta'), negativas: get('--negativas') };
    const diagnostico = diagnosticar(dados);
    return { empresa, dados, diagnostico, abordagem: abordagem(empresa, diagnostico), pacotes: PACOTES };
  }
  if (action === 'adicionar') {
    const empresa = args[1];
    if (!empresa) throw new Error('Informe o nome da empresa.');
    const leads = await loadLeads();
    const get = (flag, fallback = '') => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : fallback; };
    const dados = { nota: get('--nota', 0), avaliacoes: get('--avaliacoes', 0), semResposta: get('--sem-resposta', 0), negativas: get('--negativas', 0) };
    const diagnostico = diagnosticar(dados);
    const lead = { id: Date.now().toString(), empresa, contato: get('--contato'), link: get('--link'), status: 'Novo', pacote: get('--pacote'), dados, diagnostico, abordagem: abordagem(empresa, diagnostico), criadoEm: new Date().toISOString() };
    leads.push(lead); await saveLeads(leads); return { ok: true, lead };
  }
  if (action === 'status') {
    const id = args[1], status = args.slice(2).join(' ');
    if (!id || !status) throw new Error('Uso: mega-brain reputacao status <id> <Novo|Contatado|Respondeu|Negociacao|Cliente>');
    const permitidos = ['Novo','Contatado','Respondeu','Negociacao','Cliente'];
    const normalizado = permitidos.find(x => x.toLowerCase() === status.toLowerCase());
    if (!normalizado) throw new Error(`Status invalido. Use: ${permitidos.join(', ')}`);
    const leads = await loadLeads(); const lead = leads.find(x => x.id === id);
    if (!lead) throw new Error('Lead nao encontrado.'); lead.status = normalizado; lead.atualizadoEm = new Date().toISOString();
    await saveLeads(leads); return { ok: true, lead };
  }
  return { modulo: 'Reputacao 5 Estrelas', comandos: ['reputacao analisar "Empresa" --nota 4.1 --avaliacoes 20 --sem-resposta 5 --negativas 2','reputacao adicionar "Empresa" --contato 69999999999 --link URL --nota 4.1 --avaliacoes 20','reputacao listar','reputacao status <id> Contatado','reputacao pacotes'], regra: 'Somente avaliacoes autenticas de clientes reais; o modulo nao cria, compra ou manipula avaliacoes.' };
}
