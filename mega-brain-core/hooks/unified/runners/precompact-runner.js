'use strict';

const fs = require('fs');
const path = require('path');

async function onPreCompact(context = {}) {
  const projectDir = context.projectDir || process.cwd();
  const sessionId = context.sessionId || 'unknown';
  const transcriptPath = context.transcriptPath;

  // PreCompact must never block Claude Code. Persist a compact, local marker
  // only when the project's memory directory is available.
  try {
    const memoryDir = path.join(projectDir, '.claude', 'memory');
    if (!fs.existsSync(memoryDir)) return { ok: true, skipped: true };

    const digestDir = path.join(memoryDir, 'precompact');
    fs.mkdirSync(digestDir, { recursive: true });
    const payload = {
      sessionId,
      trigger: context.trigger || 'auto',
      transcriptPath: transcriptPath || null,
      timestamp: new Date().toISOString(),
    };
    fs.writeFileSync(path.join(digestDir, `${String(sessionId).replace(/[^a-zA-Z0-9._-]/g, '_')}.json`), JSON.stringify(payload, null, 2), 'utf8');
    return { ok: true };
  } catch (_) {
    return { ok: true, skipped: true };
  }
}

module.exports = { onPreCompact };
