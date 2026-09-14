"""Project context — load where you are, what happened, and where to resume.

When the runtime opens a project it assembles a context dict that answers:
  - which repo/workspace is active (root, git remote, branch, last commit,
    dirty state);
  - what memory exists for this project (previous objective, decisions,
    completed tasks, errors, next steps, session summary);
  - the last events/tasks on record;
  - what the machine can actually do (python, node, test command, provider
    availability for Gemini / Groq fallback).

This is the "continuar de onde parou" contract: ``next_steps`` + last objective
are surfaced so the executor can pick up a previous run.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from engine import paths as engine_paths
from engine.executor.memory import ProjectMemory


def _git(cwd: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30
        )
        return (proc.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_test_command(workspace: Path) -> str | None:
    from engine.executor.test_runner import detect_test_command as _detect

    return _detect(workspace)


def load_project_context(
    workspace: str | Path | None = None,
    store_root: str | Path | None = None,
) -> dict:
    root = Path(workspace or engine_paths.ROOT).resolve()
    if not root.is_dir():
        root = engine_paths.ROOT

    git_repo = (root / ".git").exists()
    branch = _git(root, "branch", "--show-current") if git_repo else ""
    last_commit = _git(root, "log", "-1", "--oneline") if git_repo else ""
    dirty = _git(root, "status", "--porcelain") if git_repo else ""
    remotes = _git(root, "remote", "-v") if git_repo else ""

    memory = ProjectMemory(root, store_root=store_root)
    state = memory.load()
    events = memory.recent_events(limit=12)

    llm_gemini = llm_groq = False
    try:
        from engine.intelligence.pipeline.mce.llm_router import is_provider_available

        llm_gemini = is_provider_available("gemini")
        llm_groq = is_provider_available("groq")
    except Exception:
        pass

    python_version = ""
    try:
        python_version = subprocess.run(
            [sys.executable, "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip() or "unknown"
    except Exception:
        python_version = "unknown"

    return {
        "ok": True,
        "root": str(root),
        "project": root.name,
        "is_git_repo": git_repo,
        "branch": branch or None,
        "last_commit": last_commit or None,
        "dirty_files": len([l for l in dirty.splitlines() if l.strip()]),
        "dirty": dirty or "",
        "remotes": remotes or "",
        "platform": platform.platform(),
        "python": python_version,
        "test_command": detect_test_command(root),
        "llm_available": llm_gemini or llm_groq,
        "llm_gemini": llm_gemini,
        "llm_groq": llm_groq,
        "workspace": str(root),
        "store_dir": str(memory.dir),
        "memory": state,
        "last_events": events,
        "resume": {
            "current_objective": state.get("current_objective"),
            "last_objective": state.get("last_objective"),
            "next_steps": state.get("next_steps") or [],
        },
    }


def project_slug(workspace: str | Path | None = None) -> str:
    from engine.executor.memory import ProjectMemory

    return ProjectMemory(workspace or engine_paths.ROOT).dir.name


__all__ = ["load_project_context", "detect_test_command", "project_slug"]