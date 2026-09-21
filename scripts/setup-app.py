#!/usr/bin/env python3
"""Create local deployment configuration without printing secrets or overwriting it."""
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / '.env.app'
content = '\n'.join([
    '# Private deployment config. Never commit this file.',
    'POSTGRES_PASSWORD=' + secrets.token_urlsafe(32),
    'APP_ACCESS_TOKEN=' + secrets.token_urlsafe(48),
    'APP_ORIGINS=http://localhost:8080',
    'GEMINI_API_KEY=', 'GROQ_API_KEY=', 'ANTHROPIC_API_KEY=', 'OPENAI_API_KEY=',
    'MCE_LLM_PROVIDER=gemini', '',
])
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print('.env.app already exists; preserved.')
else:
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    print('Created .env.app. Configure providers there and use APP_ACCESS_TOKEN to sign in.')
