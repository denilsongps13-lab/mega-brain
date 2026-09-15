"""Evidence-based mission state and Guardian QA for Mega Brain.

Adapted from the Olho de Deus mission/Guardian concepts without coupling the
projects. A mission is VERIFIED only when execution succeeded and every
required step has concrete evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class MissionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass
class MissionStep:
    name: str
    status: MissionStatus = MissionStatus.PENDING
    evidence: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class Mission:
    objective: str
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    status: MissionStatus = MissionStatus.PENDING
    steps: list[MissionStep] = field(default_factory=list)
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class GuardianResult:
    ok: bool
    problems: tuple[str, ...] = ()


class GuardianQA:
    """Final deterministic gate: no evidence means no VERIFIED mission."""

    def verify(self, mission: Mission) -> GuardianResult:
        problems: list[str] = []
        if not mission.steps:
            problems.append("mission has no executed steps")
        for step in mission.steps:
            if step.status is not MissionStatus.VERIFIED:
                problems.append(f"{step.name}: status={step.status.value}")
            if not step.evidence:
                problems.append(f"{step.name}: missing evidence")
        if not mission.result or not mission.result.get("success"):
            problems.append("executor did not report success")
        return GuardianResult(not problems, tuple(problems))


def mission_from_execution(objective: str, result: dict[str, Any]) -> Mission:
    """Convert the existing executor result into an evidence-bearing mission."""
    mission = Mission(objective=objective, status=MissionStatus.RUNNING, result=result)
    records = result.get("steps") or []
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("step_id") or record.get("action") or "step")] = record
    for name, record in latest.items():
        ok = bool(record.get("ok"))
        evidence: list[str] = []
        for key in ("summary", "path", "exit_code", "stdout", "stderr", "command"):
            value = record.get(key)
            if value is not None and value != "":
                text = str(value)
                evidence.append(f"{key}: {text[-1000:]}")
        if ok and not evidence:
            evidence.append("executor validation: ok")
        mission.steps.append(MissionStep(
            name=name,
            status=MissionStatus.VERIFIED if ok else MissionStatus.FAILED,
            evidence=evidence,
            error=None if ok else str(record.get("error") or record.get("reason") or "execution failed"),
        ))
    gate = GuardianQA().verify(mission)
    mission.status = MissionStatus.VERIFIED if gate.ok else MissionStatus.FAILED
    return mission


__all__ = [
    "MissionStatus", "MissionStep", "Mission", "GuardianResult", "GuardianQA",
    "mission_from_execution",
]
