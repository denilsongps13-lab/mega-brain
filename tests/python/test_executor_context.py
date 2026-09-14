"""Unit tests for project context loading of the local runtime."""
from __future__ import annotations

import subprocess

from engine.executor.context import detect_test_command, load_project_context
from engine.executor.memory import ProjectMemory


def test_context_basic(tmp_path):
    ctx = load_project_context(tmp_path, store_root=tmp_path / "store")
    assert ctx["ok"]
    assert ctx["root"] == str(tmp_path.resolve())
    assert ctx["project"] == tmp_path.name
    assert ctx["is_git_repo"] is False
    assert "llm_available" in ctx
    assert "memory" in ctx
    assert ctx["resume"]["next_steps"] == []


def test_context_git(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.dev"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "branch", "-M", "main"], check=True)
    (tmp_path / "b.txt").write_text("dirty", encoding="utf-8")
    ctx = load_project_context(tmp_path)
    assert ctx["is_git_repo"] is True
    assert ctx["branch"] == "main"
    assert ctx["last_commit"].endswith("init")
    assert ctx["dirty_files"] >= 1


def test_resume_from_memory(tmp_path):
    mem = ProjectMemory(tmp_path, store_root=tmp_path / "store")
    mem.set_objective("finish port")
    mem.set_next_steps(["fix s1"])
    ctx = load_project_context(tmp_path, store_root=tmp_path / "store")
    assert ctx["resume"]["current_objective"] == "finish port"
    assert ctx["resume"]["next_steps"] == ["fix s1"]


def test_pytest_dir_detected(tmp_path):
    (tmp_path / "tests").mkdir()
    assert detect_test_command(tmp_path) == "py -3 -m pytest -q"


def test_no_test_detected(tmp_path):
    assert detect_test_command(tmp_path) is None