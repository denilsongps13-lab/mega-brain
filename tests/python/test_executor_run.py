"""Tests for the TaskExecutor flow: plan -> execute -> validate -> remember.

Covered: clean manual run, failing/blocked step -> next_steps + errors, the
same-cause retry cap (max_attempts, no infinite loop), tests-based validation,
and memory state transitions (objective rotation, session end).
"""
from __future__ import annotations

import pytest

from engine.executor.executor import TaskExecutor, execute_objective


class StubPlanner:
    kind = "stub"
    def __init__(self, steps, validation="manual"):
        self.steps = steps
        self.validation = validation

    def plan(self, objective, context):
        return {
            "goal": objective,
            "steps": [dict(s, id=s.get("id", f"s{i}")) for i, s in enumerate(self.steps, 1)],
            "validation": self.validation,
            "planner": "stub",
        }


def test_clean_manual_run(tmp_path):
    stub = StubPlanner([{"action": "write", "params": {"path": "note.txt", "content": "hi"}}])
    res = execute_objective("draft a note", workspace=str(tmp_path), planner=stub)
    assert res["success"] is True
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hi"
    assert res["validation"]["kind"] == "manual"
    state = res["memory"]
    assert state["current_objective"] is None  # ended cleanly
    assert state["last_objective"] == "draft a note"
    assert state["completed"][-1]["task"] == "draft a note"


def test_blocked_step_marks_run_not_clean(tmp_path):
    stub = StubPlanner(
        [{"action": "write", "params": {"path": ".env", "content": "SECRET=1"}}]
    )
    res = execute_objective("edit env", workspace=str(tmp_path), planner=stub)
    assert res["success"] is False
    step = res["steps"][0]
    assert step["blocked"] is True
    assert res["errors"]
    assert res["next_steps"]
    # .env untouched
    assert not (tmp_path / ".env").exists()
    assert res["memory"]["current_objective"] == "edit env"


def test_retry_capped_on_same_cause(tmp_path):
    (tmp_path / "f.txt").write_text("abc", encoding="utf-8")
    stub = StubPlanner(
        [{"action": "edit", "params": {"path": "f.txt", "old": "zz", "new": "xx"}}]
    )
    executor = TaskExecutor(str(tmp_path), planner=stub, max_attempts=3)
    res = executor.run("fix f")
    attempts = [r for r in res["steps"] if r["step_id"] == "s1"]
    assert len(attempts) == 3  # same-cause retry capped
    assert attempts[-1]["ok"] is False
    assert res["success"] is False


def test_transient_failure_recovered_by_retry__run_is_clean(tmp_path):
    stub = StubPlanner([{"action": "run_tests", "params": {}}], validation="tests")
    executor = TaskExecutor(str(tmp_path), planner=stub, max_attempts=2)
    calls = {"n": 0}

    def flaky_run_tests(timeout=600):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "error": "transient failure", "exit_code": 1}
        return {"ok": True, "exit_code": 0, "runner": "stub"}

    executor.tools.run_tests = flaky_run_tests
    res = executor.run("flaky tests")
    attempts = [r for r in res["steps"] if r["step_id"] == "s1"]
    assert len(attempts) == 2
    assert attempts[0]["ok"] is False
    assert attempts[1]["ok"] is True
    assert res["errors"] == []  # transient retry that recovered is NOT an error
    assert res["success"] is True
    assert res["validation"]["ok"] is True
    assert res["next_steps"] == []


def test_tests_validation_requires_green(tmp_path):
    (tmp_path / "test_a.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    stub = StubPlanner(
        [
            {"action": "write", "params": {"path": "x.txt", "content": "1"}},
            {"action": "run_tests", "params": {}},
        ],
        validation="tests",
    )
    res = execute_objective("ensure green", workspace=str(tmp_path), planner=stub)
    assert res["validation"]["kind"] == "tests"
    assert res["validation"]["ok"] is True
    assert res["success"] is True


def test_tests_validation_fails_when_no_test_step_ran(tmp_path):
    stub = StubPlanner(
        [{"action": "write", "params": {"path": "x.txt", "content": "1"}}],
        validation="tests",
    )
    res = execute_objective("untested", workspace=str(tmp_path), planner=stub)
    assert res["validation"]["kind"] == "tests"
    assert res["validation"]["ok"] is False
    assert res["success"] is False


def test_deterministic_planner_full_run_no_api(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "engine.intelligence.pipeline.mce.llm_router.is_provider_available", lambda p: False
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_it.py").write_text(
        "def test_passes():\n    assert 1 == 1\n", encoding="utf-8"
    )
    executor = TaskExecutor(str(tmp_path))
    res = executor.run("Inspect project and run the tests")
    assert res["planner"] == "deterministic"
    assert res["success"] is True
    assert res["validation"]["kind"] == "tests"
    assert res["steps"][0]["action"] == "context"


def test_resume_without_objective(tmp_path):
    executor = TaskExecutor(str(tmp_path))
    executor.run("primary objective")
    resumed = TaskExecutor(str(tmp_path)).run()
    assert resumed["objective"] == "primary objective"  # continues from memory


def test_context_step_produces_info(tmp_path):
    stub = StubPlanner([{"action": "context", "params": {}}])
    res = execute_objective("dive", workspace=str(tmp_path), planner=stub)
    assert res["success"] is True
    assert res["steps"][0]["action"] == "context"