"""Result validation helpers for the local executor.

A step result is valid when the tool reported ``ok`` and it was not blocked
by the permission gate. A plan's final validation is either ``tests`` (last
run_tests exit code 0) or ``manual`` (marker for human review, never blocks).
"""
from __future__ import annotations

import re
from typing import Any
from engine.executor.diagnostics import failure_reason


def validate_step(step: dict, result: dict) -> tuple[bool, str | None]:
    """Return ``(ok, reason)`` for a single executed step."""
    if result.get("blocked"):
        return (False, f"blocked: {result.get('reason')}")
    if not result.get("ok"):
        return (False, failure_reason(result))
    if step.get("action") == "run_tests":
        if result.get("exit_code") not in (0, None):
            return (False, "test suite returned non-zero exit code")
        summary = result.get("summary")
        if summary is not None:
            tail = result.get("stdout", "") + result.get("stderr", "")
            if re.search(r"\b(\d+) failed\b", tail):
                return (False, "test suite reports failures")
    return (True, None)


def validate_plan(validation: str | None, results: list[dict]) -> dict:
    """Final whole-plan validation."""
    kind = (validation or "manual").strip().lower()
    if kind == "tests":
        test_runs = [r for r in results if r.get("action") == "run_tests" and r.get("step_id")]
        last = test_runs[-1] if test_runs else None
        if last is None:
            return {"kind": "tests", "ok": False, "detail": "no test run executed"}
        ok = bool(last.get("ok")) and last.get("exit_code") == 0
        tail = last.get("stdout", "") + last.get("stderr", "")
        failed = re.search(r"(\d+) failed", tail)
        detail = {
            "exit_code": last.get("exit_code"),
            "failed": int(failed.group(1)) if failed else 0,
            "attempts": last.get("attempts", 1),
        }
        return {"kind": "tests", "ok": bool(ok) and detail["failed"] == 0, "detail": detail}
    return {"kind": "manual", "ok": None, "detail": "manual validation required"}


def step_failed(step_id: str, results: list[dict]) -> bool:
    """True when any recorded attempt of ``step_id`` failed."""
    return any(r.get("step_id") == step_id and not r.get("ok") for r in results)


__all__ = ["validate_step", "validate_plan", "step_failed"]