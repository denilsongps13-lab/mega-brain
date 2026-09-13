/** Portable hook runner. Preserve stdin/stdout/stderr and the hook's exit code. */
const {spawnSync} = require('node:child_process');
const {existsSync} = require('node:fs');
const path = require('node:path');
const name = process.argv[2];
if (!name || !/^[a-zA-Z0-9_-]+\.(py|sh|js)$/.test(name)) {
  console.error('Mega Cerebro: nome de hook invalido.'); process.exit(2);
}
const script = path.join(__dirname, name);
if (!existsSync(script)) { console.error('Mega Cerebro: hook ausente.'); process.exit(2); }
let executable, args;
if (name.endsWith('.py')) {
  executable = process.env.MEGA_BRAIN_PYTHON;
  if (!executable) {
    for (const candidate of (process.platform === 'win32' ? ['python', 'py', 'python3'] : ['python3', 'python'])) {
      const prefix = candidate === 'py' ? ['-3'] : [];
      const probe = spawnSync(candidate, [...prefix, '--version'], {encoding: 'utf8', windowsHide: true});
      if (probe.status === 0 && /Python 3\./.test(probe.stdout + probe.stderr)) {
        executable = candidate; args = [...prefix, script]; break;
      }
    }
  }
  args ||= [script];
} else if (name.endsWith('.sh')) {
  executable = process.env.CLAUDE_CODE_GIT_BASH_PATH || 'bash'; args = [script.replace(/\\/g, '/')];
} else { executable = process.execPath; args = [script]; }
if (!executable) { console.error('Mega Cerebro: Python 3 indisponivel.'); process.exit(2); }
const result = spawnSync(executable, [...args, ...process.argv.slice(3)], {
  cwd: path.resolve(__dirname, '../..'), stdio: 'inherit', windowsHide: true,
  env: {...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8'},
});
if (result.error) { console.error('Mega Cerebro: nao foi possivel executar o hook.'); process.exit(2); }
process.exit(result.status === null ? 2 : result.status);
