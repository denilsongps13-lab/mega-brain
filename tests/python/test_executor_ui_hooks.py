"""UI-hooks tests for the executor: phase_observer, confirmer and Gemini->Groq fallback.

Covered:
  1. phase_observer receives every lifecycle phase in the correct order.
  2. confirmer returning True on ``ask`` verdicts authorises the step.
  3. confirmer returning False leaves the step blocked.
  4. Gemini 429 transient error routes through the Groq fallback *inside*
     the executor, while still emitting the expected lifecycle phases
     (demonstrating the full Interface -> executor -> router -> tools path
     without any real network call).
"""
from __future__ import annotations

import json

import pytest

from engine.executor.executor import TaskExecutor, execute_objective
from engine.executor.permissions import PermissionGate

OrderedSteps = list[str]


class _RecorderPlanner:
    """Return a deterministic two-step plan and track kind."""

    kind = "recorder"

    def plan(self, objective: str, context: dict) -> dict:
        return {
            "goal": objective,
            "steps": [
                {"id": "s1", "action": "context", "params": {}},
                {"id": "s2", "action": "write", "params": {"path": "ok.txt", "content": "done"}},
            ],
            "validation": "manual",
            "planner": "recorder",
        }


class _AskPlanner:
    """Return one ``ask``-level delete step (subfolder file)."""

    kind = "ask"

    def plan(self, objective: str, context: dict) -> dict:
        return {
            "goal": objective,
            "steps": [
                {"id": "s1", "action": "delete", "params": {"path": "sub/keeper.txt"}},
            ],
            "validation": "manual",
            "planner": "ask",
        }


# ---------------------------------------------------------------------------
# phase_observer
# ---------------------------------------------------------------------------

def test_phase_observer_receives_all_lifecycle_phases(tmp_path):
    """Full clean run must emit thinking -> planning -> executing(s) -> validating -> done."""
    stub = _RecorderPlanner()
    phases: list[str] = []

    def observer(name: str, payload):
        phases.append(name)

    res = execute_objective(
        "lifecycle check",
        workspace=str(tmp_path),
        planner=stub,
        phase_observer=observer,
    )
    assert res["success"] is True
    # _RecorderPlanner produces 2 steps → two "executing" entries
    assert phases == [
        "thinking", "planning", "executing", "executing", "validating", "done",
    ]


def test_phase_observer_payload_has_step_details(tmp_path):
    stub = _RecorderPlanner()
    payloads: list = []

    def observer(name: str, payload):
        payloads.append((name, payload or {}))

    res = execute_objective(
        "step details",
        workspace=str(tmp_path),
        planner=stub,
        phase_observer=observer,
    )
    assert res["success"] is True
    exec_payloads = [p for n, p in payloads if n == "executing"]
    assert len(exec_payloads) == 2
    # first step
    assert exec_payloads[0]["action"] == "context"
    assert exec_payloads[0]["step"] == 1
    assert exec_payloads[0]["total"] == 2
    # second step
    assert exec_payloads[1]["action"] == "write"
    assert exec_payloads[1]["step"] == 2


def test_phase_observer_none_does_not_break(tmp_path):
    """phase_observer=None must work identically to prior behaviour."""
    res = execute_objective(
        "no observer", workspace=str(tmp_path), planner=_RecorderPlanner()
    )
    assert res["success"] is True


# ---------------------------------------------------------------------------
# confirmer
# ---------------------------------------------------------------------------

def test_confirmer_allows_ask_verdict(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "keeper.txt").write_text("k", encoding="utf-8")
    stub = _AskPlanner()
    gate = PermissionGate(tmp_path, mode="ask", confirmer=lambda reason: True)
    decision = gate.check_step("delete", {"path": str(sub / "keeper.txt")})
    allowed, needs_confirm, reason = gate.decide(decision)
    assert allowed is True
    assert needs_confirm is False

    res = execute_objective(
        "allow delete",
        workspace=str(tmp_path),
        planner=stub,
        permission_mode="ask",
        confirmer=lambda reason: True,
    )
    assert res["success"] is True
    assert res["steps"][0]["blocked"] is False
    assert not (sub / "keeper.txt").exists()


def test_confirmer_denies_ask_verdict(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "keeper.txt").write_text("k", encoding="utf-8")
    stub = _AskPlanner()
    res = execute_objective(
        "deny delete",
        workspace=str(tmp_path),
        planner=stub,
        permission_mode="ask",
        confirmer=lambda reason: False,
    )
    assert res["success"] is False
    step = res["steps"][0]
    assert step["blocked"] is True
    assert (sub / "keeper.txt").exists()


# ---------------------------------------------------------------------------
# Gemini -> Groq fallback inside executor
# ---------------------------------------------------------------------------

def _transient_429(prompt, **kw):
    raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded for gemini")


def _fake_groq_plan(prompt, **kw):
    return json.dumps({
        "goal": "test fallback",
        "steps": [
            {"id": "g1", "action": "write", "params": {"path": "fallback.txt", "content": "from groq"}}
        ],
        "validation": "manual",
    })


def test_fallback_gemini_to_groq_through_executor(tmp_path, monkeypatch):
    """Gemini transient 429 triggers Groq fallback *inside* the router which
    is invoked by the LLMPlanner, proving the full GUI -> executor fallback."""
    monkeypatch.setattr(
        "engine.intelligence.pipeline.mce.llm_router.is_provider_available",
        lambda p: True,
    )
    monkeypatch.setattr(
        "engine.intelligence.pipeline.mce.llm_router._run_gemini",
        _transient_429,
    )
    monkeypatch.setattr(
        "engine.intelligence.pipeline.mce.llm_router._run_groq",
        _fake_groq_plan,
    )
    phases: list[str] = []

    def observer(name: str, payload):
        phases.append(name)

    res = execute_objective(
        "trigger fallback",
        workspace=str(tmp_path),
        permission_mode="block",
        phase_observer=observer,
    )
    assert res["success"] is True
    assert res["planner"] == "llm"
    assert (tmp_path / "fallback.txt").read_text(encoding="utf-8") == "from groq"
    assert "done" in phases
