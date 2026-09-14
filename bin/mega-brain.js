#!/usr/bin/env node

import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { readFileSync, existsSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const envPath = resolve(__dirname, '..', '.env');
if (existsSync(envPath)) { try { process.loadEnvFile(envPath); } catch {} }
const pkg = JSON.parse(readFileSync(resolve(__dirname, '..', 'package.json'), 'utf-8'));
const args = process.argv.slice(2);
const command = args[0];
const DISPATCH_MODE = process.env.MEGABRAIN_DISPATCH_MODE || 'subprocess';

async function dispatchOperation(operation, kwargs = {}) {
  if (DISPATCH_MODE === 'subprocess') {
    const { execFileSync } = await import('child_process');
    const { resolvePythonCmd } = await import('./lib/python-cmd.js');
    const pythonCmd = resolvePythonCmd();
    if (!pythonCmd) throw new Error('Python 3 não detectado (python3/python/py -3). Rode `mega-brain doctor`.');
    const projectRoot = resolve(__dirname, '..');
    const script = `import json, sys\nsys.path.insert(0, ${JSON.stringify(projectRoot)})\nfrom engine.operations import dispatch\nresult = dispatch(${JSON.stringify(operation)}, **json.loads(sys.argv[1]))\nprint(json.dumps(result, default=str))`;
    const result = execFileSync(pythonCmd[0], [...pythonCmd.slice(1), '-c', script, JSON.stringify(kwargs)], { cwd: projectRoot, encoding: 'utf-8', env: { ...process.env, PYTHONPATH: projectRoot } });
    return JSON.parse(result.trim() || 'null');
  }
  if (DISPATCH_MODE === 'mcp') throw new Error('MCP dispatch mode not yet implemented. Use subprocess (default).');
  if (DISPATCH_MODE === 'api') throw new Error('API dispatch mode not yet implemented. Use subprocess (default).');
  throw new Error(`Unknown dispatch mode: ${DISPATCH_MODE}. Valid: subprocess, mcp, api`);
}

async function main() {
  const { showBanner, showHelp } = await import('./lib/ascii-art.js');
  showBanner(pkg.version);
  if (!command || command === '--help' || command === '-h') { showHelp(pkg.version); process.exit(0); }

  // Reputacao e um modulo local e nao depende do setup de provedores de IA.
  if (command === 'reputacao') {
    const { runReputacao } = await import('./lib/reputacao.js');
    const result = await runReputacao(args.slice(1));
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  if (!['install', 'setup', 'push', 'update', 'start', 'execute', 'context', 'memory', 'doctor', 'preflight'].includes(command)) {
    const projectEnv = resolve(process.cwd(), '.env');
    if (!existsSync(projectEnv)) {
      let boxen = null, chalk = null;
      try { boxen = (await import('boxen')).default ?? null; } catch {}
      try { chalk = (await import('chalk')).default ?? null; } catch {}
      if (boxen && chalk) {
        console.log(boxen(chalk.cyan('  Primeira vez? Vamos configurar.\n') + chalk.dim('  Executando setup wizard...'), { padding: 1, borderColor: 'cyan', borderStyle: 'round' }));
        const { runSetup } = await import('./lib/setup-wizard.js'); await runSetup(); process.exit(0);
      }
      console.log('\n  Sem .env e sem node_modules? Rode: mega-brain install');
    }
  }

  switch (command) {
    case 'install': { const { runInstaller } = await import('./lib/installer.js'); await runInstaller(pkg.version, args[1]); break; }
    case 'update': { const { runUpdate } = await import('./lib/installer.js'); await runUpdate(pkg.version); break; }
    case 'status': { const { getProStatus } = await import('./utils/pro-detector.js'); const { getLicenseState } = await import('./lib/license.js'); const { showStatusBox } = await import('./lib/ascii-art.js'); const status = getProStatus(); showStatusBox({ state: getLicenseState(status.license), email: status.email, activatedAt: status.activatedAt }, status.installed); break; }
    case 'features': { const { listFeatures } = await import('./lib/feature-gate.js'); const { showFeatureTable } = await import('./lib/ascii-art.js'); showFeatureTable(listFeatures()); break; }
    case 'setup': { const { runSetup } = await import('./lib/setup-wizard.js'); await runSetup(); break; }
    case 'push': { await import('./push.js'); break; }
    case 'search': { const query = args[1]; if (!query) throw new Error('Uso: mega-brain search <query>'); const bucketFlag = args.indexOf('--bucket'); const buckets = bucketFlag !== -1 && args[bucketFlag + 1] ? [args[bucketFlag + 1]] : null; console.log(JSON.stringify(await dispatchOperation('search_knowledge', { query, buckets }), null, 2)); break; }
    case 'buckets': console.log(JSON.stringify(await dispatchOperation('available_buckets'), null, 2)); break;
    case 'preflight': console.log(JSON.stringify(await dispatchOperation('run_preflight'), null, 2)); break;
    case 'health': console.log(JSON.stringify(await dispatchOperation('check_agent_health', { agent_id: args[1] || null }), null, 2)); break;
    case 'ingest': { const sourcePath = args[1]; if (!sourcePath) throw new Error('Uso: mega-brain ingest <source-path>'); const f = args.indexOf('--bucket'); console.log(JSON.stringify(await dispatchOperation('ingest', { source_path: sourcePath, bucket: f !== -1 ? args[f + 1] : null }), null, 2)); break; }
    case 'index': console.log(JSON.stringify(await dispatchOperation('build_index', { bucket_name: args[1] || null }), null, 2)); break;
    case 'conclave': { if (!args[1]) throw new Error('Uso: mega-brain conclave <topic>'); const f = args.indexOf('--agents'); console.log(JSON.stringify(await dispatchOperation('run_conclave', { topic: args[1], agents: f !== -1 && args[f+1] ? args[f+1].split(',') : null }), null, 2)); break; }
    case 'dossier': { if (!args[1]) throw new Error('Uso: mega-brain dossier <persona>'); console.log(JSON.stringify(await dispatchOperation('compile_dossier', { persona: args[1] }), null, 2)); break; }
    case 'governance': console.log(JSON.stringify(await dispatchOperation('validate_governance'), null, 2)); break;
    case 'workspace-health': console.log(JSON.stringify(await dispatchOperation('check_workspace_health'), null, 2)); break;
    case 'scheduler': console.log(JSON.stringify(await dispatchOperation('run_autonomous_pipeline'), null, 2)); break;
    case 'operations': console.log(JSON.stringify(await dispatchOperation('list_operations'), null, 2)); break;
    case 'start': { const { runStart } = await import('./lib/start.js'); await runStart(pkg.version); break; }
    case 'context': console.log(JSON.stringify(await dispatchOperation('project_context'), null, 2)); break;
    case 'memory': console.log(JSON.stringify(await dispatchOperation('mega_memory'), null, 2)); break;
    case 'execute': {
      const objective = args.slice(1).join(' ').trim();
      if (!objective) throw new Error('Uso: mega-brain execute "<objetivo>"');
      const kw = {};
      const d = args.indexOf('--dangerous');
      if (d !== -1 && args[d + 1]) kw.permission_mode = args[d + 1];
      const w = args.indexOf('--workspace');
      if (w !== -1 && args[w + 1]) kw.workspace = args[w + 1];
      const m = args.indexOf('--max-attempts');
      if (m !== -1 && args[m + 1]) kw.max_attempts = args[m + 1];
      console.log(JSON.stringify(await dispatchOperation('execute_task', { objective, ...kw }), null, 2));
      break;
    }
    case 'dispatch': { if (!args[1]) throw new Error('Uso: mega-brain dispatch <operation>'); const jf = args.indexOf('--json'); const kwargs = jf !== -1 && args[jf+1] ? JSON.parse(args[jf+1]) : {}; console.log(JSON.stringify(await dispatchOperation(args[1], kwargs), null, 2)); break; }
    default: console.error(`\n  Comando desconhecido: ${command}`); showHelp(pkg.version); process.exit(1);
  }
}
main().catch((err) => { console.error(`\n  Erro: ${err.message}`); setTimeout(() => process.exit(1), 100); });
