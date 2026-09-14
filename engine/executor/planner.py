"""Task planning for the local runtime — short plan, concrete steps.

Two planners with one contract (:meth:`Planner.plan` returns a dict with
``goal`` / ``steps`` / ``validation``):

  - :class:`DeterministicPlanner` — the no-API-key fallback. Builds a short,
    conservative plan from the project context (run context dive, inspect git,
    run the detected test suite, validate). Never guesses destructive edits.
  - :class:`LLMPlanner` — asks the existing ``llm_router`` (Gemini primary,
    Groq fallback) for a concrete step plan via ``structured_schema``, reusing
    the mission's resilient model routing as-is (no new loop, no cooldown).
    Falls back to the deterministic planner on any router error or malformed
    JSON.

``make_planner`` selects the LLM planner only when a provider is actually
available and the env override ``MEGA_BRAIN_PLANNER`` is not ``deterministic``.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "read", "write", "edit", "search", "glob",
                            "run", "run_tests", "mkdir", "delete", "git_status", "diagnostics",
                        ],
                    },
                    "params": {"type": "object"},
                    "note": {"type": "string"},
                },
                "required": ["action"],
            },
        },
        "validation": {"type": "string", "enum": ["tests", "manual"]},
    },
    "required": ["goal", "steps"],
}

_PLAN_PROMPT = """You are the Mega Brain local task planner. Given a human objective and project context, produce a SHORT, concrete plan of tool steps to run autonomously.

Constraints:
- Keep it to 3-6 steps. No destructive actions.
- Actions available: read, write, edit, search, glob, run, run_tests, mkdir, git_status, diagnostics.
- To diagnose failures use diagnostics (no params). It reads the canonical execution journal. Never guess execution.log.
- params must be simple strings (path, pattern, command, old, new, content).
- If the objective involves fixing tests, ALWAYS include run_tests and use it as validation.
- validation is "tests" when you can verify by running the test suite, else "manual".
- Return ONLY JSON matching the schema, with a "goal" the exact objective and a "steps" array.

Objective: {objective}

Project context:
{context}"""


class Planner:
    kind = "base"

    def plan(self, objective: str, context: dict) -> dict:
        raise NotImplementedError


class DeterministicPlanner(Planner):
    kind = "deterministic"

    def plan(self, objective: str, context: dict) -> dict:
        test_command = context.get("test_command")
        steps: list[dict] = [
            {"id": _sid("s"), "action": "context", "params": {}, "note": "load project context"},
        ]
        if context.get("is_git_repo"):
            steps.append({"id": _sid("s"), "action": "git_status", "params": {}, "note": "inspect git state"})
        triggers = re.split(r"[^\w]+", objective.lower())
        want_search = any(w in triggers for w in ("procure", "procura", "search", "find", "findem", "localizar", "onde"))
        if want_search:
            steps.append(
                {
                    "id": _sid("s"),
                    "action": "search",
                    "params": {"pattern": _infer_search_pattern(objective), "where": None},
                    "note": "locate relevant code",
                }
            )
        if test_command:
            steps.append({"id": _sid("s"), "action": "run_tests", "params": {}, "note": "run detected test suite"})
        else:
            steps.append({"id": _sid("s"), "action": "glob", "params": {"pattern": "**/*.py"}, "note": "inventory source files"})
        return {
            "goal": objective,
            "steps": steps,
            "validation": "tests" if test_command else "manual",
            "planner": "deterministic",
        }


class LLMPlanner(Planner):
    kind = "llm"

    def plan(self, objective: str, context: dict) -> dict:
        summary = "\n".join(
            f"- {k}: {v}"
            for k, v in (
                ("project", context.get("project")),
                ("branch", context.get("branch")),
                ("last_commit", context.get("last_commit")),
                ("dirty_files", context.get("dirty_files")),
                ("test_command", context.get("test_command")),
                ("llm_gemini", context.get("llm_gemini")),
                ("llm_groq", context.get("llm_groq")),
                ("next_steps", context.get("resume", {}).get("next_steps")),
            )
            if v is not None
        )
        prompt = _PLAN_PROMPT.format(objective=objective, context=summary)
        try:
            from engine.intelligence.pipeline.mce import llm_router

            raw = llm_router.run_prompt(
                prompt,
                structured_schema=PLAN_SCHEMA,
                max_output_tokens=2048,
            )
            plan = _parse_plan(raw, objective)
            plan.setdefault("planner", "llm")
            return plan
        except Exception as exc:  # any router failure (incl. fallback) -> deterministic
            import logging

            logging.getLogger("executor.planner").warning(
                "LLM planner failed (%s) — using deterministic plan", exc
            )
            return self._fallback(objective, context)

    def _fallback(self, objective, context):
        return DeterministicPlanner().plan(objective, context)


def _parse_plan(raw: str, objective: str) -> dict:
    if isinstance(raw, dict):
        plan = raw
    else:
        text = str(raw or "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end < start:
            raise ValueError("no JSON envelope in LLM plan response")
        plan = json.loads(text[start : end + 1])
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("malformed plan: steps missing")
    for step in steps:
        if not isinstance(step, dict) or "action" not in step:
            raise ValueError("malformed plan step")
        step.setdefault("id", _sid("s"))
        step.setdefault("params", {})
    plan["goal"] = objective
    plan.setdefault("validation", "manual")
    return plan


def _infer_search_pattern(objective: str) -> str:
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", objective):
        if token.lower() not in {
            "projeto", "project", "procurar", "procure", "search", "find",
            "localizar", "arquivo", "file", "code", "codigo", "onde", "qual",
            "testes", "tests", "corrija", "corrigir", "fix", "analise",
            "analisar", "abrir", "este", "deste", "encapsular", "sobre", "para",
        }:
            return token
    return r"\b(fix|todo|TODO|FIXME)\b"


def _sid(prefix: str) -> str:
    return f"{prefix}{str(uuid.uuid4())[:8]}"


def make_planner(
    context: dict | None = None,
    *,
    force: str | None = None,
    explicit: Planner | None = None,
) -> Planner:
    """Pick a planner. LLM when a provider is available and env allows it."""
    if explicit is not None:
        return explicit
    choice = force or os.environ.get("MEGA_BRAIN_PLANNER", "").strip().lower()
    if choice == "deterministic":
        return DeterministicPlanner()
    llm_ok = context and context.get("llm_available")
    if llm_ok:
        return LLMPlanner()
    return DeterministicPlanner()


__all__ = ["Planner", "DeterministicPlanner", "LLMPlanner", "make_planner", "PLAN_SCHEMA"]