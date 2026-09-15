"""Tests for lock_utils -- the cross-platform flock shim (engine core).
Pure stdlib, no network.
"""
import os
import tempfile
from pathlib import Path

import pytest

from engine.intelligence.pipeline.lock_utils import (
    LOCK_EX,
    LOCK_NB,
    LOCK_UN,
    flock,
)


def test_constants_exist():
    assert LOCK_EX != 0
    assert LOCK_UN != 0
    assert isinstance(LOCK_NB, int)


def test_flock_on_windows_is_noop_or_works():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "lock-test.txt"
        p.write_text("x", encoding="utf-8")
        fd = os.open(str(p), os.O_RDWR)
        try:
            flock(fd, LOCK_EX)
            flock(fd, LOCK_UN)
        finally:
            os.close(fd)


def test_flock_nonblocking_exclusive_lock_semantics():
    """A second nonblocking exclusive lock must not block the test process."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "lock-test2.txt"
        p.write_text("y", encoding="utf-8")
        fd1 = os.open(str(p), os.O_RDWR)
        fd2 = os.open(str(p), os.O_RDWR)
        try:
            flock(fd1, LOCK_EX)
            if os.name == "nt":
                # Windows shim may treat the same-process lock as a no-op/success.
                flock(fd2, LOCK_EX | LOCK_NB)
                flock(fd2, LOCK_UN)
            else:
                # POSIX flock correctly reports contention for a distinct open file
                # description when LOCK_NB is requested.
                with pytest.raises(BlockingIOError):
                    flock(fd2, LOCK_EX | LOCK_NB)
        finally:
            flock(fd1, LOCK_UN)
            os.close(fd2)
            os.close(fd1)
