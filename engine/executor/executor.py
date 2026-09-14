"""The local autonomous task executor — plan, execute, validate, remember.

This is THE local executor: it receives an objective, assembles a SHORT plan
(LLM planner with Gemini -> Groq fallback, or the deterministic no-API plan),
executes each step through the scoped tools under the permission gate, retries
each failing step up to ``max_attempts`` times on the SAME cause, validates the
final result, persists everything to project memory, and returns a structured
result.

Flow for ``run(objective)``:
  1. load project context (git, memory, last events) — "continue from here";
  2. pick planner (injected / LLM / deterministic);
  3. plan -> steps + validation;
  4. execute each step (max attempts per step, blocked steps recorded, no retry);
  5. validate the plan;
  6. persist: decisions/tasks/errors/solutions/next_steps/session summary;
  7. return structured result (success, steps, validation, memory, report).
"""
from __future__ import annotations

import logging
import uuid
from engine.executor.diagnostics import ExecutionJournal, redact, failure_reason
from typing import Any, Callable

from engine.executor.context import load_project_context
from engine.executor.memory import ProjectMemory
from engine.executor.permissions import PermissionGate
from engine.executor.planner import make_planner
from engine.executor.reports import build_report
from engine.executor.tools import ScopedTools
from engine.executor.validate import validate_plan, validate_step

logger = logging.getLogger("executor")

DEFAULT_MAX_ATTEMPTS = 3


