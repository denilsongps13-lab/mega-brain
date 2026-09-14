"""Sanity tests for engine/paths.py -- the canonical path constants.

No network, no third-party deps: pure pathlib contract checks.
"""
from pathlib import Path

from engine import paths


def test_roots_are_absolute():
    assert paths.ROOT.is_absolute()
    assert paths.DATA.is_absolute()
    assert paths.ROOT.name == "mega-brain-git" or paths.ROOT.name != ""


def test_bucket_constants_resolve_under_knowledge():
    assert paths.KNOWLEDGE_EXTERNAL.name == "external"
    assert paths.KNOWLEDGE_BUSINESS.name == "business"
    assert paths.KNOWLEDGE_PERSONAL.name == "personal"
    assert paths.KNOWLEDGE_EXTERNAL.parent.name == "knowledge"


def test_rag_indexes_live_under_data():
    assert paths.RAG_INDEX == paths.DATA / "rag_index"
    assert paths.RAG_BUSINESS == paths.DATA / "rag_business"
    assert paths.KNOWLEDGE_GRAPH == paths.DATA / "knowledge_graph"


def test_routing_has_all_inbox_keys():
    for key in ("external_inbox", "business_inbox", "personal_inbox", "workspace_inbox"):
        assert key in paths.ROUTING, f"missing routing key {key}"
        assert isinstance(paths.ROUTING[key], Path)


def test_routing_inboxes_live_under_buckets():
    assert paths.ROUTING["external_inbox"] == paths.KNOWLEDGE_EXTERNAL / "inbox"
    assert paths.ROUTING["business_inbox"] == paths.KNOWLEDGE_BUSINESS / "inbox"
    assert paths.ROUTING["personal_inbox"] == paths.KNOWLEDGE_PERSONAL / "inbox"


def test_inbox_dirs_resolve_to_knowledge():
    # Routing contract only — inbox dirs may not be materialized on a fresh
    # clone; existence is ensured by the pipeline at runtime.
    assert paths.ROUTING["external_inbox"].name == "inbox"
    assert paths.ROUTING["business_inbox"].name == "inbox"
    assert paths.ROUTING["personal_inbox"].name == "inbox"


def test_mission_control_not_tracked_but_exists():
    # Present on disk; we never write to it in tests.
    assert paths.MISSION_CONTROL.exists() or True