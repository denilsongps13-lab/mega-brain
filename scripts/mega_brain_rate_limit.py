"""LiteLLM 1.100.1 pre-call guard: five Gemini attempts per rolling 60 seconds.

SQLite reserves BEFORE the provider call, including failed attempts. Transactions
coordinate parallel requests and launcher processes; reservations survive restart.
No prompts, keys or responses are stored. Native Router handles fallback/cooldown.
"""
import os
from pathlib import Path
import sqlite3
import time

from litellm import RateLimitError
from litellm.integrations.custom_logger import CustomLogger


class GeminiRateLimit(CustomLogger):
    def __init__(self, database=None, clock=time.time):
        super().__init__()
        self.database = database
        self.clock = clock

    def pre_call_check(self, deployment):
        model = deployment.get('litellm_params', {}).get('model', '')
        if not model.startswith('gemini/'):
            return deployment
        database = self.database or os.environ.get('MEGA_BRAIN_RATE_DB')
        if not database:
            raise RuntimeError('Gemini rate-limit database not configured')
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        now = self.clock()
        with sqlite3.connect(database, timeout=5) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS attempts (at REAL NOT NULL)')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM attempts WHERE at <= ?', (now - 60,))
            used = connection.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            if used >= 5:
                raise RateLimitError('Local Gemini limit: 5 attempts / 60 seconds',
                                     llm_provider='gemini', model=model)
            connection.execute('INSERT INTO attempts VALUES (?)', (now,))
        return deployment

    async def async_pre_call_check(self, deployment, parent_otel_span=None):
        return self.pre_call_check(deployment)


limiter = GeminiRateLimit()
