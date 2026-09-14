/**
 * Build the Mega Brain Windows installer.
 *
 * 1. Takes a CLEAN tracked snapshot via `git archive HEAD` -> staging/
 *    (guaranteed to exclude .env, .data, node_modules, .claude/mission-control,
 *    caches, logs and any other untracked local data).
 * 2. Compiles windows/installer/mega-brain.iss with Inno Setup (ISCC), version
 *    taken from package.json, output to dist/Mega-Brain-Setup-x64.exe.
 *
 * Usage:  node scripts/build-installer.mjs   (npm run build:installer)
 */
import { existsSync, mkdirSync, readFileSync, rmSync, statSync } from 'fs';
import { execFileSync, execSync } from 'child_process';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const staging = resolve(root, 'windows', 'installer', 'staging');
const iss = resolve(root, 'windows', 'installer', 'mega-brain.iss');
const dist = resolve(root, 'dist');
const tmp = resolve(root, '.build');
const zip = resolve(tmp, 'staging.zip');
const version = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf-8')).version;

console.log('[build:installer] limpeza de staging/dist...');
rmSync(staging, { recursive: true, force: true });
rmSync(dist, { recursive: true, force: true });
mkdirSync(staging, { recursive: true });
mkdirSync(dist, { recursive: true });
mkdirSync(tmp, { recursive: true });
rmSync(zip, { force: true });

console.log(`[build:installer] snapshot limpo via git archive (version=${version})...`);
execFileSync('git', ['archive', '--format=zip', '-o', zip, 'HEAD'], { cwd: root, stdio: 'pipe' });
execSync(
  `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '${zip}' -DestinationPath '${staging}' -Force"`,
  { cwd: root, stdio: 'inherit' },
);
rmSync(zip, { force: true });

const candidates = [
  process.env.INNO_SETUP_DIR && resolve(process.env.INNO_SETUP_DIR, 'ISCC.exe'),
  process.env.LOCALAPPDATA && resolve(process.env.LOCALAPPDATA, 'Programs', 'Inno Setup 6', 'ISCC.exe'),
  'C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe',
  'C:\\Program Files\\Inno Setup 6\\ISCC.exe',
].filter(Boolean);
const iscc = candidates.find((p) => existsSync(p));
if (!iscc) {
  console.error('[build:installer] Inno Setup (ISCC.exe) nao encontrado.');
  console.error('  Instale com:  winget install --id JRSoftware.InnoSetup --scope user');
  process.exit(1);
}

console.log('[build:installer] compilando megabrain.iss via ISCC...');
execFileSync(iscc, ['/Q', `/DMyAppVersion=${version}`, iss], { cwd: root, stdio: 'inherit' });

const out = resolve(dist, 'Mega-Brain-Setup-x64.exe');
if (!existsSync(out)) {
  console.error(`[build:installer] instalador nao gerado: ${out}`);
  process.exit(1);
}
const sizeMb = (statSync(out).size / 1024 / 1024).toFixed(1);
console.log(`[build:installer] OK -> ${out} (${sizeMb} MB)`);