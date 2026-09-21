"""Reuse TaskExecutor with web-safe file access and container-only commands."""

import os
import shlex
import shutil
import subprocess

from engine.executor.executor import TaskExecutor
from engine.executor.permissions import PermissionGate
from engine.executor.tools import ScopedTools


class WebGate(PermissionGate):
    def resolve(self, path):
        result = super().resolve(path)
        if result is None:
            return None
        relative = result.relative_to(self.workspace)
        if any(
            p.startswith(".")
            or p.lower() in ("node_modules", "__pycache__", "credentials", "secrets")
            for p in relative.parts
        ):
            return None
        if result.suffix.lower() in (".pem", ".key", ".p12", ".pfx"):
            return None
        return result

    def check_step(self, action, params):
        if action in ("write", "edit") and len(str(params.get("content", ""))) > 1_000_000:
            return "block", "File too large"
        return super().check_step(action, params)


class WebTools(ScopedTools):
    def search(self, pattern, where=None, *, max_results=50):
        # Literal search avoids untrusted regex CPU exhaustion and rg bypassing the gate.
        root = self.gate.resolve(where or "")
        if root is None:
            return {"ok": False, "blocked": True, "reason": "Protected path"}
        matches = []
        paths = [root] if root.is_file() else root.rglob("*")
        for p in paths:
            if self.gate.resolve(p) is None or not p.is_file() or p.stat().st_size > 500_000:
                continue
            for line, text in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if pattern.lower() in text.lower():
                    matches.append(
                        {
                            "file": str(p.relative_to(self.workspace)),
                            "line": line,
                            "text": text[:200],
                        }
                    )
                    if len(matches) >= max_results:
                        return {"ok": True, "count": len(matches), "matches": matches}
        return {"ok": True, "count": len(matches), "matches": matches}

    def glob(self, pattern):
        if ".." in pattern or pattern.startswith(("/", "\\")):
            return {"ok": False, "blocked": True, "reason": "Invalid pattern"}
        files = [
            str(p.relative_to(self.workspace))
            for p in self.workspace.rglob(pattern)
            if self.gate.resolve(p) is not None and p.is_file()
        ][:200]
        return {"ok": True, "count": len(files), "files": files}

    def git_snapshot(self):
        from engine.executor.context import _git

        return {
            "status": _git(self.workspace, "status", "--porcelain"),
            "branch": _git(self.workspace, "branch", "--show-current"),
            "last_commit": _git(self.workspace, "log", "-1", "--oneline"),
            "diff": _git(self.workspace, "diff", "--no-ext-diff", "--no-textconv", "--stat"),
        }

    def run(self, command, *, timeout=120, cwd=None):
        if not shutil.which("docker") or not os.getenv("APP_SANDBOX_IMAGE"):
            return {"ok": False, "blocked": True, "reason": "Command sandbox not configured"}
        argv = shlex.split(command)
        if not argv or argv[0] not in ("python", "python3", "pytest", "node", "npm", "git"):
            return {"ok": False, "blocked": True, "reason": "Executable not allowed"}
        root = self.gate.resolve(cwd or "")
        if root is None:
            return {"ok": False, "blocked": True, "reason": "Invalid working directory"}
        container_cwd = "/work/" + str(root.relative_to(self.workspace))
        # No host env, no network, no docker socket, bounded resources and no capabilities.
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                "megabrain-" + os.environ["APP_JOB_ID"],
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=128",
                "--memory=512m",
                "--cpus=1",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--tmpfs",
                "/tmp:rw,nosuid,size=128m",
                "-v",
                f"{self.workspace}:/work:rw",
                "-w",
                container_cwd,
                os.environ["APP_SANDBOX_IMAGE"],
                *argv,
            ],
            capture_output=True,
            text=True,
            timeout=min(int(timeout), 300),
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "summary": (proc.stdout + proc.stderr)[-10000:],
        }

    def run_tests(self, *, timeout=600):
        from engine.executor.test_runner import detect_test_command

        command = detect_test_command(self.workspace)
        if not command:
            return {"ok": False, "error": "No test suite found"}
        return self.run(command, timeout=timeout)


def execute(settings, objective, emit):
    def observer(name, payload):
        if name != "done":
            emit({"type": "phase", "state": name, **(payload or {})})

    executor = TaskExecutor(
        str(settings.workspace),
        store_root=str(settings.data / "memory"),
        permission_mode="block",
        phase_observer=observer,
    )
    executor.gate = WebGate(settings.workspace, mode="block")
    executor.tools = WebTools(settings.workspace, executor.gate)
    result = executor.run(objective)
    # A deterministic inventory is not fulfillment of an arbitrary natural-language goal.
    if result.get("planner") == "deterministic":
        result["limited"] = True
        result["limitation"] = "Sem planejamento LLM: somente inventário e testes disponíveis."
    if result.get("validation", {}).get("ok") is not True:
        result["limited"] = True
        result["limitation"] = result.get(
            "limitation", "Validação manual pendente; objetivo não confirmado."
        )
    return result
