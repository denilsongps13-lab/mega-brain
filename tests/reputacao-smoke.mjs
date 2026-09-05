import assert from 'node:assert/strict';
import fs from 'fs-extra';
import { runReputacao } from '../bin/lib/reputacao.js';

await fs.remove('workspace/reputacao');
const analise = await runReputacao(['analisar', 'Empresa Teste', '--nota', '3.8', '--avaliacoes', '12', '--sem-resposta', '5', '--negativas', '2']);
assert.equal(analise.empresa, 'Empresa Teste');
assert.equal(analise.diagnostico.prioridade, 'alta');
assert.match(analise.abordagem, /Empresa Teste/);
assert.equal(analise.pacotes.gestao.preco, 197);

const criado = await runReputacao(['adicionar', 'Empresa Teste', '--contato', '69999999999', '--nota', '3.8', '--avaliacoes', '12']);
assert.equal(criado.ok, true);
const lista = await runReputacao(['listar']);
assert.equal(lista.leads.length, 1);
assert.equal(lista.leads[0].status, 'Novo');
const atualizado = await runReputacao(['status', criado.lead.id, 'Contatado']);
assert.equal(atualizado.lead.status, 'Contatado');
await fs.remove('workspace/reputacao');
console.log('Reputacao 5 Estrelas: smoke test OK');
