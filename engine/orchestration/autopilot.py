"""Small, dependency-free swarm/autopilot layer for Mega Brain.

Adapts the useful ideas (specialized roles, autonomous bounded loops and quality
gates) without installing Ruflo or replacing Mega Brain's executor/memory/gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any


class SwarmRole(str, Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    TESTER = "tester"
    REVIEWER = "reviewer"
    SECURITY = "security"


@dataclass(frozen=True)
class GateResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class QualityGate:
    checks: list[tuple[str, Callable[[], Any]]] = field(default_factory=list)

    def add(self, name: str, check: Callable[[], Any]) -> "QualityGate":
        self.checks.append((name, check))
        return self

    def run(self) -> list[GateResult]:
        results: list[GateResult] = []
        for name, check in self.checks:
            try:
                value = check()
                if isinstance(value, dict):
                    ok = bool(value.get("ok", value.get("success", False)))
                    detail = str(value.get("error") or value.get("summary") or "")
                else:
                    ok = bool(value)
                    detail = ""
            except Exception as exc:
                ok, detail = False, str(exc)
            results.append(GateResult(name, ok, detail))
        return results


class Autopilot:
    """Bounded diagnose/fix/validate loop. Never bypasses PermissionGate."""

    def __init__(self, execute: Callable[[str], dict], *, max_cycles: int = 3):
        self.execute = execute
        self.max_cycles = max(1, min(int(max_cycles), 3))

    def run(self, objective: str) -> dict:
        history: list[dict] = []
        current = objective
        for cycle in range(1, self.max_cycles + 1):
            result = self.execute(current)
            history.append({"cycle": cycle, "result": result})
            if result.get("success"):
                return {"success": True, "cycles": cycle, "history": history, "result": result}
            errors = result.get("errors") or []
            diagnostics = "; ".join(map(str, errors[:5])) or "unknown execution failure"
            current = (
                f"Repair the failed objective safely, then rerun all relevant validation. "
                f"Original objective: {objective}. Diagnostics: {diagnostics}. "
                "Preserve existing work, secrets, memory and PermissionGate."
            )
        return {"success": False, "cycles": self.max_cycles, "history": history, "result": history[-1]["result"]}
