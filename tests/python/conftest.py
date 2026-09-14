"""Shared pytest config: ensure repo root on sys.path so ``engine.*`` imports.

The suite is executed from the repo root via ``python -m pytest tests/python/``,
so this is a safety net for bare ``pytest`` invocations.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))