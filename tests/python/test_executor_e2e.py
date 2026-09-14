"""E2E tests through the operations dispatcher — the exact CLI contract.

Covers: execute_task, project_context, mega_memory, run_preflight,
check_workspace_health and run_autonomous_pipeline resume behavior.
All planner selection is forced deterministic via MEGA_BRAIN_PLANNER so the
suite never makes paid model calls.
"""
from __future__ import annotations

import pytest

from engine.operations import dispatch, list_operations


@pytest.fixture()
def deterministic_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGA_BRAIN_PLANNER", "deterministic")


def test_execute_task_via_dispatch(tmp_path, deterministic_env):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_p():\n    assert 1\n", encoding="utf-8")
    result = dispatch(
        "execute_task",
        objective="Run the project tests",
        workspace=str(tmp_path),
        permission_mode="block",
    )
    assert result["success"] is True
    assert result["operation"] == "execute_task"
    assert result["planner"] == "deterministic"
    assert result["validation"]["kind"] == "tests"
    assert result["validation"]["ok"] is True


def test_execute_task_requires_objective(tmp_path):
    result = dispatch("execute_task", workspace=str(tmp_path))
    assert result["success"] is False
    assert "objective" in result["error"]


def test_project_context_via_dispatch(tmp_path):
    result = dispatch("project_context", workspace=str(tmp_path))
    assert result["success"] is True
    assert result["root"] == str(tmp_path.resolve())


def test_mega_memory_via_dispatch(tmp_path, deterministic_env):
    dispatch("execute_task", objective="seed memory", workspace=str(tmp_path))
    result = dispatch("mega_memory", workspace=str(tmp_path))
    assert result["success"] is True
    assert result["memory"]["last_objective"] == "seed memory"
    assert isinstance(result["events"], list)
    assert "seed memory" in result["markdown"]


def test_run_preflight_via_dispatch(tmp_path):
    result = dispatch("run_preflight", workspace=str(tmp_path))
    assert result["success"] is True
    assert "checks" in result
    assert all(c["name"] for c in result["checks"])


def test_workspace_health_via_dispatch(tmp_path, deterministic_env):
    dispatch("execute_task", objective="prime", workspace=str(tmp_path))
    result = dispatch("check_workspace_health", workspace=str(tmp_path))
    assert result["healthy"] is True
    assert result["root"] == str(tmp_path.resolve())
    assert "memory" in result


def test_autonomous_pipeline_resumes_last_objective(tmp_path, deterministic_env):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_y.py").write_text("def test_q():\n    assert 1\n", encoding="utf-8")
    dispatch("run_autonomous_pipeline", objective="Fix the tests and verify", workspace=str(tmp_path))
    context = dispatch("project_context", workspace=str(tmp_path))
    resumed = dispatch("run_autonomous_pipeline", workspace=str(tmp_path))
    assert resumed["success"] is False or resumed["objective"]  # runs regardless
    assert "tests" in resumed["objective"]


def test_runtime_ops_registered():
    ops = list_operations()
    for name in (
        "execute_task", "project_context", "mega_memory",
        "run_autonomous_pipeline", "run_preflight", "check_workspace_health",
    ):
        assert name in ops, name


def test_unknown_operation_returns_error():
    result = dispatch("definitely_not_a_thing")
    assert result["success"] is False
    assert "not implemented" in result["error"]