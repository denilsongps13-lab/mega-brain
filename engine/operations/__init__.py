"""
engine/operations/__init__.py -- CLI operation dispatcher.
==========================================================

Single entry point for the ``mega-brain`` CLI subprocess contract
(bin/mega-brain.js L21)::

    from engine.operations import dispatch
    result = dispatch(<operation>, **json.loads(sys.argv[1]))
    print(json.dumps(result, default=str))

``dispatch`` returns a JSON-serializable dict for every operation. Each
handler lazily imports its backing module so importing this package never
pulls heavy dependencies or fails on missing third-party libs.

Registered operations (names come from bin/mega-brain.js):

    search_knowledge          -> rag.query_orchestrator.query
    available_buckets         -> rag.query_orchestrator.available_buckets
    ingest                    -> pipeline.inbox_processor.process_inbox_item
    build_index               -> rag.rebuild.rebuild
    compile_dossier           -> dossier.dossier_compiler.compile_dossier

Operations without a real backend today return a serializable error dict
(never raise), so the CLI can render them deterministically.

Version: 1.0.0
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Handlers (lazy imports, one per operation)
# ---------------------------------------------------------------------------


def _search_knowledge(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.intelligence.rag.query_orchestrator import query
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"search_knowledge unavailable: {exc}"}
    kwargs.setdefault("top_k", 10)
    results = query(kwargs.pop("query", ""), **kwargs)
    return {"success": True, "results": [r.to_dict() for r in results]}


def _available_buckets(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.intelligence.rag.query_orchestrator import available_buckets
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"available_buckets unavailable: {exc}"}
    return {"success": True, "buckets": available_buckets()}


def _ingest(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.intelligence.pipeline.inbox_processor import process_inbox_item
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"ingest unavailable: {exc}"}
    source_path = kwargs.pop("source_path", None)
    if not source_path:
        return {"success": False, "error": "ingest requires source_path"}
    result = process_inbox_item(source_path, kwargs.pop("bucket", None), **kwargs)
    return {"success": bool(result.get("success", True)), **result}


def _build_index(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.intelligence.rag.rebuild import rebuild
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"build_index unavailable: {exc}"}
    result = rebuild(bucket=kwargs.pop("bucket_name", None) or "all", **kwargs)
    return {"success": True, **result}


def _compile_dossier(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.intelligence.dossier.dossier_compiler import compile_dossier
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"compile_dossier unavailable: {exc}"}
    slug = kwargs.pop("persona", kwargs.pop("slug", None))
    if not slug:
        return {"success": False, "error": "compile_dossier requires persona"}
    dest = compile_dossier(
        slug=slug,
        category=kwargs.pop("category", "persons"),
        bucket=kwargs.pop("bucket", "external"),
        insight_ids=kwargs.pop("insight_ids", None),
    )
    return {"success": True, "dossier": str(dest)}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_OPERATIONS: dict[str, Any] = {
    "search_knowledge": _search_knowledge,
    "available_buckets": _available_buckets,
    "ingest": _ingest,
    "build_index": _build_index,
    "compile_dossier": _compile_dossier,
}


def list_operations() -> list[str]:
    """Names of all dispatchable operations."""
    return sorted(_OPERATIONS) + [
        "run_preflight",
        "check_agent_health",
        "run_conclave",
        "validate_governance",
        "check_workspace_health",
        "run_autonomous_pipeline",
    ]


def dispatch(operation: str, **kwargs: Any) -> dict[str, Any]:
    """Dispatch an operation, always returning a JSON-serializable dict.

    Args:
        operation: Operation name (see ``list_operations``).
        **kwargs: Operation-specific keyword arguments.

    Returns:
        ``{"success": True, ...}`` for handled operations, or
        ``{"success": False, "error": ...}`` when unknown / not implemented.
    """
    if operation == "list_operations":
        return {"success": True, "operations": list_operations()}
    handler = _OPERATIONS.get(operation)
    if handler is None:
        return {
            "success": False,
            "operation": operation,
            "error": f"operation not implemented: {operation}",
        }
    try:
        result = handler(**kwargs)
    except Exception as exc:  # keep the CLI contract total -- never raise
        return {"success": False, "operation": operation, "error": str(exc)}
    result.setdefault("operation", operation)
    return result