"""llm_router.py -- Pluggable LLM router for MCE pipeline steps
==================================================================

Why this exists
---------------
Every LLM call in the MCE pipeline used to go straight to Gemini Flash via
``llm_extractor.run_prompt``. That meant:

  - No way to swap providers without editing source (paralelização blocked).
  - No prompt caching (Anthropic SDK supports ephemeral 5min cache; reuse
    of long system prompts pays full input cost every time on Gemini).
  - No structured output via Anthropic ``tool_use`` (more deterministic
    than relying on Gemini's JSON-mode being well-behaved).
  - Latency for Sage steps (~3s per insight extraction call) is the
    single biggest contributor to MCE wall-clock time. Anthropic Haiku 4.5
    runs the same prompt in ~500ms.

This module exposes a thin abstraction:

  >>> router = LLMRouter()
  >>> router.run_prompt("Hi", provider="anthropic")
  '...response...'

Selection priority (highest first):

  1. Explicit ``provider=`` argument on the call.
  2. Env override per step: ``MCE_LLM_{STEP_UPPER}`` (e.g.
     ``MCE_LLM_INSIGHTS=anthropic`` redirects Sage.insight_extraction).
  3. Env default: ``MCE_LLM_PROVIDER`` (e.g. ``anthropic``).
  4. Built-in default: ``gemini`` (backward compat — preserves existing
     behaviour for all callers that haven't migrated yet).

The router never raises ``ImportError`` for a missing SDK — it falls back
to the configured default if the requested provider is unavailable. This
keeps tests/CI green even on machines that pinned only one provider.

Supported providers
-------------------
  - ``gemini``     -- google-genai (existing path; reused via llm_extractor)
  - ``anthropic``  -- anthropic SDK (Haiku 4.5 by default)
  - ``openai``     -- openai SDK (gpt-4o-mini by default)
  - ``groq``       -- openai SDK against Groq's OpenAI-compatible endpoint
    (``https://api.groq.com/openai/v1``, ``gpt-oss-120b`` by default, key from
    ``GROQ_API_KEY``). The default fallback for Gemini.

Resilient primary → fallback
----------------------------
When the selected provider IS the default (``gemini``), the router attempts it
ONCE and, on a transient transport failure (429/5xx/timeout/connection reset),
an unavailable provider (missing SDK/key), or an unconfigured Gemini path, drops
IMMEDIATELY to a single fallback attempt on ``groq``. No cooldown, no local RPM
limiter, no infinite loop — each call is independent, so the next call starts on
Gemini again. The fallback provider is tunable via ``MCE_LLM_FALLBACK_PROVIDER``.
For non-default selections the legacy behaviour is kept (fall back to the
configured default when the requested provider is unavailable).

Each provider exposes the same logical contract:
  - ``text``: str input (the assembled prompt)
  - ``structured_schema``: optional JSON-schema dict for structured output
  - ``tools``: optional OpenAI-style function-calling tool list
  - Returns: raw text response (str), or an iterator of str chunks when
    ``stream=True``.

Status
------
Added 2026-05-13 as part of V2 (Frente 2 of MCE 7→12 validation roadmap).
``llm_extractor.run_prompt`` now delegates here; existing call-sites work
unchanged with Gemini as default.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

from engine.intelligence.pipeline.mce.llm_retry import (
    MAX_LLM_RETRIES,
    is_transient_llm_error,
)

logger = logging.getLogger("mce.llm_router")


# ─────────────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_PROVIDER = "gemini"
_VALID_PROVIDERS = ("gemini", "anthropic", "openai", "groq")

_ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
_GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
_FALLBACK_DEFAULT_PROVIDER = "groq"
# Gemini default model is owned by llm_extractor (MCE_LLM_MODEL env).


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────


class LLMRouterError(RuntimeError):
    """Base class for router-level errors."""


class ProviderUnavailableError(LLMRouterError):
    """Raised when the requested provider has no usable SDK or credentials.

    The router catches this internally and falls back to the configured
    default; callers will only see it if BOTH the requested provider AND
    the fallback are unavailable.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Provider resolution
# ─────────────────────────────────────────────────────────────────────────────


