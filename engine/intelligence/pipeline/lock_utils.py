"""
engine/intelligence/pipeline/lock_utils.py -- Cross-platform advisory file lock.
==================================================================================

POSIX: delegates to ``fcntl.flock`` (real inter-process locking).
Windows: no-op -- ``fcntl`` does not exist on Windows. This mirrors the
existing ``batch_auto_creator._try_flock`` pattern so callers keep working
unchanged on non-Unix platforms (advisory locking degrades to best-effort).

Exposes ``flock`` plus the ``LOCK_SH / LOCK_EX / LOCK_NB / LOCK_UN``
constants used across the pipeline.

Version: 1.0.0
"""
from __future__ import annotations

try:
    import fcntl as _fcntl

    LOCK_SH: int = _fcntl.LOCK_SH
    LOCK_EX: int = _fcntl.LOCK_EX
    LOCK_NB: int = _fcntl.LOCK_NB
    LOCK_UN: int = _fcntl.LOCK_UN

    def flock(fd, operation: int) -> None:
        """Apply an advisory file lock operation (delegates to fcntl.flock)."""
        _fcntl.flock(fd, operation)

except ImportError:  # Windows / non-Unix platform
    # Dummy constant values (kept aligned with POSIX fcntl bit flags).
    LOCK_SH: int = 1
    LOCK_EX: int = 2
    LOCK_NB: int = 4
    LOCK_UN: int = 8

    def flock(fd, operation: int) -> None:  # type: ignore[misc]
        """No-op fallback for platforms without ``fcntl`` (e.g. Windows)."""
        return None