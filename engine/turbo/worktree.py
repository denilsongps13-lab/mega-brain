"""Isolated parallel task runner using git worktrees.

Disabled by default.  It never invokes a shell and keeps all temporary
worktrees inside the repository-scoped ``.megabrain/worktrees`` directory.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .context import redact_secrets

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,255}$")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _trim(text: str, limit: int = 16000) -> str:
    text = redact_secrets(text or "")
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


@dataclass(frozen=True)
class WorktreeTask:
    name: str
    argv: Sequence[str]
    ref: str = "HEAD"
    timeout_s: float = 300.0


@dataclass(frozen=True)
class WorktreeResult:
    name: str
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    success: bool
    error: str | None = None


class ParallelWorktreeRunner:
    def __init__(
        self,
        repo_root: str | Path,
        *,
        max_workers: int = 2,
        enabled: bool | None = None,
        permission_check: Callable[[Sequence[str]], bool] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.max_workers = max(1, min(int(max_workers), 4))
        self.enabled = _truthy(os.environ.get("MEGA_BRAIN_WORKTREE_PARALLEL")) if enabled is None else bool(enabled)
        self.permission_check = permission_check
        self.workspace = (self.repo_root / ".megabrain" / "worktrees").resolve()
        if self.repo_root not in self.workspace.parents:
            raise ValueError("worktree workspace escaped repository root")

    @staticmethod
    def _validate_task(task: WorktreeTask) -> None:
        if not _SAFE_NAME.fullmatch(task.name) or ".." in task.name:
            raise ValueError("unsafe worktree task name")
        if not isinstance(task.argv, (list, tuple)) or not task.argv or not all(isinstance(x, str) and x for x in task.argv):
            raise ValueError("argv must be a non-empty sequence of strings")
        if not _SAFE_REF.fullmatch(task.ref) or task.ref.startswith("-") or ".." in task.ref:
            raise ValueError("unsafe git ref")
        if task.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

    def run(self, tasks: Iterable[WorktreeTask]) -> list[WorktreeResult]:
        items = list(tasks)
        if not self.enabled:
            raise PermissionError("parallel worktree execution is disabled")
        for task in items:
            self._validate_task(task)
        self.workspace.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(items)))) as pool:
            return list(pool.map(self._run_one, items))

    def _run_one(self, task: WorktreeTask) -> WorktreeResult:
        if self.permission_check is not None and not self.permission_check(task.argv):
            return WorktreeResult(task.name, 126, "", "", 0.0, False, "permission denied")
        path = (self.workspace / task.name).resolve()
        if self.workspace not in path.parents:
            return WorktreeResult(task.name, 126, "", "", 0.0, False, "unsafe worktree path")
        started = time.monotonic()
        added = False
        try:
            add = subprocess.run(
                ["git", "worktree", "add", "--detach", str(path), task.ref],
                cwd=self.repo_root, capture_output=True, text=True, timeout=60, shell=False,
            )
            if add.returncode != 0:
                return WorktreeResult(task.name, add.returncode, _trim(add.stdout), _trim(add.stderr), time.monotonic()-started, False, "git worktree add failed")
            added = True
            proc = subprocess.run(
                list(task.argv), cwd=path, capture_output=True, text=True,
                timeout=float(task.timeout_s), shell=False,
            )
            return WorktreeResult(task.name, proc.returncode, _trim(proc.stdout), _trim(proc.stderr), time.monotonic()-started, proc.returncode == 0, None if proc.returncode == 0 else "task failed")
        except subprocess.TimeoutExpired as exc:
            return WorktreeResult(task.name, 124, _trim(str(exc.stdout or "")), _trim(str(exc.stderr or "")), time.monotonic()-started, False, "timeout")
        except Exception as exc:
            return WorktreeResult(task.name, 1, "", "", time.monotonic()-started, False, _trim(f"{type(exc).__name__}: {exc}"))
        finally:
            if added:
                subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=self.repo_root, capture_output=True, text=True, shell=False)
            subprocess.run(["git", "worktree", "prune"], cwd=self.repo_root, capture_output=True, text=True, shell=False)


__all__ = ["ParallelWorktreeRunner", "WorktreeResult", "WorktreeTask"]
