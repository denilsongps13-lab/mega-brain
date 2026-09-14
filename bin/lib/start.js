// bin/lib/start.js
// mega-brain start — validate the local environment and print status.
// Deliberately dependency-free (no chalk/boxen/ora) so it works before
// `npm install` and inside any Windows shell.

import { execFileSync } from 'child_process';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';
import { existsSync } from 'fs';

const line = (s = '') => console.log(s);
const badge = (ok, label) => `  ${ok ? '[OK]' : '[ERR]'} ${label}`;

function runProbe(pythonCmd, root) {
  const script = `import json,sys\nsys.path.insert(0, ${JSON.stringify(root)})\nfrom engine.executor.context import load_project_context\ntry:\n    print(json.dumps(load_project_context(${JSON.stringify(root)}), default=str))\nexcept Exception as e:\n    print(json.dumps({"error": str(e)}))`;
  try {
    return JSON.parse(execFileSync(pythonCmd[0], [...pythonCmd.slice(1), '-c', script], {
      cwd: root,
      encoding: 'utf-8',
      env: { ...process.env, PYTHONPATH: root },
      timeout: 30000,
    }).trim() || '{}');
  } catch (e) {
    return { error: String(e && e.message || e) };
  }
}

export async function runStart(version) {
  const here = dirname(fileURLToPath(import.meta.url));
  const root = resolve(here, '..', '..');
  let failures = [];

  line();
  line(`  Mega Brain v${version} — local runtime status`);
  line(`  Workspace: ${root}`);
  line();

  const { resolvePythonCmd } = await import('./python-cmd.js');
  const pythonCmd = resolvePythonCmd();
  if (pythonCmd) {
    line(badge(true, `Python: ${pythonCmd.join(' ')}`));
  } else {
    line(badge(false, 'Python not detected (py -3 / python3 / python)'));
    failures.push('python');
  }

  line(badge(existsSync(resolve(root, 'package.json')), 'package.json present'));
  line(badge(fsHasDir(root, 'engine'), 'engine/ present'));
  line(badge(fsHasDir(root, 'tests'), 'tests/ present'));

  if (pythonCmd) {
    const ctx = runProbe(pythonCmd, root);
    if (ctx.error) {
      line(badge(false, `engine probe failed: ${ctx.error}`));
      failures.push('engine');
    } else {
      line(badge(true, `git: ${ctx.is_git_repo ? ctx.branch + ' @ ' + ctx.last_commit : 'no repo'}`));
      line(badge(true, `dirty files: ${ctx.dirty_files ?? 0}`));
      line(badge(Boolean(ctx.test_command), `tests: ${ctx.test_command || 'none detected'}`));
      line(`  [--] models: Gemini=${ctx.llm_gemini} Groq=${ctx.llm_groq} (offline -> deterministic planner)`);
      line(badge(Boolean(ctx.store_dir), `memory: ${ctx.store_dir}`));
      if (ctx.memory && ctx.memory.last_objective) {
        line(badge(true, `last objective: ${ctx.memory.last_objective}`));
      }
      const pending = (ctx.memory && ctx.memory.next_steps) || [];
      if (pending.length) {
        line(badge(true, `pending next steps: ${pending.length}`));
      }
    }
  }

  line();
  if (failures.length) {
    line(`  ${failures.length} check(s) failed. Run: mega-brain doctor`);
    if (!pythonCmd) line('  Install Python 3.13+ and re-run this command.');
    process.exitCode = 1;
  } else {
    line('  Runtime: READY');
    line();
    line('  Send a task:');
    line('    mega-brain execute "analise este projeto e corrija os testes"');
    line('  Inspect context / memory:');
    line('    mega-brain context       (project + git + resume memory)');
    line('    mega-brain memory        (persisted project memory)');
    line('    mega-brain preflight     (environment checks)');
    line('    mega-brain status        (license / pro status)');
    line();
  }
}

function fsHasDir(root, name) {
  try {
    return existsSync(resolve(root, name));
  } catch {
    return false;
  }
}