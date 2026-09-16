"""Provider primitives for Mega Brain Turbo Router V1.

The adapter is intentionally generic: any legitimate OpenAI-compatible service
can be enabled with environment variable *names*.  Credential values are never
logged or persisted by this module.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterator


class ProviderState(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READY = "READY"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


class ProviderFailure(RuntimeError):
    def __init__(self, provider: str, state: ProviderState, message: str) -> None:
        super().__init__(f"{provider}: {state.value}: {message}")
        self.provider = provider
        self.state = state


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    state: ProviderState
    consecutive_failures: int
    circuit_open_until: float | None


Transport = Callable[[str, str, str, float, int | None], str]


def classify_provider_error(exc: BaseException) -> ProviderState:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return ProviderState.RATE_LIMITED
    if isinstance(status, int) and status >= 500:
        return ProviderState.ERROR
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return ProviderState.TIMEOUT
    text = f"{type(exc).__name__}: {exc}".casefold()
    if "429" in text or "rate limit" in text or "rate_limit" in text:
        return ProviderState.RATE_LIMITED
    if "timeout" in text or "timed out" in text:
        return ProviderState.TIMEOUT
    return ProviderState.ERROR


class OpenAICompatibleProvider:
    """Small adapter for OpenAI-compatible chat-completions endpoints.

    Configuration is env-only and fail-closed.  The three required variables
    are API key, base URL and model.  An injected ``transport`` keeps unit tests
    network-free and also lets future adapters reuse the circuit breaker.
    """

    def __init__(
        self,
        *,
        name: str,
        api_key_env: str,
        base_url_env: str,
        model_env: str,
        timeout_env: str | None = None,
        default_base_url: str | None = None,
        default_model: str | None = None,
        default_timeout_s: float = 12.0,
        failure_threshold: int = 2,
        cooldown_s: float = 30.0,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.api_key_env = api_key_env
        self.base_url_env = base_url_env
        self.model_env = model_env
        self.timeout_env = timeout_env
        self.default_base_url = default_base_url
        self.default_model = default_model
        self.default_timeout_s = max(0.1, float(default_timeout_s))
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_s = max(0.0, float(cooldown_s))
        self._transport = transport
        self._clock = clock
        self._failures = 0
        self._open_until: float | None = None
        self._last_state = ProviderState.NOT_CONFIGURED

    def _config(self) -> tuple[str, str, str, float] | None:
        key = os.environ.get(self.api_key_env, "").strip()
        base = os.environ.get(self.base_url_env, "").strip() or (self.default_base_url or "")
        model = os.environ.get(self.model_env, "").strip() or (self.default_model or "")
        if not key or not base or not model:
            return None
        timeout = self.default_timeout_s
        if self.timeout_env:
            raw = os.environ.get(self.timeout_env, "").strip()
            if raw:
                try:
                    timeout = max(0.1, float(raw))
                except ValueError:
                    timeout = self.default_timeout_s
        return key, base.rstrip("/"), model, timeout

    @property
    def configured(self) -> bool:
        return self._config() is not None

    def health(self) -> ProviderHealth:
        now = self._clock()
        if self._open_until is not None and now >= self._open_until:
            self._open_until = None
            self._failures = 0
        state = self._last_state
        if not self.configured:
            state = ProviderState.NOT_CONFIGURED
        elif self._open_until is not None:
            state = ProviderState.CIRCUIT_OPEN
        elif state in (ProviderState.NOT_CONFIGURED, ProviderState.CIRCUIT_OPEN):
            state = ProviderState.READY
        return ProviderHealth(self.name, state, self._failures, self._open_until)

    def call(self, prompt: str, *, max_output_tokens: int | None = None) -> str:
        cfg = self._config()
        if cfg is None:
            self._last_state = ProviderState.NOT_CONFIGURED
            raise ProviderFailure(self.name, ProviderState.NOT_CONFIGURED, "provider is not configured")
        now = self._clock()
        if self._open_until is not None and now < self._open_until:
            self._last_state = ProviderState.CIRCUIT_OPEN
            raise ProviderFailure(self.name, ProviderState.CIRCUIT_OPEN, "circuit breaker is cooling down")
        if self._open_until is not None:
            self._open_until = None
            self._failures = 0

        key, base_url, model, timeout = cfg
        try:
            transport = self._transport or self._sdk_transport
            text = transport(prompt, key, base_url, timeout, max_output_tokens)
            self._failures = 0
            self._last_state = ProviderState.READY
            return text
        except ProviderFailure:
            raise
        except Exception as exc:
            state = classify_provider_error(exc)
            self._failures += 1
            self._last_state = state
            if self._failures >= self.failure_threshold:
                self._open_until = self._clock() + self.cooldown_s
            raise ProviderFailure(self.name, state, str(exc)) from exc

    def _sdk_transport(
        self,
        prompt: str,
        api_key: str,
        base_url: str,
        timeout: float,
        max_output_tokens: int | None,
    ) -> str:
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("openai SDK is required for OpenAI-compatible providers") from exc
        model = os.environ.get(self.model_env, "").strip() or self.default_model
        if not model:
            raise RuntimeError("model is not configured")
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        response = client.chat.completions.create(**kwargs)
        return (response.choices[0].message.content or "").strip()


def build_orcarouter_provider(*, transport: Transport | None = None) -> OpenAICompatibleProvider:
    """Build the optional OrcaRouter slot.

    No endpoint/model is guessed in code.  Operators must set the documented
    environment variables for the account they legitimately control.
    """
    return OpenAICompatibleProvider(
        name="orcarouter",
        api_key_env="ORCAROUTER_API_KEY",
        base_url_env="ORCAROUTER_BASE_URL",
        model_env="ORCAROUTER_MODEL",
        timeout_env="ORCAROUTER_TIMEOUT_S",
        transport=transport,
    )


__all__ = [
    "OpenAICompatibleProvider",
    "ProviderFailure",
    "ProviderHealth",
    "ProviderState",
    "build_orcarouter_provider",
    "classify_provider_error",
]
