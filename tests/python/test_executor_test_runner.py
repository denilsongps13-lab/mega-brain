"""Tests for the platform-aware test runner detection (`engine.executor.test_runner`).

Covers: python launcher resolution, npm test gating on a declared ``test``
script, pytest detection, concrete pytest command targeting, and the masking
fix — a failing ``npm test`` must never be silently replaced by a pytest run.
"""
from __future__ import annotations

import json
import os

import pytest

from engine.executor import test_runner as tr
from engine.executor.permissions import PermissionGate
from engine.executor.test_runner import (
    detect_test_command,
    npm_runner,
    pytest_command,
    python_launcher,
)
from engine.executor.tools import ScopedTools

ALLOWED_LAUNCHERS = {"py", "python", "python3"}

npm_token = "npm.cmd" if os.name == "nt" else "npm"

def _write_pkg(workspace, scripts: dict | None):
    (workspace / "package.json").write_text(
        json.dumps({"scripts": scripts or {}}), encoding="utf-8"
    )


def test_python_launcher_available_and_real():
    launcher = python_launcher()
    assert launcher, "expected a reachable python launcher"
    assert launcher[0] in ALLOWED_LAUNCHERS
    assert tr.shutil.which(launcher[0])


def test_npm_runner_requires_declared_test_script(tmp_path):
    _write_pkg(tmp_path, {"test": "echo hi"})
    assert npm_runner(tmp_path) == f"{npm_token} test"
    _write_pkg(tmp_path, {"build": "echo hi"})
    assert npm_runner(tmp_path) is None
    (tmp_path / "package.json").unlink()
    assert npm_runner(tmp_path) is None


def test_detect_prefers_npm_when_declared(tmp_path):
    _write_pkg(tmp_path, {"test": "echo hi"})
    (tmp_path / "tests").mkdir()
    assert detect_test_command(tmp_path) == f"{npm_token} test"


def test_detect_pytest_for_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    launcher = python_launcher()
    assert detect_test_command(tmp_path) == " ".join(launcher) + " -m pytest -q"


def test_detect_pytest_for_pytest_ini(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    launcher = python_launcher()
    assert detect_test_command(tmp_path) == " ".join(launcher) + " -m pytest -q"


def test_detect_none_when_nothing_configured(tmp_path):
    assert detect_test_command(tmp_path) is None


def test_pytest_command_targets_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    command = pytest_command(tmp_path)
    assert command is not None
    assert "tests" in command
    assert command.endswith(f'"{str((tmp_path / "tests").resolve())}"')


def test_pytest_command_targets_workspace_without_tests_dir(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_it():\n    assert 1\n", encoding="utf-8")
    command = pytest_command(tmp_path)
    assert command is not None
    assert command.endswith(f'"{str(tmp_path.resolve())}"')


def test_failing_npm_test_is_not_masked_by_pytest(tmp_path):
    _write_pkg(tmp_path, {"test": "exit 1"})
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "tests" / "test_pass.py").write_text(
        "def test_it():\n    assert 1\n", encoding="utf-8"
    )
    tools = ScopedTools(str(tmp_path), gate=PermissionGate(str(tmp_path), mode="block"))
    res = tools.run_tests(timeout=120)
    assert res.get("runner") == "npm"
    assert not res.get("ok")
    assert res.get("exit_code") != 0
    assert "summary" not in res


def test_successful_npm_test_reports_npm_runner(tmp_path):
    _write_pkg(tmp_path, {"test": "exit 0"})
    tools = ScopedTools(str(tmp_path), gate=PermissionGate(str(tmp_path), mode="block"))
    res = tools.run_tests(timeout=120)
    assert res.get("runner") == "npm"
    assert res.get("ok")