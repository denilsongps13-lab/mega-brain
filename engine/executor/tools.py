"""Scoped local tools for the task executor — everything stays in-workspace.

Every tool is a method on :class:`ScopedTools`, which wraps a
:class:`~.permissions.PermissionGate`. All file operations resolve strictly
under the authorized workspace, all command execution goes through the
executable allowlist + blocked-fragment scan, and results are plain dicts
(JSON-serializable) so the executor can log them into project memory.

Tools
-----
  - ``read``   — read a text file (with line count + preview)
  - ``write``  — create/overwrite a text file (never ``.env``)
  - ``edit``   — replace the first occurrence of ``old`` with ``new``
  - ``search`` — regex search (ripgrep when present, pure-python fallback)
  - ``glob``   — filename pattern listing
  - ``mkdir``  — create a directory tree inside the workspace
  - ``run``    — run an allowlisted command in the workspace
  - ``run_tests`` — auto-detect pytest/npm test and execute it
  - ``git``    — read-only git analysis (status/diff/log/...)

Every method returns ``{"ok": ...}`` (or contains ``blocked: True``) and never
raises for permission issues — the gate decides, the executor records.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from engine.executor.permissions import PermissionGate

_ENCODING = "utf-8"

# Text extensions we consider safe to read/write as text.
_TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".jsonl", ".yaml", ".yml",
    ".md", ".toml", ".ini", ".cfg", ".txt", ".html", ".css", ".csv", ".env.example",
    ".sh", ".ps1", ".bat", ".mjs", ".cjs",
}


class ScopedTools:
    def __init__(self, workspace: str | Path, gate: PermissionGate | None = None):
        self.workspace = Path(workspace).resolve()
        self.gate = gate or PermissionGate(self.workspace)

    # ------------------------------------------------------------- filesystem
    def read(self, path: str | Path, *, max_bytes: int = 200_000) -> dict:
        resolved = self.gate.resolve(str(path))
        if resolved is None:
            return {"ok": False, "blocked": True, "reason": "path escapes workspace"}
        if not resolved.is_file():
            return {"ok": False, "error": f"file not found: {resolved.relative_to(self.workspace)}"}
        try:
            raw = resolved.read_bytes()
            text = raw[:max_bytes].decode(_ENCODING, errors="replace")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        truncated = len(raw) > max_bytes
        return {
            "ok": True,
            "path": str(resolved.relative_to(self.workspace)),
            "bytes": len(raw),
            "lines": text.count("\n") + 1,
            "truncated": truncated,
            "content": text,
        }

    def write(self, path: str | Path, content: str) -> dict:
        verdict = self.gate.check_step("write", {"path": str(path)})
        allowed, _, reason = self.gate.decide(verdict)
        if not allowed:
            return {"ok": False, "blocked": True, "reason": reason}
        resolved = self.gate.resolve(str(path))
        assert resolved is not None  # check_step guarantees within workspace
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding=_ENCODING)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(resolved.relative_to(self.workspace)), "bytes": len(content.encode(_ENCODING))}

    def edit(self, path: str | Path, old: str, new: str) -> dict:
        verdict = self.gate.check_step("edit", {"path": str(path)})
        allowed, _, reason = self.gate.decide(verdict)
        if not allowed:
            return {"ok": False, "blocked": True, "reason": reason}
        resolved = self.gate.resolve(str(path))
        if resolved is None or not resolved.is_file():
            return {"ok": False, "error": f"file not found: {path}"}
        try:
            text = resolved.read_text(_ENCODING, errors="replace")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if old not in text:
            return {"ok": False, "error": "old string not found (no edit applied)"}
        updated = text.replace(old, new, 1)
        try:
            resolved.write_text(updated, encoding=_ENCODING)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "path": str(resolved.relative_to(self.workspace)),
            "replacements": 1,
        }

    def mkdir(self, path: str | Path) -> dict:
        resolved = self.gate.resolve(str(path))
        if resolved is None:
            return {"ok": False, "blocked": True, "reason": "path escapes workspace"}
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(resolved.relative_to(self.workspace))}

    def delete(self, path: str | Path) -> dict:
        verdict = self.gate.check_step("delete", {"path": str(path)})
        allowed, _, reason = self.gate.decide(verdict)
        if not allowed:
            return {"ok": False, "blocked": True, "reason": reason}
        resolved = self.gate.resolve(str(path))
        if resolved is None or not resolved.exists():
            return {"ok": False, "error": f"path not found: {path}"}
        try:
            if resolved.is_dir():
                return {"ok": False, "blocked": True, "reason": "directory deletion refused"}
            resolved.unlink()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(resolved.relative_to(self.workspace))}

    # ------------------------------------------------------------- searches
    def search(self, pattern: str, where: str | None = None, *, max_results: int = 50) -> dict:
        base = self.workspace
        if where:
            resolved = self.gate.resolve(str(where))
            if resolved is None:
                return {"ok": False, "blocked": True, "reason": "path escapes workspace"}
            base = resolved
        try:
            re.compile(pattern)
        except re.error as exc:
            return {"ok": False, "error": f"invalid regex: {exc}"}
        matches: list[dict] = []
        rg = shutil.which("rg")
        if rg:
            proc = subprocess.run(
                [rg, "--no-heading", "--line-number", "-e", pattern, str(base)],
                capture_output=True, text=True, timeout=60,
            )
            for raw in proc.stdout.splitlines():
                if len(matches) >= max_results:
                    break
                parts = raw.split(":", 2)
                if len(parts) == 3:
                    rel = _rel(Path(parts[0]), self.workspace)
                    matches.append({"file": rel, "line": int(parts[1]), "text": parts[2][:200]})
        else:
            for file_path in base.rglob("*"):
                if not file_path.is_file() or file_path.stat().st_size > 500_000:
                    continue
                if _is_binary(file_path):
                    continue
                try:
                    text = file_path.read_text(_ENCODING, errors="replace")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if re.search(pattern, line):
                        matches.append(
                            {"file": _rel(file_path, self.workspace), "line": lineno, "text": line[:200]}
                        )
                        if len(matches) >= max_results:
                            break
        return {"ok": True, "count": len(matches), "matches": matches}

    def glob(self, pattern: str) -> dict:
        files = [str(p.relative_to(self.workspace)) for p in self.workspace.rglob(pattern) if p.is_file()]
        return {"ok": True, "count": len(files), "files": files[:200]}

    # ------------------------------------------------------------- commands
    def run(
        self, command: str, *, timeout: int = 120, cwd: str | Path | None = None
    ) -> dict:
        verdict = self.gate.check_command(command)
        allowed, _, reason = self.gate.decide(verdict)
        if not allowed:
            return {"ok": False, "blocked": True, "reason": reason}
        cwd_path = self.workspace
        if cwd:
            resolved = self.gate.resolve(str(cwd))
            if resolved is None:
                return {"ok": False, "blocked": True, "reason": "cwd escapes workspace"}
            cwd_path = resolved
        argv = _resolve_argv(command)
        if argv is None:
            return {"ok": False, "error": f"executable not found: {_first_token(command)}"}
        creationflags = 0
        if os.name == "nt":
            # Detach child from any console dance (parent may be console-less);
            # avoids conhost creation contention that hangs nested py launches.
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"command timed out after {timeout}s", "timeout": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        stdout = (proc.stdout or "")[-6000:]
        stderr = (proc.stderr or "")[-6000:]
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
        }

    def run_tests(self, *, timeout: int = 600) -> dict:
        """Auto-detect and run the workspace test suite (pytest or npm test)."""
        if (self.workspace / "package.json").is_file():
            result = self.run("npm.cmd test", timeout=timeout)
            if result.get("ok") and "test" in _pkg_json(self.workspace):
                return result
            # fall through to pytest detection if npm run is not configured
        tests_dir = self.workspace / "tests"
        has_pytest = any(
            (self.workspace / cfg).is_file()
            for cfg in ("pytest.ini", "pyproject.toml", "tox.ini", "conftest.py")
        )
        target = tests_dir if tests_dir.is_dir() else self.workspace
        command = f'py -3 -m pytest -q --tb=short "{target}"'
        result = self.run(command, timeout=timeout)
        if result.get("blocked"):
            return result
        if result.get("ok"):
            summary = _pytest_summary(result)
            result["summary"] = summary
        return result

    def git(self, subcommand: str, *args: str) -> dict:
        tokens = [subcommand, *args]
        verdict = self.gate.check_command("git " + " ".join(tokens))
        allowed, _, reason = self.gate.decide(verdict)
        if not allowed:
            return {"ok": False, "blocked": True, "reason": reason}
        try:
            proc = subprocess.run(
                ["git", *tokens], cwd=str(self.workspace), capture_output=True, text=True, timeout=60
            )
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "command": "git " + " ".join(tokens),
            "stdout": (proc.stdout or "")[-8000:],
            "stderr": (proc.stderr or "")[-4000:],
        }

    def git_status(self) -> dict:
        return self.git("status", "--porcelain")

    def git_snapshot(self) -> dict:
        return {
            "status": self.git("status", "--porcelain").get("stdout", ""),
            "branch": self.git("branch", "--show-current").get("stdout", "").strip(),
            "last_commit": self.git("log", "-1", "--oneline").get("stdout", "").strip(),
            "diff": self.git("diff", "--stat").get("stdout", "").strip(),
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(1024)
    except OSError:
        return True


def _first_token(command: str) -> str:
    return command.strip().split(" ", 1)[0]


def _resolve_argv(command: str) -> list[str] | None:
    """Tokenize ``command`` and resolve the executable (PATHEXT-aware)."""
    from engine.executor.permissions import _split_command

    tokens = _split_command(command)
    if not tokens:
        return None
    exe = shutil.which(tokens[0])
    if exe is None and not tokens[0].lower().endswith((".cmd", ".exe", ".bat")):
        for suffix in (".cmd", ".exe", ".bat"):
            exe = shutil.which(tokens[0] + suffix)
            if exe:
                break
    if exe is None:
        return None
    return [exe, *tokens[1:]]


def _pytest_summary(result: dict) -> int:
    tail = result.get("stdout", "") + result.get("stderr", "")
    m = re.search(r"(\d+) passed", tail)
    return int(m.group(1)) if m else None


def _pkg_json(workspace: Path) -> dict:
    try:
        return json.loads((workspace / "package.json").read_text(_ENCODING))
    except Exception:
        return {}


__all__ = ["ScopedTools", "_TEXT_SUFFIXES"]