def _step_env_var(step: str | None) -> str | None:
    """Map a step name to its env var (e.g. 'insights' -> 'MCE_LLM_INSIGHTS')."""
    if not step:
        return None
    cleaned = step.strip().upper().replace("-", "_").replace(".", "_")
    return f"MCE_LLM_{cleaned}"


def _resolve_provider(
    *,
    explicit: str | None,
    step: str | None,
) -> str:
    """Apply selection priority: explicit > step env > global env > default."""
    if explicit:
        normalized = explicit.strip().lower()
        if normalized not in _VALID_PROVIDERS:
            raise ValueError(f"Unknown provider {explicit!r} — expected one of {_VALID_PROVIDERS}")
        return normalized

    step_var = _step_env_var(step)
    if step_var:
        v = os.environ.get(step_var)
        if v:
            v = v.strip().lower()
            if v in _VALID_PROVIDERS:
                return v
            logger.warning(
                "Ignored invalid %s=%r — expected one of %s", step_var, v, _VALID_PROVIDERS
            )

    v = os.environ.get("MCE_LLM_PROVIDER", "").strip().lower()
    if v:
        if v in _VALID_PROVIDERS:
            return v
        logger.warning(
            "Ignored invalid MCE_LLM_PROVIDER=%r — expected one of %s", v, _VALID_PROVIDERS
        )

    return _DEFAULT_PROVIDER


def _resolve_fallback_env() -> str | None:
    """Resolve the fallback provider for the DEFAULT provider (gemini).

    ``MCE_LLM_FALLBACK_PROVIDER`` selects it; default is ``groq``. Returns
    ``None`` when unset-restricted or invalid so the router re-raises instead
    of guessing. Only applies when the chosen provider is the built-in default.
    """
    raw = os.environ.get("MCE_LLM_FALLBACK_PROVIDER", "").strip().lower()
    if raw:
        if raw not in _VALID_PROVIDERS:
            logger.warning(
                "Ignored invalid MCE_LLM_FALLBACK_PROVIDER=%r — expected one of %s",
                raw,
                _VALID_PROVIDERS,
            )
            return None
        return raw
    return _FALLBACK_DEFAULT_PROVIDER


def _fallback_for(chosen: str) -> str | None:
    """Pick the fallback for ``chosen``; ``None`` when there is none.

    Legacy behaviour: a non-default selection (e.g. explicit ``anthropic``)
    falls back to the configured default (``gemini``). When the default itself
    was chosen, the resilient Gemini → ``groq`` fallback applies. Never returns
    a provider equal to ``chosen`` (would be an infinite loop).
    """
    if chosen != _DEFAULT_PROVIDER:
        return None if _DEFAULT_PROVIDER == chosen else _DEFAULT_PROVIDER
    candidate = _resolve_fallback_env()
    if candidate == chosen:
        return None
    return candidate


def _is_provider_unavailable(exc: BaseException) -> bool:
    """True when the exception means the provider cannot serve, full stop.

    Covers the router's own ``ProviderUnavailableError`` and the Gemini path's
    ``LLMNotConfiguredError`` (no SDK / no API key). Both trigger the fallback.
    """
    if isinstance(exc, ProviderUnavailableError):
        return True
    try:
        from engine.intelligence.pipeline.mce.llm_extractor import (
            LLMNotConfiguredError,
        )
    except Exception:  # pragma: no cover — defensive import
        return False
    return isinstance(exc, LLMNotConfiguredError)


# ─────────────────────────────────────────────────────────────────────────────
# Gemini  (delegates to llm_extractor — preserves backward compat)
# ─────────────────────────────────────────────────────────────────────────────


