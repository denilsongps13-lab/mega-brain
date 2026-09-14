"""
engine/paths.py -- Canonical path constants for the Mega Brain repository.
===========================================================================

Single source of truth for every directory/file that the engine touches.
Modules import from here instead of hardcoding paths, so renames/migrations
happen in exactly one place.

Layout (repo root = ``ROOT``)::

    ROOT/
    ├── .claude/            CLAUDE
    │   ├── commands/       COMMANDS
    │   └── mission-control/ MISSION_CONTROL
    ├── core/               CORE        (rules, workflows, mce checkpoints)
    ├── engines/            AGENTS_*    (business / external / cargo)
    ├── knowledge/
    │   ├── external/       KNOWLEDGE_EXTERNAL (sources, dna, dossiers, playbooks)
    │   ├── business/       KNOWLEDGE_BUSINESS (insights, dossiers, sops, decisions)
    │   └── personal/       KNOWLEDGE_PERSONAL (email, messages, calls, cognitive)
    ├── workspace/          WORKSPACE   (businesses / strategy / team / templates / inbox)
    ├── inbox/              INBOX       (legacy personal drop folder)
    ├── processing/         PROCESSING  (staging areas for harvest pipelines)
    ├── logs/               LOGS
    ├── agents/             AGENTS
    └── .data/              DATA        (artifacts, rag index, knowledge graph, …)

``ROUTING`` table maps stable logical keys to concrete ``Path`` objects.
Consumers use ``ROUTING["<key>"]`` (strict) or ``ROUTING.get(...)`` (with
default). Keys are added here, never invented at call sites.

Inbox destinations live under the same convention the pipeline uses:

  * ``external_inbox``  -> ``knowledge/external/inbox/``
  * ``business_inbox``  -> ``knowledge/business/inbox/``
  * ``personal_inbox``  -> ``knowledge/personal/inbox/``
  * ``workspace_inbox`` -> ``workspace/inbox/``

Version: 1.0.0
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------
ROOT: Path = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Operational roots
# ---------------------------------------------------------------------------
DATA: Path = ROOT / ".data"
LOGS: Path = ROOT / "logs"
ARTIFACTS: Path = DATA / "artifacts"  # marker: S15 -- migrated from ROOT/artifacts
PROCESSING: Path = ROOT / "processing"
INBOX: Path = ROOT / "inbox"

# ---------------------------------------------------------------------------
# .claude subtree
# ---------------------------------------------------------------------------
CLAUDE: Path = ROOT / ".claude"
COMMANDS: Path = CLAUDE / "commands"
MISSION_CONTROL: Path = CLAUDE / "mission-control"

# ---------------------------------------------------------------------------
# core subtree
# ---------------------------------------------------------------------------
CORE: Path = ROOT / "core"

# ---------------------------------------------------------------------------
# knowledge buckets
# ---------------------------------------------------------------------------
KNOWLEDGE_EXTERNAL: Path = ROOT / "knowledge" / "external"
KNOWLEDGE_BUSINESS: Path = ROOT / "knowledge" / "business"
KNOWLEDGE_PERSONAL: Path = ROOT / "knowledge" / "personal"

# external: dna / dossiers / playbooks / sources
EXTERNAL_DNA_DOMAINS: Path = KNOWLEDGE_EXTERNAL / "dna" / "domains"
EXTERNAL_DNA_PERSONS: Path = KNOWLEDGE_EXTERNAL / "dna" / "persons"
EXTERNAL_SOURCES: Path = KNOWLEDGE_EXTERNAL / "sources"
EXTERNAL_DOSSIERS_PERSONS_BY_THEME: Path = KNOWLEDGE_EXTERNAL / "dossiers" / "persons-by-theme"

# business: decisions / dossiers / insights / sops
BUSINESS_DECISIONS: Path = KNOWLEDGE_BUSINESS / "decisions"
BUSINESS_DOSSIERS: Path = KNOWLEDGE_BUSINESS / "dossiers"
BUSINESS_INSIGHTS: Path = KNOWLEDGE_BUSINESS / "insights"
BUSINESS_SOPS: Path = KNOWLEDGE_BUSINESS / "sops"

# personal: calls / cognitive / email / messages
PERSONAL_CALLS: Path = KNOWLEDGE_PERSONAL / "calls"
PERSONAL_COGNITIVE: Path = KNOWLEDGE_PERSONAL / "cognitive"
PERSONAL_EMAIL: Path = KNOWLEDGE_PERSONAL / "email"
PERSONAL_MESSAGES: Path = KNOWLEDGE_PERSONAL / "messages"

# ---------------------------------------------------------------------------
# workspace subtree
# ---------------------------------------------------------------------------
WORKSPACE: Path = ROOT / "workspace"
WORKSPACE_INBOX: Path = WORKSPACE / "inbox"
WORKSPACE_ORG: Path = WORKSPACE / "org"
WORKSPACE_TEAM: Path = WORKSPACE / "team"
WORKSPACE_FINANCE: Path = WORKSPACE / "finance"
WORKSPACE_MEETINGS: Path = WORKSPACE / "meetings"
WORKSPACE_AUTOMATIONS: Path = WORKSPACE / "automations"
WORKSPACE_TOOLS: Path = WORKSPACE / "tools"
WORKSPACE_BUSINESSES: Path = WORKSPACE / "businesses"
WORKSPACE_STRATEGY: Path = WORKSPACE / "strategy"
WORKSPACE_TEMPLATES: Path = WORKSPACE / "_templates"

# ---------------------------------------------------------------------------
# agents subtree
# ---------------------------------------------------------------------------
AGENTS: Path = ROOT / "agents"
AGENTS_BUSINESS: Path = AGENTS / "business"
AGENTS_EXTERNAL: Path = AGENTS / "external"
AGENTS_CARGO: Path = AGENTS / "cargo"

# ---------------------------------------------------------------------------
# retrieval / graph
# ---------------------------------------------------------------------------
RAG_INDEX: Path = DATA / "rag_index"
RAG_BUSINESS: Path = DATA / "rag_business"
KNOWLEDGE_GRAPH: Path = DATA / "knowledge_graph"

# ---------------------------------------------------------------------------
# ROUTING table -- stable logical key -> concrete Path
# ---------------------------------------------------------------------------
ROUTING: dict[str, Path] = {
    # inboxes
    "external_inbox": KNOWLEDGE_EXTERNAL / "inbox",
    "business_inbox": KNOWLEDGE_BUSINESS / "inbox",
    "personal_inbox": KNOWLEDGE_PERSONAL / "inbox",
    "workspace_inbox": WORKSPACE / "inbox",
    # watcher daemon
    "watcher_state": DATA / "watcher-state.json",
    "watcher_log": LOGS / "inbox-watcher.jsonl",
    # Read.ai harvester
    "read_ai_log": DATA / "read-ai",
    "read_ai_state": DATA / "read-ai-state.json",
    "read_ai_staging": PROCESSING / "read-ai",
    # mce pipeline
    "mce_state": MISSION_CONTROL / "mce",
    "mce_metrics_log": LOGS / "mce-metrics.jsonl",
    "mce_cache": DATA / "mce_cache",
    # business knowledge
    "business_insights": KNOWLEDGE_BUSINESS / "insights",
    "business_dossiers": KNOWLEDGE_BUSINESS / "dossiers",
    "business_people": KNOWLEDGE_BUSINESS / "people",
    "business_dna": KNOWLEDGE_BUSINESS / "dna",
    "business_dna_persons": KNOWLEDGE_BUSINESS / "dna" / "persons",
    "business_sops": KNOWLEDGE_BUSINESS / "sops",
    "business_sources": KNOWLEDGE_BUSINESS / "sources",
    "business_dossiers_companies": KNOWLEDGE_BUSINESS / "dossiers" / "companies",
    # agents
    "agents_business": AGENTS / "business",
    # sync
    "workspace_sync_log": LOGS / "workspace-sync.jsonl",
    "memory_enricher_log": LOGS / "memory-enricher.jsonl",
    "ss_bridge_config": MISSION_CONTROL / "ss-bridge.yaml",
    "ss_bridge_log": LOGS / "ss-bridge.jsonl",
    # qa / governance
    "conclave_faithfulness_log": LOGS / "conclave-faithfulness.jsonl",
    "quality_gaps": LOGS / "quality-gaps",
    "handoff": LOGS / "handoffs",
    # batches
    "batch_registry": MISSION_CONTROL / "BATCH-REGISTRY.json",
    "batch_log": LOGS / "batches",
    "batch_auto_creator_log": LOGS / "batch-auto-creator.jsonl",
    # models
    "hhem_model": DATA / "models" / "hhem",
    # local autonomous runtime (engine/executor)
    "mega_brain_state": DATA / "megabrain" / "projects",
    "mega_brain_memory": DATA / "megabrain" / "memory-state.json",
    "mega_brain_session_log": DATA / "megabrain" / "sessions.jsonl",
    "mega_brain_runs": DATA / "megabrain" / "runs",
}

# ---------------------------------------------------------------------------
# Local autonomous runtime (engine/executor) — data-layer store under DATA.
# ---------------------------------------------------------------------------
MEGA_BRAIN_STORE: Path = DATA / "megabrain"
MEGA_BRAIN_PROJECTS: Path = MEGA_BRAIN_STORE / "projects"
MEGA_BRAIN_MEMORY_FILE: Path = MEGA_BRAIN_STORE / "memory-state.json"
MEGA_BRAIN_SESSION_LOG: Path = MEGA_BRAIN_STORE / "sessions.jsonl"
MEGA_BRAIN_RUNS: Path = MEGA_BRAIN_STORE / "runs"