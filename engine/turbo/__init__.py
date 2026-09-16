"""Mega Brain Turbo Router V1.

A small, opt-in fast path that complements the existing MCE pipeline without
replacing it.  It provides deterministic context compaction, resilient extra
LLM providers and isolated parallel git-worktree execution.
"""

from .context import CompactionResult, CompactionStats, ConversationContextCompactor
from .providers import OpenAICompatibleProvider, ProviderFailure, ProviderState
from .router import TurboRouter
from .worktree import ParallelWorktreeRunner, WorktreeResult, WorktreeTask

__all__ = [
    "CompactionResult",
    "CompactionStats",
    "ConversationContextCompactor",
    "OpenAICompatibleProvider",
    "ProviderFailure",
    "ProviderState",
    "TurboRouter",
    "ParallelWorktreeRunner",
    "WorktreeResult",
    "WorktreeTask",
]
