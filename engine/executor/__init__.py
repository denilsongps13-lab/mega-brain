"""Local autonomous runtime — plan, execute, validate, remember, safely.

The Mega Brain local runtime turns a free-form objective ("analise este
projeto e corrija os testes") into a short plan, executes it with scoped
local tools behind a permission gate, validates the result, persists it into
per-project memory and returns a structured result. It reuses the existing
LLM router (Gemini primary, Groq fallback, streaming/tools preserved) when
model providers are available and degrades to a conservative deterministic
planner when they are not.

Public entry points
-------------------
  - :func:`execute_objective` — run one objective end-to-end.
  - :func:`engine.executor.context.load_project_context` — state on open.
  - :func:`engine.executor.memory.load_memory` — persisted memory state.
"""
from __future__ import annotations

from engine.executor.context import load_project_context, project_slug
from engine.executor.executor import TaskExecutor, execute_objective
from engine.executor.memory import ProjectMemory, load_memory
from engine.executor.permissions import PermissionGate
from engine.executor.planner import DeterministicPlanner, LLMPlanner, make_planner
from engine.executor.reports import build_report
from engine.executor.tools import ScopedTools

__all__ = [
    "TaskExecutor",
    "execute_objective",
    "load_project_context",
    "project_slug",
    "ProjectMemory",
    "load_memory",
    "PermissionGate",
    "ScopedTools",
    "DeterministicPlanner",
    "LLMPlanner",
    "make_planner",
    "build_report",
]