class TaskExecutor:
    """Run one objective end-to-end inside an authorized workspace."""

    def __init__(
        self,
        workspace: str | None = None,
        *,
        store_root: str | None = None,
        permission_mode: str = "block",
        planner=None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        phase_observer: Callable[[str, dict | None], None] | None = None,
        confirmer: Callable[[str], bool] | None = None,
    ):
        if not workspace:
            from engine import paths as engine_paths

            workspace = str(engine_paths.ROOT)
        self.workspace = str(workspace)
        self.store_root = store_root
        self.gate = PermissionGate(self.workspace, mode=permission_mode, confirmer=confirmer)
        self.tools = ScopedTools(self.workspace, gate=self.gate)
        self.planner = planner
        self.memory = ProjectMemory(self.workspace, store_root=store_root)
        self.journal = ExecutionJournal(self.memory.dir)
        self.session_id = uuid.uuid4().hex
        self.task_id = uuid.uuid4().hex
        self.max_attempts = min(3, max(1, int(max_attempts)))
        self.phase_observer = phase_observer

    # ---------------------------------------------------------------- phases
    def _phase(self, name: str, **payload) -> None:
        """Emit a lifecycle phase to the optional observer (never raises).

        Phases: thinking -> planning -> executing -> validating -> done.
        ``executing`` carries ``step`` (1-based index), ``total`` and
        ``action`` for UI progress. The observer runs on the caller's thread.
        """
        if self.phase_observer is None:
            return
        try:
            self.phase_observer(name, payload or None)
        except Exception:
            pass

    # ------------------------------------------------------------------ main
    def run(self, objective: str | None = None) -> dict:
        self.task_id = uuid.uuid4().hex
        context = load_project_context(self.workspace, store_root=self.store_root)
        resume = context.get("resume", {})
        if not objective:
            objective = resume.get("current_objective") or resume.get("last_objective")
        if not objective:
            objective = "Run a dry scaffold pass over the project and report state."
        objective = str(objective)

        self.memory.set_objective(objective)
        self._phase("thinking")
        planner = make_planner(context, explicit=self.planner)
        self._phase("planning")
        try:
            plan = planner.plan(objective, context)
        except Exception as exc:  # planner must never break the run
            from engine.executor.planner import DeterministicPlanner

            logger.warning("planner raised (%s) — falling back to deterministic", redact(str(exc)))
            plan = DeterministicPlanner().plan(objective, context)

        step_records: list[dict] = []
        steps = plan.get("steps", [])
        total = len(steps)
        for index, step in enumerate(steps, 1):
            self._phase("executing", step=index, total=total, action=step.get("action"))
            step_records.extend(self._execute_step_retry(step))

        self._phase("validating")
        validation = validate_plan(plan.get("validation"), step_records)

        # A step is judged by its FINAL attempt: a transient failure that a later
        # retry recovered must not leave the run marked PARTIAL (STORY: npm test
        # exit 1 on attempt 1, green on attempt 2 — run still reported PARTIAL).
        # Later attempts share step_id and overwrite earlier ones in dict order.
        final_records = {r.get("step_id"): r for r in step_records}
        errors = [
            f"{r.get('step_id')}: {r.get('error') or r.get('reason')}"
            for r in final_records.values()
            if not r.get("ok")
        ]
        for err in errors[:3]:
            self.memory.record_error("run", err, self.max_attempts)

        if validation.get("ok") is False:
            success = False
        else:
            success = not errors

        if errors:
            self.memory.record_decision(
                f"objective '{objective[:80]}' completed with {len(errors)} outstanding error(s)"
            )
            self.memory.set_next_steps(
                [f"resolve: {err}" for err in errors[:5]] + ["re-run mega-brain execute after fixes"]
            )
            next_steps = [f"resolve: {err}" for err in errors[:5]] + [
                "re-run mega-brain execute after fixes"
            ]
        else:
            self.memory.record_task(objective, ok=success)
            self.memory.record_solution("run", "objective completed cleanly")
            next_steps = []

        result: dict[str, Any] = {
            "success": success,
            "objective": objective,
            "planner": plan.get("planner", planner.kind),
            "workspace": context.get("root"),
            "steps": step_records,
            "validation": validation,
            "errors": errors[:10],
            "next_steps": next_steps,
            "permission_mode": self.gate.mode,
            "max_attempts": self.max_attempts,
            "memory_dir": str(self.memory.dir),
            "execution_log": str(self.journal.path),
            "task_id": self.task_id,
            "session_id": self.session_id,
        }

        summary = build_report(result, context)
        result["report_markdown"] = summary

        if success:
            self.memory.end_session(
                f"Objective completed: {objective[:120]} (validation: {validation.get('kind')})"
            )
        # Keep current_objective + next_steps visible when not fully resolved.

        result["memory"] = self.memory.load()
        logger.info("objective done success=%s steps=%d", success, len(step_records))
        self._phase("done", success=bool(success), objective=objective)
        return result

    # ----------------------------------------------------------------- steps
    def _execute_step_retry(self, step: dict) -> list[dict]:
        action = step.get("action")
        params = dict(step.get("params") or {})
        step_id = step.get("id") or action
        records: list[dict] = []

        attempts = 0
        while attempts < self.max_attempts:
            attempts += 1
            try:
                raw = self._run_step(action, params)
            except Exception as exc:
                raw = {"ok": False, "error": str(exc)}
            raw = redact(raw)
            if not raw.get("ok"):
                raw["error"] = failure_reason(raw)
            ok, reason = validate_step(step, raw)
            record = {
                "task_id": self.task_id,
                "session_id": self.session_id,
                "tool": action,
                "command": raw.get("command", params.get("command")),
                "params": redact(params),
                "runner": raw.get("runner"),
                "timeout": raw.get("timeout", False),
                "timeout_seconds": params.get("timeout", 600 if action == "run_tests" else 120) if action in ("run", "run_tests") else None,
                "stdout": raw.get("stdout", ""),
                "stderr": raw.get("stderr", ""),
                "step_id": step_id,
                "action": action,
                "attempt": attempts,
                "ok": ok,
                "blocked": bool(raw.get("blocked")),
                "error": raw.get("error") if not ok else None,
                "reason": reason if not ok else None,
                **{k: raw.get(k) for k in ("path", "exit_code", "count", "summary") if raw.get(k) is not None},
            }
            record = self.journal.append(record)
            if action == "diagnostics":
                record["diagnostics"] = raw.get("records", [])
            records.append(record)
            if ok or raw.get("blocked"):
                break
            if attempts < self.max_attempts:
                logger.warning(
                    "step %s failed on attempt %d/%d (%s) — retrying same cause",
                    step_id,
                    attempts,
                    self.max_attempts,
                    raw.get("error"),
                )
        if not records[-1].get("ok") and not records[-1].get("blocked"):
            self.memory.record_error(step_id, str(records[-1].get("error") or reason), attempts)
        return records

    def _run_step(self, action: str, params: dict) -> dict:
        """Dispatch a single plan step to the scoped tools."""
        if action == "diagnostics":
            return {"ok": True, "path": str(self.journal.path), "records": self.journal.recent()}
        if action == "context":
            return {"ok": True, "info": load_project_context(self.workspace, store_root=self.store_root)}
        if action == "read":
            return self.tools.read(params.get("path", ""))
        if action == "write":
            return self.tools.write(params.get("path", ""), str(params.get("content", "")))
        if action == "edit":
            return self.tools.edit(params.get("path", ""), str(params.get("old", "")), str(params.get("new", "")))
        if action == "search":
            return self.tools.search(params.get("pattern", ""), params.get("where"))
        if action == "glob":
            return self.tools.glob(params.get("pattern", "**/*"))
        if action == "mkdir":
            return self.tools.mkdir(params.get("path", ""))
        if action == "delete":
            return self.tools.delete(params.get("path", ""))
        if action == "run_tests":
            timeout = params.get("timeout") or 600
            return self.tools.run_tests(timeout=int(timeout))
        if action == "git_status":
            return {"ok": True, **self.tools.git_snapshot()}
        if action == "run":
            if not params.get("command"):
                return {"ok": False, "error": "run step requires params.command"}
            return self.tools.run(params["command"], timeout=int(params.get("timeout") or 120))
        return {"ok": False, "error": f"unsupported action: {action}"}


def execute_objective(
    objective: str,
    workspace: str | None = None,
    *,
    store_root: str | None = None,
    permission_mode: str = "block",
    planner=None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    phase_observer: Callable[[str, dict | None], None] | None = None,
    confirmer: Callable[[str], bool] | None = None,
) -> dict:
    """Module-level entry point — one objective, one structured result.

    ``phase_observer`` receives lifecycle phases (``thinking``, ``planning``,
    ``executing``, ``validating``, ``done``) so a GUI can render progress.
    ``confirmer`` (only meaningful with ``permission_mode="ask"``) is asked
    before any gate verdict that needs human confirmation.
    """
    return TaskExecutor(
        workspace,
        store_root=store_root,
        permission_mode=permission_mode,
        planner=planner,
        max_attempts=max_attempts,
        phase_observer=phase_observer,
        confirmer=confirmer,
    ).run(objective)


__all__ = ["TaskExecutor", "execute_objective", "DEFAULT_MAX_ATTEMPTS"]