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
    execute_task              -> executor.execute_objective (local runtime)
    project_context           -> executor.context.load_project_context
    mega_memory               -> executor.memory.ProjectMemory
    run_autonomous_pipeline   -> executor (resumes last objective)
    run_preflight             -> executor context checks
    check_workspace_health    -> workspace + memory health

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
# Local autonomous runtime (engine/executor)
# ---------------------------------------------------------------------------


def _execute_task(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.executor import execute_objective
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"execute_task unavailable: {exc}"}
    objective = kwargs.pop("objective", None)
    if not objective:
        return {"success": False, "error": "execute_task requires objective"}
    return execute_objective(
        objective,
        kwargs.pop("workspace", None),
        store_root=kwargs.pop("store_root", None),
        permission_mode=kwargs.pop("permission_mode", kwargs.pop("dangerous", "block")),
        max_attempts=int(kwargs.pop("max_attempts", 3)),
    )


def _project_context(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.executor.context import load_project_context
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"project_context unavailable: {exc}"}
    ctx = load_project_context(kwargs.pop("workspace", None), kwargs.pop("store_root", None))
    return {"success": bool(ctx.get("ok", True)), **ctx}


def _mega_memory(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.executor.memory import ProjectMemory
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"mega_memory unavailable: {exc}"}
    workspace = kwargs.pop("workspace", None)
    mem = ProjectMemory(workspace, store_root=kwargs.pop("store_root", None))
    return {
        "success": True,
        "store": str(mem.dir),
        "memory": mem.load(),
        "events": mem.recent_events(limit=kwargs.pop("limit", 20)),
        "markdown": mem.summary_markdown(),
    }


def _run_autonomous_pipeline(**kwargs: Any) -> dict[str, Any]:
    workspace = kwargs.pop("workspace", None)
    objective = kwargs.pop("objective", None)
    if not objective and workspace:
        try:
            from engine.executor.memory import ProjectMemory

            state = ProjectMemory(workspace).load()
            objective = state.get("current_objective") or state.get("last_objective")
        except Exception:
            objective = None
    if not objective:
        objective = kwargs.pop("last_objective", None) or (
            "Inspect the project state and report what changed since the last run."
        )
    kwargs["workspace"] = workspace  # pop() ed; re-add so stdout stays in-workspace
    kwargs.setdefault("objective", objective)
    return _execute_task(**kwargs)


def _run_preflight(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.executor.context import load_project_context
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"preflight unavailable: {exc}"}
    ctx = load_project_context(kwargs.pop("workspace", None))
    checks = []
    checks.append({"name": "python", "ok": bool(ctx.get("python"))})
    checks.append({"name": "workspace", "ok": bool(ctx.get("workspace"))})
    checks.append({"name": "memory_store", "ok": bool(ctx.get("store_dir"))})
    checks.append({"name": "model_router", "ok": bool(ctx.get("llm_available")), "note": "LLM providers offline -> deterministic planner"})
    if ctx.get("is_git_repo"):
        checks.append({"name": "git", "ok": True, "note": f"{ctx.get('branch')} @ {ctx.get('last_commit')}"})
    ok = all(c["ok"] for c in checks)
    return {"success": True, "ready": ok, "checks": checks, "summary": ctx.get("root")}


def _check_workspace_health(**kwargs: Any) -> dict[str, Any]:
    try:
        from engine.executor.context import load_project_context
    except Exception as exc:  # pragma: no cover - env-dependent import
        return {"success": False, "error": f"workspace health unavailable: {exc}"}
    ctx = load_project_context(kwargs.pop("workspace", None))
    mem = ctx.get("memory", {})
    return {
        "success": True,
        "healthy": bool(ctx.get("workspace") and ctx.get("store_dir")),
        "root": ctx.get("root"),
        "git": {"repo": ctx.get("is_git_repo"), "branch": ctx.get("branch"), "dirty_files": ctx.get("dirty_files")},
        "tests": ctx.get("test_command"),
        "models": {"gemini": ctx.get("llm_gemini"), "groq": ctx.get("llm_groq")},
        "memory": {"store": ctx.get("store_dir"), "last_objective": mem.get("last_objective"), "next_steps": mem.get("next_steps")},
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_OPERATIONS: dict[str, Any] = {
    "search_knowledge": _search_knowledge,
    "available_buckets": _available_buckets,
    "ingest": _ingest,
    "build_index": _build_index,
    "compile_dossier": _compile_dossier,
    "execute_task": _execute_task,
    "project_context": _project_context,
    "mega_memory": _mega_memory,
    "run_autonomous_pipeline": _run_autonomous_pipeline,
    "run_preflight": _run_preflight,
    "check_workspace_health": _check_workspace_health,
}


def list_operations() -> list[str]:
    """Names of all dispatchable operations."""
    return sorted(_OPERATIONS) + [
        "check_agent_health",
        "run_conclave",
        "validate_governance",
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