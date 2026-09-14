"""Canonical, sanitized execution journal. Never reads credential files."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_SECRET = re.compile(r'key|token|password|passwd|secret|authorization|credential', re.I)
_ASSIGNMENT = re.compile(r'''(?ix)([\w.-]*(?:api[_-]?key|token|password|passwd|secret|authorization|credential)[\w.-]*["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')
_BEARER = re.compile(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/_.=-]+')
_LOCK = threading.Lock()


def redact(value):
    """Redact structured secrets, labelled text, and loaded credential values."""
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if _SECRET.search(str(k)) else redact(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    for key, secret in sorted(os.environ.items(), key=lambda p: len(p[1]), reverse=True):
        if _SECRET.search(key) and secret:
            value = value.replace(secret, '[REDACTED]')
    value = re.sub(r'(?i)(--[\w-]*(?:key|token|password|secret)[\w-]*\s+)(?:"[^"\n]*"|[^\s]+)', r'\1[REDACTED]', value)
    value = _BEARER.sub(r'\1 [REDACTED]', value)
    value = _ASSIGNMENT.sub(r'\1[REDACTED]', value)
    value = re.sub(r'(?i)(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', value)
    value = re.sub(r'\b(?:AIza[\w-]{25,}|gsk_[\w-]+|sk-[\w-]{12,})', '[REDACTED]', value)
    value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED]', value, flags=re.S)
    return value


def failure_reason(result):
    return str(result.get('error') or result.get('reason') or result.get('stderr')
               or result.get('stdout') or f"tool failed (exit code {result.get('exit_code', 'unavailable')})")


class ExecutionJournal:
    def __init__(self, memory_dir):
        self.path = Path(memory_dir).resolve() / 'execution.jsonl'

    def append(self, record):
        safe = redact({'timestamp': datetime.now(timezone.utc).isoformat(), **record})
        encoded = json.dumps(safe, ensure_ascii=False, default=str) + '\n'
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        return safe

    def recent(self, limit=20):
        from collections import deque
        if not self.path.exists():
            return []
        with self.path.open(encoding='utf-8') as stream:
            lines = deque(stream, maxlen=max(1, min(int(limit), 100)))
        return [redact(json.loads(line)) for line in lines if line.strip()]
