"""Tests for MCE state machine (transitions - real dependency).

Each test uses a unique slug + ``auto_load=False`` and redirects the
persistence path to a temp dir, so no state file leaks between tests and
nothing is written under .claude/mission-control.
"""
from pathlib import Path

from engine.intelligence.pipeline.mce.state_machine import (
    STATES,
    PipelineStateMachine,
)


def _sm(slug: str, tmp: Path) -> PipelineStateMachine:
    sm = PipelineStateMachine(slug, auto_load=False)
    sm._state_path = tmp / f"{slug}.yaml"  # redirect persistence off the repo
    return sm


def test_initial_state_is_init(tmp_path):
    assert _sm("tst-init", tmp_path).state == "init"


def test_has_start_ingest_trigger(tmp_path):
    assert hasattr(_sm("tst-trigger", tmp_path), "start_ingest")


def test_start_ingest_transition(tmp_path):
    sm = _sm("tst-trans", tmp_path)
    sm.start_ingest()
    assert sm.state == "ingesting"


def test_start_batch_transition(tmp_path):
    sm = _sm("tst-batch", tmp_path)
    sm.start_ingest()
    sm.start_batch()
    assert sm.state == "batching"


def test_serializable_state(tmp_path):
    sm = _sm("tst-serial", tmp_path)
    assert isinstance(sm.state, str)
    assert sm.state in STATES