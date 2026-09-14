"""Test runner detection for the local runtime — platform-aware.

Why this exists
---------------
The executor must be able to run the workspace's test suite on any of the
platforms Mega Brain supports (macOS / Linux / Windows). The repo already
resolves Python cross-platform via ``bin/lib/python-cmd.js`` (python3 first,
then python, then the ``py -3`` launcher); this module mirrors that order in
Python so the executor's ``run_tests`` / ``detect_test_command`` pick the
same interpreter instead of hardcoding ``py -3`` / ``npm.cmd``.

Rules
-----
  - pytest runs under ``python3`` / ``python`` / ``py -3`` depending on what
    is actually on PATH (never assume a launcher exists).
  - ``npm test`` is used only when ``package.json`` declares a ``test``
    script; the runner token is ``npm`` on POSIX and ``npm.cmd`` on Windows.
  - detection is shared with ``engine.executor.context`` so the displayed
    command and the executed command can never diverge.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# Mirror lib/python-cmd.js: fastest-first, platform aware.
_LAUNCHER_CANDIDATES = (["python3"], ["python"], ["py", "-3"])

_PYTEST_CONFIG_FILES = ("pytest.ini", "pyproject.toml", "tox.ini", "conftest.py")


def python_launcher() -> list[str] | None:
    """First *working* python command (e.g. ``["py", "-3"]`` on Windows launcher).

    ``shutil.which`` alone is not enough: Windows Store aliases (``python3``/
    ``python``) resolve but either fail a probe or only work as bare tokens.
    Concretely, ``WindowsApps\\python.EXE`` runs fine as ``python`` but exits
    with code 9009 ("not recognized") when invoked by full path — and the
    executor always resolves executables to full paths. Alias-backed launchers
    are therefore excluded; each remaining candidate is probed with
    ``--version`` (same strategy as ``bin/lib/python-cmd.js``).
    """
    for candidate in _LAUNCHER_CANDIDATES:
        resolved = shutil.which(candidate[0])
        if resolved is None:
            continue
        if os.name == "nt" and "WindowsApps" in resolved:
            continue
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        try:
            proc = subprocess.run(
                [*candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return candidate
    return None


def _pkg_json(workspace: Path) -> dict:
    try:
        return json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def npm_runner(workspace: Path) -> str | None:
    """``npm test`` (or ``npm.cmd test`` on Windows) when a test script exists."""
    if not _pkg_json(workspace).get("scripts", {}).get("test"):
        return None
    return "npm.cmd test" if os.name == "nt" else "npm test"


def pytest_configured(workspace: Path) -> bool:
    return (workspace / "tests").is_dir() or any(
        (workspace / cfg).is_file() for cfg in _PYTEST_CONFIG_FILES
    )


def detect_test_command(workspace: Path) -> str | None:
    """Human/diagnostic representation of the detected test command."""
    npm = npm_runner(workspace)
    if npm:
        return npm
    if pytest_configured(workspace):
        launcher = python_launcher()
        if launcher:
            return " ".join(launcher) + " -m pytest -q"
    return None


def pytest_command(workspace: Path) -> str | None:
    """Concrete ``python -m pytest -q --tb=short <target>`` command."""
    launcher = python_launcher()
    if launcher is None:
        return None
    tests_dir = (workspace / "tests").resolve()
    target = tests_dir if tests_dir.is_dir() else workspace.resolve()
    base = " ".join(launcher) + " -m pytest -q --tb=short"
    return f'{base} "{target}"'


__all__ = [
    "python_launcher",
    "npm_runner",
    "pytest_configured",
    "detect_test_command",
    "pytest_command",
]