def _run_gemini(
    prompt: str,
    *,
    max_output_tokens: int | None = None,
    structured_schema: dict | None = None,
    tools: list[dict] | None = None,
    max_attempts: int | None = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Call Gemini via the existing llm_extractor.run_prompt.

    ``structured_schema`` and ``tools`` are accepted but ignored on the Gemini
    path — the existing llm_extractor wraps a free-form text call. Callers that
    need Gemini structured output should keep using gemini_analyzer.py for the
    fixed-task surface. ``stream`` simulates streaming over the batch result
    (the project's existing pattern) so the router's streaming surface stays
    uniform across providers.

    ``max_attempts`` is forwarded to llm_extractor (default: its own 4). The
    router passes ``1`` when Gemini is primary in a fallback flow, so a single
    transient Gemini failure drops straight to the fallback provider.
    """
    from engine.intelligence.pipeline.mce import llm_extractor

    def _run() -> str:
        return llm_extractor._run_prompt_via_gemini(
            prompt,
            max_output_tokens=max_output_tokens,
            max_attempts=max_attempts,
        )

    if stream:

        def _stream():
            text = _run()
            if not text:
                return
            step = 96
            for i in range(0, len(text), step):
                yield text[i : i + step]

        return _stream()

    return _run()


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_anthropic_key() -> str | None:
    """Resolve Anthropic API key. Env first, fall back to .env at project root."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    env_file = root / ".env"
    if not env_file.exists():
        return None
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("ANTHROPIC_API_KEY="):
                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                if candidate:
                    os.environ.setdefault("ANTHROPIC_API_KEY", candidate)
                    return candidate
    except OSError as exc:
        logger.debug(".env read failed for Anthropic key: %s", exc)
    return None


def _run_anthropic(
    prompt: str,
    *,
    max_output_tokens: int | None = None,
    structured_schema: dict | None = None,
    model: str | None = None,
    tools: list[dict] | None = None,
    max_attempts: int | None = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Call Anthropic Claude Haiku (default) and return the text response.

    Prompt caching: the assembled prompt is sent as a single user message
    with ``cache_control=ephemeral``. Repeated calls inside the 5min TTL
    window reuse cached tokens (Anthropic charges only ~10% of input cost
    on cache hits). Per-step prompt templates therefore amortize nicely.

    Structured output: when ``structured_schema`` is provided, the prompt
    is wrapped in a ``tool_use`` definition so Claude is guaranteed to
    return JSON matching the schema. We then materialize the tool input
    as a JSON string and return it (callers can pass it to
    ``extract_json`` or parse directly).

    ``max_attempts`` threads through ``call_with_retry`` (default 4). When
    ``stream`` is True the return type is an iterator of text chunks rather
    than ``str``.
    """
    api_key = _resolve_anthropic_key()
    if not api_key:
        raise ProviderUnavailableError("ANTHROPIC_API_KEY not set")

    try:
        import anthropic  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ProviderUnavailableError(
            "anthropic SDK not installed — pip install anthropic"
        ) from exc

    from engine.intelligence.pipeline.mce.llm_retry import (
        call_with_retry,
        resolve_timeout_s,
    )

    chosen_model = (
        model or os.environ.get("MCE_LLM_ANTHROPIC_MODEL", "").strip() or _ANTHROPIC_DEFAULT_MODEL
    )
    max_tok = max_output_tokens or 4096
    attempts = max_attempts or MAX_LLM_RETRIES

    # NON-NEGOTIABLE: explicit transport timeout on the client. Without it the
    # Anthropic SDK can block indefinitely on a stalled TLS keep-alive when the
    # provider saturates under parallel ingest (the Cloudflare hang). The SDK's
    # own ``max_retries`` is disabled (=0) so our shared ``call_with_retry`` is
    # the single source of truth for backoff timing (no retry multiplication).
    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=resolve_timeout_s(),
        max_retries=0,
    )

    if structured_schema:
        tool_name = "emit_structured_output"
        # Anthropic input_schema follows JSON-schema dialect.
        schema_tools = [
            {
                "name": tool_name,
                "description": "Emit the structured output for this MCE step.",
                "input_schema": structured_schema,
            }
        ]
        if tools:
            schema_tools.extend(tools)

        def _structured_call() -> str:
            message = client.messages.create(
                model=chosen_model,
                max_tokens=max_tok,
                tools=schema_tools,
                tool_choice={"type": "tool", "name": tool_name},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
            )
            # Find the tool_use block.
            for block in message.content or []:
                if getattr(block, "type", None) == "tool_use":
                    import json as _json

                    return _json.dumps(block.input)
            # Should not happen given tool_choice=tool, but fall back gracefully.
            for block in message.content or []:
                if getattr(block, "type", None) == "text":
                    return block.text  # type: ignore[attr-defined]
            return ""

        return call_with_retry(_structured_call, max_attempts=attempts, label="anthropic")

    if stream:

        def _stream_gen():
            with client.messages.stream(
                model=chosen_model,
                max_tokens=max_tok,
                tools=tools or None,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
            ) as stream_ctx:
                for text in stream_ctx.text_stream:
                    yield text

        return _stream_gen()

    # Free-form text path
    def _freeform_call() -> str:
        message = client.messages.create(
            model=chosen_model,
            max_tokens=max_tok,
            tools=tools or None,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        )
        for block in message.content or []:
            if getattr(block, "type", None) == "text":
                return (block.text or "").strip()  # type: ignore[attr-defined]
        return ""

    return call_with_retry(_freeform_call, max_attempts=attempts, label="anthropic")


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_openai_key() -> str | None:
    """Resolve OpenAI API key. Env first, fall back to .env at project root."""
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    env_file = root / ".env"
    if not env_file.exists():
        return None
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("OPENAI_API_KEY="):
                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                if candidate:
                    os.environ.setdefault("OPENAI_API_KEY", candidate)
                    return candidate
    except OSError as exc:
        logger.debug(".env read failed for OpenAI key: %s", exc)
    return None


def _run_openai(
    prompt: str,
    *,
    max_output_tokens: int | None = None,
    structured_schema: dict | None = None,
    model: str | None = None,
    tools: list[dict] | None = None,
    max_attempts: int | None = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Call OpenAI gpt-4o-mini (default) and return the text response.

    Structured output: when ``structured_schema`` is provided, we use
    ``response_format={"type": "json_schema", ...}`` so the response is
    guaranteed to match the schema (OpenAI's strict structured output).
    Returns the JSON string verbatim; callers can ``json.loads`` it.

    ``tools`` (OpenAI function-calling format) is passed to the chat request;
    ``max_attempts`` threads through ``call_with_retry`` (default 4); when
    ``stream`` is True the return type is an iterator of text chunks.
    """
    api_key = _resolve_openai_key()
    if not api_key:
        raise ProviderUnavailableError("OPENAI_API_KEY not set")

    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ProviderUnavailableError("openai SDK not installed — pip install openai") from exc

    from engine.intelligence.pipeline.mce.llm_retry import (
        call_with_retry,
        resolve_timeout_s,
    )

    chosen_model = (
        model or os.environ.get("MCE_LLM_OPENAI_MODEL", "").strip() or _OPENAI_DEFAULT_MODEL
    )
    max_tok = max_output_tokens or 4096
    attempts = max_attempts or MAX_LLM_RETRIES

    # MCE-2.2 hunt: explicit timeout so httpx receive_response_headers cannot
    # stall the pipeline indefinitely (observed live hang in Step 5). The SDK's
    # own retries are disabled (=0) so our shared ``call_with_retry`` owns the
    # backoff timing — exponential + ±30% jitter + Retry-After floor, identical
    # to the Gemini/Anthropic/embedding paths (no retry multiplication).
    client = OpenAI(api_key=api_key, timeout=resolve_timeout_s(), max_retries=0)

    request_kwargs: dict = {
        "model": chosen_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tok,
    }
    if structured_schema and not tools:
        request_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "mce_step_output",
                "schema": structured_schema,
                "strict": False,
            },
        }
    if tools:
        request_kwargs["tools"] = tools

    if stream:

        def _stream_gen():
            stream_resp = client.chat.completions.create(**request_kwargs, stream=True)
            for chunk in stream_resp:
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield text

        return _stream_gen()

    def _freeform_call() -> str:
        response = client.chat.completions.create(**request_kwargs)
        choice = response.choices[0]
        return (choice.message.content or "").strip()

    return call_with_retry(_freeform_call, max_attempts=attempts, label="openai")


# ─────────────────────────────────────────────────────────────────────────────
# Groq  (OpenAI-compatible endpoint, same openai SDK)
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_groq_key() -> str | None:
    """Resolve Groq API key. Env first, fall back to .env at project root.

    Only the variable NAME is referenced — the value is handled exactly like
    the other provider keys (never logged).
    """
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    env_file = root / ".env"
    if not env_file.exists():
        return None
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("GROQ_API_KEY="):
                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                if candidate:
                    os.environ.setdefault("GROQ_API_KEY", candidate)
                    return candidate
    except OSError as exc:
        logger.debug(".env read failed for Groq key: %s", exc)
    return None


def _run_groq(
    prompt: str,
    *,
    max_output_tokens: int | None = None,
    structured_schema: dict | None = None,
    model: str | None = None,
    tools: list[dict] | None = None,
    max_attempts: int | None = None,
    stream: bool = False,
) -> str | Iterator[str]:
    """Call Groq's OpenAI-compatible chat endpoint and return the text response.

    Uses the SAME openai SDK as the ``openai`` provider against
    ``https://api.groq.com/openai/v1`` (override via ``GROQ_BASE_URL``) with a
    key from ``GROQ_API_KEY`` and ``gpt-oss-120b`` by default
    (``MCE_LLM_GROQ_MODEL`` override). Structured output uses OpenAI
    ``response_format``/json_schema; tool calling uses the OpenAI function
    format; ``stream=True`` returns an iterator of text chunks.
    """
    api_key = _resolve_groq_key()
    if not api_key:
        raise ProviderUnavailableError("GROQ_API_KEY not set")

    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ProviderUnavailableError(
            "openai SDK not installed — pip install openai (required for Groq)"
        ) from exc

    from engine.intelligence.pipeline.mce.llm_retry import (
        call_with_retry,
        resolve_timeout_s,
    )

    chosen_model = (
        model or os.environ.get("MCE_LLM_GROQ_MODEL", "").strip() or _GROQ_DEFAULT_MODEL
    )
    max_tok = max_output_tokens or 4096
    attempts = max_attempts or MAX_LLM_RETRIES
    base_url = os.environ.get("GROQ_BASE_URL", "").strip() or _GROQ_DEFAULT_BASE_URL

    # Same transport discipline as the other providers: explicit timeout and
    # SDK retries disabled so our shared ``call_with_retry`` owns backoff (no
    # retry multiplication, no unbounded hang).
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=resolve_timeout_s(),
        max_retries=0,
    )

    request_kwargs: dict = {
        "model": chosen_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tok,
    }
    if structured_schema and not tools:
        request_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "mce_step_output",
                "schema": structured_schema,
                "strict": False,
            },
        }
    if tools:
        request_kwargs["tools"] = tools

    if stream:

        def _stream_gen():
            stream_resp = client.chat.completions.create(**request_kwargs, stream=True)
            for chunk in stream_resp:
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield text

        return _stream_gen()

    def _freeform_call() -> str:
        response = client.chat.completions.create(**request_kwargs)
        choice = response.choices[0]
        return (choice.message.content or "").strip()

    return call_with_retry(_freeform_call, max_attempts=attempts, label="groq")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


