"""Tests for lock_utils -- the cross-platform flock shim (engine core).
Pure stdlib, no network.
"""
import os
import pytest
import tempfile
from pathlib import Path

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
    # On Windows msvcrt is used (no fcntl); on POSIX a real lock is taken.
    # Either way it must not raise on a normal file.
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "lock-test.txt"
        p.write_text("x", encoding="utf-8")
        fd = os.open(str(p), os.O_RDWR)
        try:
            flock(fd, LOCK_EX)  # must not raise
            flock(fd, LOCK_UN)
        finally:
            os.close(fd)


def test_exclusive_lock_contends_then_releases():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "lock-test2.txt"
        p.write_text("y", encoding="utf-8")
        fd = os.open(str(p), os.O_RDWR)
        try:
            flock(fd, LOCK_EX)
            # Independent opens contend on POSIX; Windows currently documents a no-op.
            fd2 = os.open(str(p), os.O_RDWR)
            try:
                if os.name != "nt":
                    with pytest.raises(BlockingIOError):
                        flock(fd2, LOCK_EX | LOCK_NB)
                flock(fd, LOCK_UN)
                flock(fd2, LOCK_EX | LOCK_NB)
                flock(fd2, LOCK_UN)
            finally:
                os.close(fd2)
        finally:
            os.close(fd)