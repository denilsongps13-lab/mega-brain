#!/usr/bin/env node
/**
 * bin/run-python.js -- npm-script friendly Python runner.
 *
 * Usage:  node bin/run-python.js -m pytest tests/python/ -v
 *         node bin/run-python.js engine/intelligence/validation/validate_json_integrity.py
 *
 * Resolves the Python interpreter exactly like lib/python-cmd.js and forwards
 * all remaining args. Exits with the child's exit code.
 */
import { resolvePythonCmd, runWithPython } from './lib/python-cmd.js';

const args = process.argv.slice(2);
if (!resolvePythonCmd()) {
  console.error(
    '\n  Python 3 não detectado. Configure python3 (POSIX) ou py -3 (Windows).\n'
  );
  process.exit(1);
}
const result = runWithPython(args);
process.exit(result.status ?? 1);