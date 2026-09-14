"""The local autonomous task executor — plan, execute, validate, remember.

This executor plans, runs, validates and persists task state. Each tool attempt
is also written to a canonical per-project execution log so failures keep the
actual command, exit code, stdout and stderr instead of degrading to a generic
"tool reported failure" message.
"""
from __future__ import annotations

import json
import logging
import re
import time
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
_SENSITIVE_KEY = re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.I)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(GEMINI_API_KEY|GROQ_API_KEY|GOOGLE_API_KEY|[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD))\s*=\s*([^\s]+)"
)


def _redact_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = _SENSITIVE_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=<redacted>", value)
    return text.replace(".env", "<env-file>") if "=" in text else text


def _safe(value: Any) -> Any:
    """Return a JSON-serializable, secret-redacted representation."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                out[str(key)] = "<redacted>"
            else:
                out[str(key)] = _safe(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _best_error(raw: dict, reason: str | None = None) -> str:
    """Prefer concrete tool diagnostics over generic validation text."""
    explicit = raw.get("error") or raw.get("reason")
    if explicit:
        return str(explicit)
    stderr = str(raw.get("stderr") or "").strip()
    if stderr:
        return stderr[-2000:]
    stdout = str(raw.get("stdout") or "").strip()
    if stdout:
        return stdout[-2000:]
    if raw.get("exit_code") is not None:
        return f"command exited with code {raw.get('exit_code')}"
    return str(reason or "tool reported failure")


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
        self.execution_log = self.memory.dir / "execution.jsonl"
        self.max_attempts = max(1, int(max_attempts))
        self.phase_observer = phase_observer

    def _phase(self, name: str, **payload) -> None:
        if self.phase_observer is None:
            return
        try:
            self.phase_observer(name, payload or None)
        except Exception:
            pass

    def _log_attempt(self, record: dict, raw: dict, params: dict) -> None:
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "step_id": record.get("step_id"),
            "action": record.get("action"),
            "attempt": record.get("attempt"),
            "ok": record.get("ok"),
            "blocked": record.get("blocked"),
            "params": _safe(params),
            "command": _safe(raw.get("command")),
            "exit_code": raw.get("exit_code"),
            "stdout": _safe(raw.get("stdout")),
            "stderr": _safe(raw.get("stderr")),
            "error": _safe(record.get("error")),
            "reason": _safe(record.get("reason")),
            "runner": raw.get("runner"),
            "summary": raw.get("summary"),
            "timeout": bool(raw.get("timeout")),
        }
        try:
            self.execution_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.execution_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("could not persist execution diagnostics: %s", exc)

    def run(self, objective: str | None = None) -> dict:
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
        except Exception as exc:
            from engine.executor.planner import DeterministicPlanner
            logger.warning("planner raised (%s) — falling back to deterministic", exc)
            plan = DeterministicPlanner().plan(objective, context)

        step_records: list[dict] = []
        steps = plan.get("steps", [])
        total = len(steps)
        for index, step in enumerate(steps, 1):
            self._phase("executing", step=index, total=total, action=step.get("action"))
            step_records.extend(self._execute_step_retry(step))

        self._phase("validating")
        validation = validate_plan(plan.get("validation"), step_records)
        final_records = {r.get("step_id"): r for r in step_records}
        errors = [
            f"{r.get('step_id')}: {r.get('error') or r.get('reason')}"
            for r in final_records.values()
            if not r.get("ok")
        ]
        for err in errors[:3]:
            self.memory.record_error("run", err, self.max_attempts)

        success = bool(validation.get("ok") is not False and not errors)
        if errors:
            self.memory.record_decision(
                f"objective '{objective[:80]}' completed with {len(errors)} outstanding error(s)"
            )
            next_steps = [f"resolve: {err}" for err in errors[:5]] + [
                "re-run mega-brain execute after fixes"
            ]
            self.memory.set_next_steps(next_steps)
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
            "execution_log": str(self.execution_log),
        }

        summary = build_report(result, context)
        result["report_markdown"] = summary
        if success:
            self.memory.end_session(
                f"Objective completed: {objective[:120]} (validation: {validation.get('kind')})"
            )
        result["memory"] = self.memory.load()
        logger.info("objective done success=%s steps=%d", success, len(step_records))
        self._phase("done", success=bool(success), objective=objective)
        return result

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
            ok, reason = validate_step(step, raw)
            error = None if ok else _best_error(raw, reason)
            record = {
                "step_id": step_id,
                "action": action,
                "attempt": attempts,
                "ok": ok,
                "blocked": bool(raw.get("blocked")),
                "error": error,
                "reason": reason if not ok else None,
            }
            for key in (
                "path", "exit_code", "count", "summary", "command", "stdout",
                "stderr", "runner", "timeout"
            ):
                if raw.get(key) is not None:
                    record[key] = _safe(raw.get(key))
            records.append(record)
            self._log_attempt(record, raw, params)

            if ok or raw.get("blocked"):
                break
            if attempts < self.max_attempts:
                logger.warning(
                    "step %s failed on attempt %d/%d (%s) — retrying same cause",
                    step_id, attempts, self.max_attempts, error,
                )

        if not records[-1].get("ok") and not records[-1].get("blocked"):
            self.memory.record_error(step_id, str(records[-1].get("error") or reason), attempts)
        return records

    def _run_step(self, action: str, params: dict) -> dict:
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
            return self.tools.run_tests(timeout=int(params.get("timeout") or 600))
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
