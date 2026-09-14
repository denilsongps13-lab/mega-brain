"""
engine/config.py -- Canonical configuration access for Mega Brain.
==================================================================

Single accessor for configuration values, used across the engine:

    from engine.config import get_config

    api_key = get_config("OPENAI_API_KEY")
    voice   = get_config("ELEVENLABS_VOICE_ID", "your-voice-id-here")
    expand  = get_config("RAG_QUERY_EXPANSION", default="0")

Hierarchy (mirrors scripts/ingest-with-entity-discovery.py):

  os.environ  system env vars win
  > REPO/.env file (.env is gitignored; parsed with stdlib, idempotent, fail-open)
  > default argument

No third-party dependencies (python-dotenv intentionally NOT used).

Version: 1.0.0
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_REPO_ROOT: Path = Path(__file__).resolve().parent.parent
_DOTENV_PATH: Path = _REPO_ROOT / ".env"
_DOTENV_LOADED: bool = False


def _bootstrap_env_from_dotenv() -> None:
    """Populate ``os.environ`` from ``REPO / .env`` (idempotent, fail-open).

    Idempotent: system env vars already set are never overwritten, and the
    file is only re-read on the first call (runtime-mutable env is always
    observed after that). Fail-open: a missing or unreadable .env is a no-op.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    if not _DOTENV_PATH.exists():
        return
    try:
        for raw in _DOTENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def get_config(key: str, default: Any = None) -> Any:
    """Return the effective value for a configuration key.

    Resolution order: ``os.environ`` -> ``REPO/.env`` -> ``default``.

    Args:
        key: Configuration key (matches a .env / environment variable name).
        default: Value returned when the key is not configured anywhere.

    Returns:
        The raw string value, or ``default`` when unset.
    """
    _bootstrap_env_from_dotenv()
    return os.environ.get(key, default)