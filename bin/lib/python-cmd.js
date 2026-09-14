/**
 * bin/lib/python-cmd.js -- Cross-platform Python 3 resolution.
 *
 * Centralizes the "which python" probe that was copy-pasted across
 * installer.js / setup-wizard.js / mega-brain-doctor.js so the runtime
 * dispatch path (mega-brain.js) and npm scripts use the SAME logic.
 *
 * Priority (fastest-first, matches the rest of the toolchain):
 *   1. `python3`   (macOS / Linux / POSIX)
 *   2. `python`    (Windows Store alias / virtualenvs)
 *   3. `py -3`     (Windows Python Launcher)
 *
 * Exports:
 *   resolvePythonCmd()   -> cmd array or null (probe once, cached)
 *   runWithPython(args, opts?) -> spawnSync helper returning child result
 */
import { spawnSync } from 'child_process';

let cached = null;

function probe(cmd) {
  const result = spawnSync(cmd, ['--version'], {
    encoding: 'utf-8',
    timeout: 15000,
    stdio: 'pipe',
  });
  const out = `${result.stdout || ''}${result.stderr || ''}`.toLowerCase();
  return !result.error && out.includes('python 3') ? cmd : null;
}

/** Return the Python command array (e.g. ['py', '-3']) or null if none. */
export function resolvePythonCmd() {
  if (cached !== null) return cached;
  for (const candidate of [['python3'], ['python'], ['py', '-3']]) {
    if (probe(candidate[0])) {
      cached = candidate;
      return cached;
    }
  }
  cached = null;
  return null;
}

/**
 * Spawn a Python process with the extra args. Returns the same result shape
 * as spawnSync (stdout/stderr/status/error). Throws a clear Error when no
 * Python 3 interpreter is available.
 */
export function runWithPython(args, opts = {}) {
  const py = resolvePythonCmd();
  if (!py) {
    throw new Error(
      'Python 3 não detectado. Instale em https://www.python.org/downloads ' +
        'ou via `winget install Python.Python.3.13`.'
    );
  }
  const [cmd, ...pyArgs] = py;
  return spawnSync(cmd, [...pyArgs, ...args], {
    encoding: 'utf-8',
    timeout: 120000,
    stdio: 'inherit',
    ...opts,
  });
}