class LLMRouter:
    """Stateless router. Picks a provider per call.

    The class is mostly a namespace — it carries no state today. A future
    iteration can add per-provider client caching here without touching
    call-sites.
    """

    def run_prompt(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        step: str | None = None,
        structured_schema: dict | None = None,
        max_output_tokens: int | None = None,
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> str:
        """Route the prompt to the chosen provider and return raw text.

        Resilient fallback (primary Gemini → ``groq``): when the chosen
        provider IS the built-in default, the router makes exactly ONE attempt
        on it and, on a transient transport error (429/5xx/timeout/conn reset),
        an unavailable provider (missing SDK/key) or an unconfigured Gemini
        path, drops IMMEDIATELY to a single fallback attempt on ``groq``. No
        cooldown, no local rate limiter, no retry loop — this call is done with
        the fallback result or its error. The NEXT call selects Gemini again.

        ``MCE_LLM_FALLBACK_PROVIDER`` overrides the fallback (default ``groq``).
        Non-transient errors are re-raised untouched (explicit behaviour); a
        failing fallback is also re-raised.

        Args:
            prompt: Assembled prompt (system + user instructions inline).
            provider: ``gemini`` | ``groq`` | ``anthropic`` | ``openai``. If
                omitted, the env-driven selection in ``_resolve_provider`` is
                used.
            step: Logical step name (e.g. ``insights``, ``behavioral``).
                Used to pick per-step env override
                (``MCE_LLM_{STEP_UPPER}``).
            structured_schema: Optional JSON-schema dict for structured
                output. Honored on anthropic + openai + groq; ignored on
                gemini (gemini path is text-only here; use
                gemini_analyzer.py for fixed-task structured calls).
            max_output_tokens: Optional cap on completion tokens.
            model: Override the per-provider default model.
            tools: Optional OpenAI-style function-calling tool list. Passed
                through to every provider path so the fallback preserves
                tool-use.

        Returns:
            The raw text response from the chosen provider. Use
            ``llm_extractor.extract_json`` to parse JSON envelopes.

        Raises:
            ProviderUnavailableError if BOTH the chosen and fallback
            providers are unavailable.
            ValueError if ``provider`` is an unknown identifier.
        """
        chosen = _resolve_provider(explicit=provider, step=step)
        fallback = _fallback_for(chosen)
        logger.debug(
            "LLMRouter.run_prompt(step=%s) -> provider=%s fallback=%s schema=%s",
            step,
            chosen,
            fallback,
            "yes" if structured_schema else "no",
        )

        primary_attempts = 1 if chosen == _DEFAULT_PROVIDER else None
        try:
            return self._dispatch(
                chosen,
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=model,
                tools=tools,
                max_attempts=primary_attempts,
            )
        except Exception as exc:
            # Non-transient → explicit failure, never mask it.
            if not fallback or fallback == chosen:
                raise
            if not (
                _is_provider_unavailable(exc) or is_transient_llm_error(exc)
            ):
                raise
            logger.warning(
                "LLM provider %s failed (%s: %s) — falling back to %s",
                chosen,
                type(exc).__name__,
                exc,
                fallback,
            )
            return self._dispatch(
                fallback,
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=None,  # fallback keeps its own model selection
                tools=tools,
                max_attempts=1,
            )

    def stream_prompt(
        self,
        prompt: str,
        *,
        provider: str | None = None,
        step: str | None = None,
        structured_schema: dict | None = None,
        max_output_tokens: int | None = None,
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> Iterator[str]:
        """Stream text chunks from the chosen provider (iterator of str).

        Fallback semantics mirror :meth:`run_prompt`: when the primary is the
        default provider and the stream fails with a transient / unavailable
        error BEFORE the first chunk is emitted, the stream restarts on the
        fallback provider. A failure AFTER output started is re-raised (the
        client already saw partial output — no invisible cut-over). Each call
        starts fresh on the primary provider.

        Returns:
            An iterator of ``str`` chunks. Consume with ``for chunk in ...``.
        """
        chosen = _resolve_provider(explicit=provider, step=step)
        fallback = _fallback_for(chosen)
        logger.debug(
            "LLMRouter.stream_prompt(step=%s) -> provider=%s fallback=%s",
            step,
            chosen,
            fallback,
        )

        primary_attempts = 1 if chosen == _DEFAULT_PROVIDER else None
        primary = self._dispatch_stream(
            chosen,
            prompt,
            max_output_tokens=max_output_tokens,
            structured_schema=structured_schema,
            model=model,
            tools=tools,
            max_attempts=primary_attempts,
        )
        yielded_chunk = False
        try:
            for chunk in primary:
                yielded_chunk = True
                yield chunk
        except Exception as exc:
            if yielded_chunk or not fallback or fallback == chosen:
                raise
            if not (_is_provider_unavailable(exc) or is_transient_llm_error(exc)):
                raise
            logger.warning(
                "LLM stream from %s failed before first chunk (%s: %s) — "
                "switching stream to %s",
                chosen,
                type(exc).__name__,
                exc,
                fallback,
            )
            yield from self._dispatch_stream(
                fallback,
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=None,
                tools=tools,
                max_attempts=1,
            )

    def _dispatch(
        self,
        provider: str,
        prompt: str,
        *,
        max_output_tokens: int | None,
        structured_schema: dict | None,
        model: str | None,
        tools: list[dict] | None = None,
        max_attempts: int | None = None,
    ) -> str:
        if provider == "gemini":
            return _run_gemini(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                tools=tools,
                max_attempts=max_attempts,
            )
        if provider == "anthropic":
            return _run_anthropic(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=model,
                tools=tools,
                max_attempts=max_attempts,
            )
        if provider == "openai":
            return _run_openai(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=model,
                tools=tools,
                max_attempts=max_attempts,
            )
        if provider == "groq":
            return _run_groq(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=model,
                tools=tools,
                max_attempts=max_attempts,
            )
        # Defensive — _resolve_provider should never produce anything else.
        raise ValueError(f"Unsupported provider {provider!r}")

    def _dispatch_stream(
        self,
        provider: str,
        prompt: str,
        *,
        max_output_tokens: int | None,
        structured_schema: dict | None,
        model: str | None,
        tools: list[dict] | None = None,
        max_attempts: int | None = None,
    ) -> Iterator[str]:
        if provider == "gemini":
            return _run_gemini(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                tools=tools,
                max_attempts=max_attempts,
                stream=True,
            )
        if provider == "anthropic":
            return _run_anthropic(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=model,
                tools=tools,
                max_attempts=max_attempts,
                stream=True,
            )
        if provider == "openai":
            return _run_openai(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=model,
                tools=tools,
                max_attempts=max_attempts,
                stream=True,
            )
        if provider == "groq":
            return _run_groq(
                prompt,
                max_output_tokens=max_output_tokens,
                structured_schema=structured_schema,
                model=model,
                tools=tools,
                max_attempts=max_attempts,
                stream=True,
            )
        # Defensive — _resolve_provider should never produce anything else.
        raise ValueError(f"Unsupported provider {provider!r}")


# Module-level convenience  ----------------------------------------------------

_router_singleton: LLMRouter | None = None


def get_router() -> LLMRouter:
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = LLMRouter()
    return _router_singleton


def run_prompt(
    prompt: str,
    *,
    provider: str | None = None,
    step: str | None = None,
    structured_schema: dict | None = None,
    max_output_tokens: int | None = None,
    model: str | None = None,
    tools: list[dict] | None = None,
) -> str:
    """Module-level shortcut to ``get_router().run_prompt(...)``."""
    return get_router().run_prompt(
        prompt,
        provider=provider,
        step=step,
        structured_schema=structured_schema,
        max_output_tokens=max_output_tokens,
        model=model,
        tools=tools,
    )


def stream_prompt(
    prompt: str,
    *,
    provider: str | None = None,
    step: str | None = None,
    structured_schema: dict | None = None,
    max_output_tokens: int | None = None,
    model: str | None = None,
    tools: list[dict] | None = None,
) -> Iterator[str]:
    """Module-level shortcut to ``get_router().stream_prompt(...)``."""
    return get_router().stream_prompt(
        prompt,
        provider=provider,
        step=step,
        structured_schema=structured_schema,
        max_output_tokens=max_output_tokens,
        model=model,
        tools=tools,
    )


def resolve_provider(step: str | None = None, explicit: str | None = None) -> str:
    """Public helper — useful for diagnostics + tests."""
    return _resolve_provider(explicit=explicit, step=step)


def is_provider_available(provider: str) -> bool:
    """Cheap probe — returns True if both SDK + credentials are present."""
    provider = provider.strip().lower()
    if provider == "gemini":
        try:
            from engine.intelligence.pipeline.mce.llm_extractor import is_available

            return is_available()
        except Exception:
            return False
    if provider == "anthropic":
        if not _resolve_anthropic_key():
            return False
        try:
            import anthropic  # noqa: F401

            return True
        except ImportError:
            return False
    if provider == "openai":
        if not _resolve_openai_key():
            return False
        try:
            import openai  # noqa: F401

            return True
        except ImportError:
            return False
    if provider == "groq":
        if not _resolve_groq_key():
            return False
        try:
            import openai  # noqa: F401

            return True
        except ImportError:
            return False
    return False


__all__ = [
    "LLMRouter",
    "LLMRouterError",
    "ProviderUnavailableError",
    "get_router",
    "is_provider_available",
    "resolve_provider",
    "run_prompt",
    "stream_prompt",
]
