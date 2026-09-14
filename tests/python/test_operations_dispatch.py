"""Tests for the CLI operation dispatcher (engine/operations/__init__.py).

Exercises the exact contract used by bin/mega-brain.js -- every call returns
a JSON-serializable dict, never raises.
"""
import json

from engine.operations import dispatch, list_operations


def test_list_operations_contract():
    result = dispatch("list_operations")
    assert result["success"] is True
    assert "operations" in result
    ops = result["operations"]
    assert "search_knowledge" in ops
    assert "ingest" in ops
    assert "build_index" in ops
    assert "available_buckets" in ops


def test_unknown_operation_returns_error_dict():
    result = dispatch("no_such_operation")
    assert result["success"] is False
    assert "error" in result


def test_available_buckets_returns_json_serializable():
    result = dispatch("available_buckets")
    assert result["success"] is True
    # Default backend returns a per-bucket stats dict.
    assert isinstance(result["buckets"], (dict, list))
    # Must be JSON-serializable (the CLI prints json.dumps(default=str)).
    json.dumps(result)


def test_ingest_requires_source_path():
    result = dispatch("ingest")
    assert result["success"] is False
    assert "source_path" in result.get("error", "")


def test_compile_dossier_requires_persona():
    result = dispatch("compile_dossier")
    assert result["success"] is False
    assert "persona" in result.get("error", "")


def test_search_knowledge_empty_query_does_not_raise():
    # Empty query with no built index must degrade to a serializable dict,
    # never raise (fail-open contract).
    result = dispatch("search_knowledge", query="")
    assert "success" in result
    json.dumps(result)