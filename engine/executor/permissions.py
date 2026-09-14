"""Permission gate for the local task executor — safe/protected/destructive.

Why this exists
---------------
The executor gets a human-style objective ("analise este projeto e corrija os
testes") and turns it into local tool calls. Those calls MUST stay inside an
authorized workspace and MUST NOT be able to damage the machine or the repo.
This module is the single decision point: every tool/command the executor
plans to run is classified here BEFORE it executes.

Verdicts
--------
Returned by every ``check_*`` method as a ``(decision, reason)`` tuple:

  - ``("allow", None)``       -> safe, run it.
  - ``("block", reason)``     -> unprotected/destructive, never run. The
    executor records the denial in project memory and moves on.
  - ``("ask", reason)``       -> possibly destructive; requires explicit human
    confirmation. In ``block`` mode (default) these are treated as blocked.

Modes (``MEGA_BRAIN_PERMISSION_MODE`` env or explicit constructor arg)
----------------------------------------------------------------------
  - ``block`` (default, non-interactive safe) — dangerous actions are denied.
  - ``ask``   — dangerous actions ask for ``y/N`` on stdin when a TTY is
    attached; otherwise denied.
  - ``allow`` — only for tests/trusted runs: logs the denial-free decision but
    still never bypasses the ALWAYS-silent .env/secret protections.

Always blocked (no mode bypasses these): touching any ``.env`` (read/write),
``git reset --hard``, force push, recursive directory deletion
(``rm -rf`` / ``Remove-Item -Recurse`` / ``shutil.rmtree``), deleting top-level
directories inside the workspace, external publish/deploy, credential changes,
reading/revealing API keys, and any file operation that resolves outside the
authorized workspace.

The allowlist of executable names is the definition of "comandos permitidos":
``py/python/pytest/npm/node/git`` — anything else is blocked by default.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

# Executables the executor may launch (base-name match, PATHEXT aware).
ALLOWED_EXECUTABLES = frozenset({"py", "python", "python3", "pytest", "npm", "node", "git"})

# Subcommands that are read-only/analysis and always allowed for git.
ALLOWED_GIT_SUBCOMMANDS = frozenset(
    {"status", "diff", "log", "show", "branch", "remote", "rev-parse", "check-ignore"}
)

# Substrings that mark a destructive/unsafe git operation, regardless of form.
_BLOCKED_GIT_MARKERS = (
    "reset --hard",
    "reset -hard",
    "push -f",
    "push --force",
    "--force-with-lease",
    "clean -fd",
    "rebase --root",
    "filter-branch",
)

# Command-line fragments that are NEVER allowed.
_BLOCKED_CMD_FRAGMENTS = (
    "rm -rf",
    "rm -fr",
    "rm -r",
    "rmdir /s",
    "rd /s",
    "Remove-Item",
    "-Recurse",
    "rmtree",
    "del /s",
    "del -r",
    "rd -r",
    "> .env",
    ">> .env",
    "Set-Content .env",
    "Out-File .env",
    "git reset --hard",
    "git clean -fd",
    "force-with-lease",
    "npm publish",
    "chmod",
    "chown",
    "sudo",
    "net user",
    "net localgroup",
    "reg add",
    "Start-Process",
    "Set-ExecutionPolicy",
    "ren .env",
    "move .env",
    "copy .env",
)

_SECRET_KEEPERS = (".env",)

_MODE_DEFAULT = "block"
_VALID_MODES = ("block", "ask", "allow")


def _mode_from_env() -> str:
    raw = os.environ.get("MEGA_BRAIN_PERMISSION_MODE", _MODE_DEFAULT).strip().lower()
    return raw if raw in _VALID_MODES else _MODE_DEFAULT


def _is_secret_file(path: Path) -> bool:
    """True when the file is a secretion store somewhere along its name."""
    return any(part.strip() == p for part in path.parts for p in _SECRET_KEEPERS) or (
        path.name == ".env"
    )


_VERDICT_KEYS = {"allow", "block", "ask"}


class PermissionGate:
    """Single decision point for every executor action on a workspace."""

    def __init__(
        self,
        workspace: str | Path,
        mode: str | None = None,
        confirmer: Callable[[str], bool] | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.mode = (mode or _mode_from_env()).strip().lower()
        if self.mode not in _VALID_MODES:
            self.mode = _MODE_DEFAULT
        # ``confirmer(reason) -> bool`` replaces the console y/N prompt for
        # ``ask`` verdicts (GUI dialogs). Never overrides ``block``.
        self._confirmer = confirmer

    # ------------------------------------------------------------------ paths
    def resolve(self, path: str | Path) -> Path | None:
        """Absolute path for a relative path; strictly inside workspace."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        candidate = candidate.resolve()
        if not self._within(candidate):
            return None
        return candidate

    def _within(self, candidate: Path) -> bool:
        try:
            candidate.relative_to(self.workspace)
        except ValueError:
            return False
        return True

    def check_path(self, action: str, path: str | Path) -> tuple[str, str | None]:
        path_obj = Path(path)
        if _is_secret_file(path_obj) or _is_secret_file(
            Path(path_obj.name)
        ):
            return ("block", f"secret file access denied: {path_obj.name}")
        resolved = self.resolve(str(path_obj))
        if resolved is None:
            return ("block", f"path escapes workspace: {path_obj}")
        if action in ("delete", "remove"):
            if resolved.resolve() == self.workspace.resolve() or resolved.parent == self.workspace:
                return ("block", "refusing to delete a top-level item")
            return ("ask", f"deleting {resolved.relative_to(self.workspace)}")
        return ("allow", None)

    # -------------------------------------------------------------- commands
    def check_command(self, command: str) -> tuple[str, str | None]:
        lowered = command.lower()
        for fragment in _BLOCKED_CMD_FRAGMENTS:
            if fragment.lower() in lowered:
                return ("block", f"destructive/unsafe pattern: {fragment.strip()}")
        tokens = _split_command(command)
        if not tokens:
            return ("block", "empty command")
        base = _exe_base(tokens[0])
        allowed = any(base == a or base.lower() == a.lower() for a in ALLOWED_EXECUTABLES)
        if base.lower() == "git":
            if tokens[1] not in ALLOWED_GIT_SUBCOMMANDS:
                return ("block", f"git subcommand not allowed: {tokens[1]}")
            for marker in _BLOCKED_GIT_MARKERS:
                if marker in lowered:
                    return ("block", f"destructive git flagged: {marker}")
            return ("allow", None)
        if not allowed:
            return ("block", f"executable not in allowlist: {tokens[0]}")
        return ("allow", None)

    def check_run(self, command: str) -> tuple[str, str | None]:
        return self.check_command(command)

    def check_step(self, action: str, params: dict) -> tuple[str, str | None]:
        """Highest-level check for a plan step before execution."""
        if action in ("read", "search", "glob", "git_status", "context"):
            return ("allow", None)
        if action in ("write", "edit"):
            path = params.get("path")
            if not path:
                return ("block", "write/edit requires a path")
            res = self.resolve(str(path))
            if res is None:
                return ("block", f"path escapes workspace: {path}")
            if _is_secret_file(Path(path)):
                return ("block", "refusing to write/edit a secret file")
            return ("allow", None)
        if action in ("run_tests", "run"):
            command = params.get("command") or params.get("cmd")
            if not command:
                return ("block", "run requires a command")
            return self.check_command(str(command))
        if action in ("delete", "remove"):
            path = params.get("path")
            if not path:
                return ("block", "delete requires a path")
            return self.check_path("delete", str(path))
        return ("block", f"unknown action: {action}")

    def decide(self, verdict: tuple[str, str | None]) -> tuple[bool, bool, str | None]:
        """Map verdict+mode to (allowed, needs_confirm, reason)."""
        decision, reason = verdict
        if decision == "allow":
            return (True, False, None)
        if decision == "ask":
            if self.mode == "allow":
                return (True, False, reason)
            if self.mode == "ask":
                if self._confirmer is not None:
                    try:
                        confirmed = bool(self._confirmer(reason))
                    except Exception:
                        confirmed = False
                else:
                    confirmed = _prompt_confirm(reason)
                if confirmed:
                    return (True, False, reason)
            return (False, self.mode == "ask", reason)
        # block
        return (False, False, reason)


def _split_command(command: str) -> list[str]:
    """Tokenize a command like a POSIX shell would, Windows-aware for quotes.

    Only handles spaces + double quotes (the executor's plan language never
    needs pipes/redirects — those are blocked by the fragment check anyway).
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in command:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch.isspace() and not in_quote:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _exe_base(token: str) -> str:
    base = token.replace("\\", "/").rsplit("/", 1)[-1]
    low = base.lower()
    for suffix in (".cmd", ".exe", ".bat", ".ps1"):
        if low.endswith(suffix):
            return low[: -len(suffix)]
    return base


def _prompt_confirm(reason: str | None) -> bool:
    """Interactive y/N confirmation for ``ask`` mode (returns False otherwise)."""
    try:
        import sys

        if not sys.stdin.isatty():
            return False
        print(f"[permission] {reason or 'dangerous action'} — confirm? [y/N] ", end="", flush=True)
        answer = sys.stdin.readline().strip().lower()
        return answer in ("y", "yes")
    except Exception:
        return False


__all__ = [
    "ALLOWED_EXECUTABLES",
    "PermissionGate",
    "_VALID_MODES",
]