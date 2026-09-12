'use strict';

const path = require('path');
const fs = require('fs');

function buildHookOutput(xml) {
  return {
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: xml || '',
    },
  };
}

function resolveHookRuntime(input) {
  const cwd = input && input.cwd;
  const sessionId = input && (input.session_id || input.sessionId);
  if (!cwd || typeof cwd !== 'string') return null;
  const synapsePath = path.join(cwd, '.synapse');
  if (!fs.existsSync(synapsePath)) return null;

  const candidates = ['mega-brain-core', '.aiox-core', '.xoia-core'];
  for (const core of candidates) {
    try {
      const base = path.join(cwd, core, 'core', 'synapse');
      const { loadSession, cleanStaleSessions } = require(path.join(base, 'session', 'session-manager.js'));
      const { SynapseEngine } = require(path.join(base, 'engine.js'));
      const sessionsDir = path.join(synapsePath, 'sessions');
      const session = loadSession(sessionId, sessionsDir) || { prompt_count: 0 };
      if (session.prompt_count === 0 && typeof cleanStaleSessions === 'function') {
        try { cleanStaleSessions(sessionsDir, 168); } catch (_) {}
      }
      return { engine: new SynapseEngine(synapsePath), session, sessionId, sessionsDir, cwd };
    } catch (_) {}
  }
  return null;
}

function finalizeHookSession(runtime, input, result) {
  if (!runtime) return;
  try {
    const candidates = ['mega-brain-core', '.aiox-core', '.xoia-core'];
    for (const core of candidates) {
      try {
        const manager = require(path.join(runtime.cwd, core, 'core', 'synapse', 'session', 'session-manager.js'));
        const save = manager.saveSession || manager.persistSession;
        if (typeof save === 'function') {
          const session = Object.assign({}, runtime.session, result && result.session ? result.session : {});
          save(runtime.sessionId, session, runtime.sessionsDir);
          return;
        }
      } catch (_) {}
    }
  } catch (_) {}
}

function detectActivationSkill() { return null; }
async function runActivationPipeline() { return ''; }

module.exports = {
  resolveHookRuntime,
  buildHookOutput,
  finalizeHookSession,
  detectActivationSkill,
  runActivationPipeline,
};
