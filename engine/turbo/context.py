"""Deterministic conversation compaction for the Mega Brain fast path.

This module deliberately performs no LLM call.  It keeps system instructions
and the newest messages verbatim, then builds a small extractive summary from
older messages.  That makes compaction fast, predictable and cheap.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD))\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bbp_live_[A-Za-z0-9_-]{8,}\b"),
)

_CRITICAL_TERMS = (
    "mission", "missão", "decision", "decisão", "constraint", "restrição",
    "error", "erro", "exception", "failed", "falhou", "todo", "pending",
    "pendente", "file", "arquivo", "path", "caminho", "command", "comando",
    "evidence", "evidência", "result", "resultado", "status", "permission",
    "permissão", "guardian", "rate limit", "429", "timeout",
)


def redact_secrets(text: str) -> str:
    """Redact common credential shapes without attempting to validate them."""
    value = text
    for pattern in _SECRET_PATTERNS:
        if "API_KEY|TOKEN" in pattern.pattern:
            value = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
        else:
            value = pattern.sub("[REDACTED]", value)
    return value


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    return str(content)


def _message_text(message: dict[str, Any]) -> str:
    return _content_to_text(message.get("content"))


def estimate_tokens(messages: Iterable[dict[str, Any]], chars_per_token: int = 4) -> int:
    chars = sum(len(_message_text(m)) + len(str(m.get("role", ""))) + 8 for m in messages)
    return max(1, (chars + chars_per_token - 1) // chars_per_token) if chars else 0


@dataclass(frozen=True)
class CompactionStats:
    original_estimated_tokens: int
    compacted_estimated_tokens: int
    messages_before: int
    messages_after: int
    compression_ratio: float
    compacted: bool


@dataclass(frozen=True)
class CompactionResult:
    messages: list[dict[str, Any]]
    stats: CompactionStats


class ConversationContextCompactor:
    """Compact chat-style messages while preserving instructions and recency."""

    def __init__(
        self,
        threshold_tokens: int = 12_000,
        target_tokens: int = 6_000,
        keep_recent: int = 8,
        chars_per_token: int = 4,
    ) -> None:
        if threshold_tokens < 1 or target_tokens < 1:
            raise ValueError("token budgets must be positive")
        if target_tokens > threshold_tokens:
            raise ValueError("target_tokens must be <= threshold_tokens")
        if keep_recent < 1:
            raise ValueError("keep_recent must be positive")
        self.threshold_tokens = threshold_tokens
        self.target_tokens = target_tokens
        self.keep_recent = keep_recent
        self.chars_per_token = max(1, chars_per_token)

    def compact(self, messages: list[dict[str, Any]]) -> CompactionResult:
        source = [dict(m) for m in messages]
        original = estimate_tokens(source, self.chars_per_token)
        if original <= self.threshold_tokens:
            return self._result(source, source, original, compacted=False)

        system_messages = [dict(m) for m in source if str(m.get("role", "")).lower() == "system"]
        non_system = [m for m in source if str(m.get("role", "")).lower() != "system"]
        recent = [dict(m) for m in non_system[-self.keep_recent :]]
        old = non_system[: max(0, len(non_system) - self.keep_recent)]

        fixed = system_messages + recent
        fixed_tokens = estimate_tokens(fixed, self.chars_per_token)
        summary_budget = max(256, self.target_tokens - fixed_tokens)
        summary_text = self._extract_summary(old, summary_budget)

        output: list[dict[str, Any]] = []
        output.extend(system_messages)
        if summary_text:
            output.append({
                "role": "system",
                "content": "[Contexto compactado — conteúdo anterior]\n" + summary_text,
            })
        output.extend(recent)

        # A very large system/recent tail can itself exceed the target.  We do
        # not truncate those authoritative messages; preservation beats budget.
        return self._result(source, output, original, compacted=True)

    def _extract_summary(self, old: list[dict[str, Any]], budget_tokens: int) -> str:
        budget_chars = max(256, budget_tokens * self.chars_per_token)
        critical: list[str] = []
        ordinary: list[str] = []
        seen: set[str] = set()

        for message in old:
            role = str(message.get("role", "unknown"))
            text = redact_secrets(_message_text(message))
            for raw in text.splitlines():
                line = " ".join(raw.strip().split())
                if not line:
                    continue
                normalized = line.casefold()
                decorated = f"{role}: {line}"
                if decorated in seen:
                    continue
                seen.add(decorated)
                if any(term in normalized for term in _CRITICAL_TERMS):
                    critical.append(decorated)
                else:
                    ordinary.append(decorated)

        selected: list[str] = []
        used = 0
        # Critical lines first; then a small amount of chronological texture.
        for line in critical + ordinary:
            if len(selected) >= 80:
                break
            remaining = budget_chars - used
            if remaining <= 0:
                break
            clipped = line if len(line) <= remaining else line[: max(0, remaining - 1)] + "…"
            if clipped:
                selected.append("- " + clipped)
                used += len(clipped) + 3
            if len(clipped) < len(line):
                break
        return "\n".join(selected)

    def _result(
        self,
        before: list[dict[str, Any]],
        after: list[dict[str, Any]],
        original_tokens: int,
        *,
        compacted: bool,
    ) -> CompactionResult:
        final_tokens = estimate_tokens(after, self.chars_per_token)
        ratio = (final_tokens / original_tokens) if original_tokens else 1.0
        stats = CompactionStats(
            original_estimated_tokens=original_tokens,
            compacted_estimated_tokens=final_tokens,
            messages_before=len(before),
            messages_after=len(after),
            compression_ratio=round(ratio, 4),
            compacted=compacted,
        )
        return CompactionResult(messages=after, stats=stats)
