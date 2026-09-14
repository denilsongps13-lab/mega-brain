"""Unit tests for the permission gate of the local runtime executor.

The gate API returns verdict tuples ``(decision, reason)`` with decisions in
``{"allow", "block", "ask"}`` (see ``PermissionGate.check_*``), plus the
``decide`` mapper that applies the configured mode. Not a dict API.
"""
from __future__ import annotations

import pytest

import engine.executor.permissions as perms
from engine.executor.permissions import PermissionGate, _split_command


@pytest.fixture()
def gate(tmp_path):
    return PermissionGate(str(tmp_path), mode="block")


def test_split_command():
    assert _split_command("py -3 -m pytest tests/") == ["py", "-3", "-m", "pytest", "tests/"]
    assert _split_command('  git   "status"  --porcelain  ') == ["git", "status", "--porcelain"]
    assert _split_command("") == []


def test_allowed_executables_readable(gate, tmp_path):
    decision, reason = gate.check_command("git status --porcelain")
    assert decision == "allow" and reason is None
    decision, reason = gate.check_command("py -3 -m pytest tests/")
    assert decision == "allow"
    decision, reason = gate.check_command("node --version")
    assert decision == "allow"


def test_git_write_subcommands_blocked(gate):
    decision, _ = gate.check_command("git push")
    assert decision == "block"
    decision, _ = gate.check_command("git commit -m x")
    assert decision == "block"


def test_destructive_commands_blocked(gate):
    assert gate.check_command("rm -rf .")[0] == "block"
    assert gate.check_command("git reset --hard")[0] == "block"
    assert gate.check_command("git push --force")[0] == "block"
    assert gate.check_command("Remove-Item -Recurse -Force .")[0] == "block"
    assert gate.check_command("chmod 777 x")[0] == "block"


def test_env_files_write_blocked(gate, tmp_path):
    (tmp_path / ".env").write_text("x=1", encoding="utf-8")
    decision, reason = gate.check_path("write", str(tmp_path / ".env"))
    assert decision == "block" and "secret" in reason.lower()
    decision, _ = gate.check_path("read", str(tmp_path / ".env"))
    assert decision == "block"


def test_path_escape_blocked(gate, tmp_path):
    outside = tmp_path.parent / "elsewhere" / "secret.txt"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("s", encoding="utf-8")
    assert gate.check_path("read", str(outside))[0] == "block"
    assert gate.check_path("write", str(tmp_path / ".." / "x"))[0] == "block"


def test_in_workspace_read_allowed(gate, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hi", encoding="utf-8")
    assert gate.check_path("read", str(f)) == ("allow", None)


def test_top_level_delete_never_allowed(gate, tmp_path):
    d = tmp_path / "sub"
    d.mkdir()
    assert gate.check_path("delete", str(d))[0] == "block"
    assert gate.check_step("delete", {"path": str(d)})[0] == "block"


def test_unknown_executable_denied_in_block_mode(gate):
    assert gate.check_command("grep x")[0] == "block"


def test_allow_mode_permits_asks(tmp_path):
    permissive = PermissionGate(str(tmp_path), mode="allow")
    sub = tmp_path / "sub"
    sub.mkdir()
    f = sub / "a.txt"
    f.write_text("x", encoding="utf-8")
    verdict = permissive.check_path("delete", str(f))
    assert verdict[0] == "ask"
    allowed, confirm, _ = permissive.decide(verdict)
    assert allowed is True and confirm is False


def test_ask_mode_confirmation(tmp_path, monkeypatch):
    ask = PermissionGate(str(tmp_path), mode="ask")
    sub = tmp_path / "sub"
    sub.mkdir()
    f = sub / "a.txt"
    f.write_text("x", encoding="utf-8")
    verdict = ask.check_path("delete", str(f))
    monkeypatch.setattr(perms, "_prompt_confirm", lambda _reason: True)
    allowed, confirm, _ = ask.decide(verdict)
    assert allowed is True and confirm is False
    monkeypatch.setattr(perms, "_prompt_confirm", lambda _reason: False)
    allowed, confirm, _ = ask.decide(verdict)
    assert allowed is False and confirm is True


def test_block_mode_denies_ask_verdict(gate, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    f = sub / "a.txt"
    f.write_text("x", encoding="utf-8")
    allowed, confirm, reason = gate.decide(gate.check_path("delete", str(f)))
    assert allowed is False and confirm is False
    assert reason is not None


def test_check_run_uses_command_rules(gate):
    assert gate.check_run("git diff") == ("allow", None)
    assert gate.check_run("rm -rf src")[0] == "block"


def test_check_step_unknown_action_blocked(gate):
    assert gate.check_step("curl", {})[0] == "block"


def test_check_step_allowed_actions(gate):
    for action in ("read", "search", "glob", "context", "git_status"):
        assert gate.check_step(action, {})[0] == "allow", action
    assert gate.check_step("write", {"path": "a.txt"})[0] == "allow"
    assert gate.check_step("write", {})[0] == "block"