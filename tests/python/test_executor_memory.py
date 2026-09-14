"""Unit tests for project memory persistence of the local runtime."""
from __future__ import annotations

from engine.executor.memory import ProjectMemory


def test_initial_state(tmp_path):
    mem = ProjectMemory(tmp_path)
    state = mem.load()
    assert state["current_objective"] is None
    assert state["decisions"] == []
    assert state["errors"] == []
    assert state["next_steps"] == []


def test_set_objective_rotates(tmp_path):
    mem = ProjectMemory(tmp_path)
    mem.set_objective("first")
    mem.set_objective("second")
    state = mem.load()
    assert state["current_objective"] == "second"
    assert state["last_objective"] == "first"


def test_record_mutations_persist(tmp_path):
    mem = ProjectMemory(tmp_path)
    mem.record_decision("use stubs")
    mem.record_task("port module", ok=True)
    mem.record_error("s1", "boom", 2)
    mem.record_solution("s1", "retried")
    mem.set_next_steps(["fix s1", "rerun"])
    state = mem.load()
    assert state["decisions"][-1]["text"] == "use stubs"
    assert state["completed"][-1]["task"] == "port module"
    assert state["errors"][-1]["error"] == "boom"
    assert state["errors"][-1]["attempts"] == 2
    assert state["solutions"][-1]["note"] == "retried"
    assert state["next_steps"] == ["fix s1", "rerun"]


def test_end_session_clears_current_keeps_last(tmp_path):
    mem = ProjectMemory(tmp_path)
    mem.set_objective("do thing")
    mem.end_session("done")
    state = mem.load()
    assert state["current_objective"] is None
    assert state["last_objective"] == "do thing"
    assert state["session_summary"] == "done"


def test_events_appended(tmp_path):
    mem = ProjectMemory(tmp_path)
    mem.set_objective("x")
    mem.record_error("s1", "e1", 1)
    events = mem.recent_events()
    assert [e["kind"] for e in events] == ["objective", "error"]


def test_reload_between_instances(tmp_path):
    ProjectMemory(tmp_path).set_objective("hello")
    assert ProjectMemory(tmp_path).load()["current_objective"] == "hello"


def test_store_root_respected(tmp_path):
    store = tmp_path / "data-store"
    mem = ProjectMemory(tmp_path, store_root=store)
    assert mem.dir.is_relative_to(store.resolve())
    mem.set_objective("t")
    assert (mem.dir / "memory.json").exists()


def test_summary_markdown_renders(tmp_path):
    mem = ProjectMemory(tmp_path)
    mem.set_objective("objective")
    mem.record_decision("a decision")
    md = mem.summary_markdown()
    assert "objective" in md
    assert "a decision" in md