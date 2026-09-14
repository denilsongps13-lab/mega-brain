"""Persistent project memory for the local runtime — data-layer only.

Why this exists
---------------
The executor must remember, between runs, what it was doing: the current
objective, decisions taken, completed tasks, errors hit, solutions applied,
next steps and a session summary. This module is the single store for that
"runtime memory". It deliberately REUSES the repo's data-layer conventions:

  - storage lives under ``engine.paths.DATA`` (``.data/``, gitignored) — the
    same root used by RAG indexes, mce caches and watcher state;
  - session events are appended to a JSONL log (``logs/megabrain-sessions.jsonl``
    style), matching the ``*.jsonl`` log convention used across the engine.

Two files per project root:
  - ``.data/megabrain/projects/<slug>/memory.json`` — the durable state;
  - ``.data/megabrain/projects/<slug>/events.jsonl``     — append-only timeline.

A global pointer (``.data/megabrain/projects/<slug>``) makes "carregar estado
anterior e continuar de onde parou" trivial: just load memory.json on open.

State fields (all JSON-serializable):
  ``current_objective, last_objective, updated_at, decisions[], completed[],
  errors[], solutions[], next_steps[], session_summary``.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from engine import paths as engine_paths

_KEYS = (
    "current_objective",
    "last_objective",
    "updated_at",
    "decisions",
    "completed",
    "errors",
    "solutions",
    "next_steps",
    "session_summary",
)

_EMPTY_STATE: dict = {
    "current_objective": None,
    "last_objective": None,
    "updated_at": None,
    "decisions": [],
    "completed": [],
    "errors": [],
    "solutions": [],
    "next_steps": [],
    "session_summary": None,
}


def _slugify(path: str) -> str:
    name = Path(path).resolve().name or "workspace"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower()
    key = slug[:48] or "workspace"
    digest = hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:6]
    return f"{key}-{digest}"


class ProjectMemory:
    """Persistent per-project memory store (default root: engine.paths.DATA)."""

    def __init__(self, project_root: str | Path | None = None, store_root: str | Path | None = None):
        self.project_root = str(project_root or engine_paths.ROOT)
        base = Path(store_root or engine_paths.MEGA_BRAIN_PROJECTS).resolve()
        self.dir = (base / _slugify(self.project_root)).resolve()
        self.state_file = self.dir / "memory.json"
        self.events_file = self.dir / "events.jsonl"
        self._ensure()

    # ------------------------------------------------------------ lifecycle
    def _ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._write_state(dict(_EMPTY_STATE))

    def _write_state(self, state: dict) -> None:
        self.state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load(self) -> dict:
        self._ensure()
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        merged = dict(_EMPTY_STATE)
        merged.update({k: state.get(k, _EMPTY_STATE[k]) for k in _KEYS})
        return merged

    def _save(self, state: dict) -> dict:
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self._write_state(state)
        return state

    def _event(self, kind: str, payload: dict) -> None:
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "kind": kind,
            "project": Path(self.project_root).resolve().name,
            **payload,
        }
        try:
            with open(self.events_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------- mutations
    def set_objective(self, objective: str) -> dict:
        state = self.load()
        state["last_objective"] = state["current_objective"]
        state["current_objective"] = objective
        state["next_steps"] = []
        self._event("objective", {"objective": objective})
        return self._save(state)

    def record_decision(self, text: str) -> dict:
        state = self.load()
        state["decisions"].append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text})
        self._event("decision", {"text": text})
        return self._save(state)

    def record_task(self, task: str, **meta) -> dict:
        state = self.load()
        state["completed"].append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": task, **meta})
        self._event("task", {"task": task, **meta})
        return self._save(state)

    def record_error(self, step: str, error: str, attempts: int) -> dict:
        state = self.load()
        state["errors"].append(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "step": step,
                "error": str(error)[:500],
                "attempts": attempts,
            }
        )
        self._event("error", {"step": step, "error": str(error)[:500], "attempts": attempts})
        return self._save(state)

    def record_solution(self, step: str, note: str) -> dict:
        state = self.load()
        state["solutions"].append(
            {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": step, "note": str(note)[:500]}
        )
        self._event("solution", {"step": step, "note": str(note)[:500]})
        return self._save(state)

    def set_next_steps(self, steps: list[str]) -> dict:
        state = self.load()
        state["next_steps"] = [str(s)[:300] for s in steps]
        return self._save(state)

    def end_session(self, summary: str) -> dict:
        state = self.load()
        state["session_summary"] = str(summary)[:3000]
        state["last_objective"] = state["current_objective"]
        state["current_objective"] = None
        self._event("session_end", {"summary": str(summary)[:300]})
        return self._save(state)

    # ------------------------------------------------------------- readers
    def recent_events(self, limit: int = 20) -> list[dict]:
        if not self.events_file.exists():
            return []
        try:
            lines = self.events_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events: list[dict] = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def summary_markdown(self) -> str:
        state = self.load()
        lines = ["# Mega Brain — Project Memory"]
        lines.append(f"- **Project:** {Path(self.project_root).resolve()}")
        lines.append(f"- **Updated:** {state.get('updated_at')}")
        lines.append(f"- **Current objective:** {state.get('current_objective')}")
        lines.append(f"- **Last objective:** {state.get('last_objective')}")
        if state.get("next_steps"):
            lines.append("\n## Next steps")
            lines += [f"- {s}" for s in state["next_steps"]]
        if state.get("decisions"):
            lines.append("\n## Decisions")
            lines += [f"- {d.get('text')}" for d in state["decisions"][-10:]]
        if state.get("completed"):
            lines.append("\n## Completed")
            lines += [f"- {t.get('task')}" for t in state["completed"][-10:]]
        if state.get("errors"):
            lines.append("\n## Last errors")
            lines += [f"- {e.get('step')}: {e.get('error')}" for e in state["errors"][-5:]]
        if state.get("session_summary"):
            lines.append(f"\n## Session summary\n{state['session_summary']}")
        return "\n".join(lines)


def load_memory(project_root: str | Path | None = None) -> dict:
    return ProjectMemory(project_root).load()


__all__ = ["ProjectMemory", "load_memory", "_slugify"]