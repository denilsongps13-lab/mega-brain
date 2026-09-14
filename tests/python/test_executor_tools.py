"""Unit tests for scoped local tools of the runtime executor.

Covered: read/write/edit/mkdir/delete/share (git clean), search within
workspace only, glob confined to workspace, run_tests summary parsing, and
git snapshot never mutating state.
"""
from __future__ import annotations

import subprocess

import pytest

from engine.executor.permissions import PermissionGate
from engine.executor.tools import ScopedTools, _pytest_summary


@pytest.fixture()
def tools(tmp_path):
    return ScopedTools(str(tmp_path), gate=PermissionGate(str(tmp_path), mode="block"))


@pytest.fixture()
def permissive_tools(tmp_path):
    return ScopedTools(str(tmp_path), gate=PermissionGate(str(tmp_path), mode="allow"))


def test_write_read_roundtrip(tools, tmp_path):
    assert tools.write("notes.md", "hello").get("ok")
    res = tools.read("notes.md")
    assert res.get("ok")
    assert "hello" in res.get("content", "")


def test_write_outside_workspace_blocked(tools, tmp_path):
    res = tools.write(str(tmp_path.parent / "outside.txt"), "nope")
    assert not res.get("ok")
    assert res.get("blocked")


def test_edit(tools, tmp_path):
    tools.write("f.txt", "aa bb")
    res = tools.edit("f.txt", "aa", "cc")
    assert res.get("ok")
    assert "cc bb" == tools.read("f.txt").get("content", "").strip()


def test_edit_missing_old_returns_error(tools):
    res = tools.edit("g.txt", "zz", "yy")
    assert not res.get("ok")
    assert res.get("error")


def test_mkdir(tmp_path, permissive_tools):
    assert permissive_tools.mkdir("sub").get("ok")
    assert (tmp_path / "sub").is_dir()


def test_delete_file_in_subdir_allowed_in_allow_mode(tmp_path, permissive_tools):
    permissive_tools.mkdir("sub")
    permissive_tools.write("sub/a.txt", "1")
    assert (tmp_path / "sub" / "a.txt").exists()
    res = permissive_tools.delete("sub/a.txt")
    assert res.get("ok")
    assert not (tmp_path / "sub" / "a.txt").exists()


def test_delete_directory_refused_even_in_allow_mode(tmp_path, permissive_tools):
    permissive_tools.mkdir("sub")
    res = permissive_tools.delete("sub")
    assert not res.get("ok")
    assert res.get("blocked")


def test_delete_in_block_mode_blocked(tmp_path, tools):
    tools.mkdir("sub")
    tools.write("sub/a.txt", "1")
    res = tools.delete("sub/a.txt")
    assert not res.get("ok")
    assert res.get("blocked")


def test_glob_confined(tools, tmp_path):
    tools.write("a.txt", "1")
    tools.mkdir("d")
    tools.write("d/b.py", "x")
    names = tools.glob("**/*").get("files", [])
    assert any(n.endswith("a.txt") for n in names)
    assert any(n.endswith("b.py") for n in names)
    assert not any(n.startswith("..") for n in names)


def test_search_within_workspace(tools, tmp_path):
    tools.write("a.txt", "needle in hay")
    res = tools.search("needle")
    assert res.get("ok")
    assert any("a.txt" in n for n in (m.get("file") for m in res.get("matches", [])))
    assert not tools.search("needle", where=str(tmp_path.parent)).get("ok")


def test_unknown_command_denied(tools):
    res = tools.run("cmd.exe /c echo hi")
    assert not res.get("ok")
    assert res.get("blocked")


def test_run_tests_summary(tmp_path, tools):
    (tmp_path / "test_ok.py").write_text("def test_it():\n    assert 1\n", encoding="utf-8")
    res = tools.run_tests(timeout=120)
    assert res.get("ok")
    assert (res.get("summary") or 0) >= 1


def test_pytest_summary_returns_count():
    assert _pytest_summary({"stdout": "3 passed, 1 failed, 2 warnings in 1.2s"}) == 3
    assert _pytest_summary({"stdout": "1 passed in 0.1s"}) == 1
    assert _pytest_summary({"stdout": ""}) is None


def test_git_snapshot_non_mutating(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.dev"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "f.txt").write_text("1", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "c"], check=True)
    tools = ScopedTools(str(tmp_path), gate=PermissionGate(str(tmp_path), mode="block"))
    snap = tools.git_snapshot()
    assert snap.get("branch")
    assert snap.get("last_commit")
    assert "status" in snap
    assert subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain"], capture_output=True, text=True
    ).stdout.strip() == ""