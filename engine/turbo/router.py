"""Mega Brain Turbo Router V1.

The existing MCE router remains authoritative for Gemini/Groq/OpenAI/Anthropic.
TurboRouter wraps it and adds optional extra providers, context compaction and
observable fallback without changing existing call sites.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .context import CompactionResult, ConversationContextCompactor
from .providers import (
    OpenAICompatibleProvider,
    ProviderFailure,
    ProviderState,
    build_orcarouter_provider,
)

logger = logging.getLogger("mega_brain.turbo_router")

CoreCall = Callable[..., str]


class TurboRouter:
    """Fast-path wrapper around the current Mega Brain LLM router.

    Flow: compact context (optional) -> existing core router -> optional extra
    providers.  The core router keeps its current Gemini -> Groq behaviour, so
    this class is additive and backward-compatible.
    """

    def __init__(
        self,
        *,
        core_call: CoreCall | None = None,
        extra_providers: list[OpenAICompatibleProvider] | None = None,
        compactor: ConversationContextCompactor | None = None,
    ) -> None:
        if core_call is None:
            from engine.intelligence.pipeline.mce.llm_router import run_prompt as core_call
        self._core_call = core_call
        self.extra_providers = list(extra_providers) if extra_providers is not None else [
            build_orcarouter_provider()
        ]
        self.compactor = compactor or ConversationContextCompactor()
        self.last_route: str | None = None
        self.last_failures: list[tuple[str, str]] = []

    def run_prompt(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        step: str | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Try the existing router first, then configured extra providers.

        Explicit ``provider`` is intentionally left to the existing MCE router;
        extra provider slots are fallback capacity, not a way to bypass provider
        quotas or account rules.
        """
        self.last_route = None
        self.last_failures = []
        try:
            response = self._core_call(
                prompt,
                provider=provider,
                step=step,
                max_output_tokens=max_output_tokens,
                **kwargs,
            )
            self.last_route = "core"
            return response
        except Exception as exc:
            self.last_failures.append(("core", type(exc).__name__))
            logger.warning("TurboRouter core path failed (%s); trying extra capacity", type(exc).__name__)

        last_error: BaseException | None = None
        for extra in self.extra_providers:
            health = extra.health()
            if health.state in (ProviderState.NOT_CONFIGURED, ProviderState.CIRCUIT_OPEN):
                self.last_failures.append((extra.name, health.state.value))
                continue
            try:
                response = extra.call(prompt, max_output_tokens=max_output_tokens)
                self.last_route = extra.name
                return response
            except ProviderFailure as exc:
                last_error = exc
                self.last_failures.append((extra.name, exc.state.value))
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("No Mega Brain LLM provider is currently available")

    def compact_messages(self, messages: list[dict[str, Any]]) -> CompactionResult:
        return self.compactor.compact(messages)

    def run_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: str | None = None,
        step: str | None = None,
        max_output_tokens: int | None = None,
    ) -> tuple[str, CompactionResult]:
        """Compact chat messages, assemble a prompt, then route it."""
        compacted = self.compact_messages(messages)
        parts: list[str] = []
        for message in compacted.messages:
            role = str(message.get("role", "user")).upper()
            content = message.get("content", "")
            parts.append(f"[{role}]\n{content}")
        response = self.run_prompt(
            "\n\n".join(parts),
            provider=provider,
            step=step,
            max_output_tokens=max_output_tokens,
        )
        return response, compacted

    def health_snapshot(self) -> dict[str, dict[str, Any]]:
        """Return provider state only; never include credential values."""
        result: dict[str, dict[str, Any]] = {}
        for provider in self.extra_providers:
            health = provider.health()
            result[provider.name] = {
                "state": health.state.value,
                "consecutive_failures": health.consecutive_failures,
                "circuit_open": health.circuit_open_until is not None,
            }
        return result


__all__ = ["TurboRouter"]
