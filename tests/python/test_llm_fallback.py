"""Unit tests for the resilient Gemini -> Groq model fallback in llm_router.

Covers the mission contract:
  - Gemini success -> Gemini (primary used).
  - Gemini 429 / 503 / timeout / transient -> Groq (immediate, 1 Gemini call).
  - Non-transient error -> explicit re-raise (Groq NOT called).
  - Next call after a fallback starts on Gemini again (stateless, no cooldown).
  - Streaming is preserved through the fallback (switch only before the first
    chunk; output already started is never silently cut over).
  - Tool-use / function calling is preserved on the fallback provider.
  - Gemini missing SDK/key (LLMNotConfiguredError) -> Groq.
  - Groq failure -> explicit error (no infinite retry loop).
  - Fallback provider tunable via MCE_LLM_FALLBACK_PROVIDER.
  - Legacy behaviour intact: explicit non-default provider unavailable falls
    back to the configured default (gemini).

All providers are mocked at module level — no real paid calls.
"""

from __future__ import annotations

import pytest

from engine.intelligence.pipeline.mce import llm_router
from engine.intelligence.pipeline.mce.llm_extractor import (
    LLMNotConfiguredError,
)
from engine.intelligence.pipeline.mce.llm_retry import (
    is_transient_llm_error,
)

TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup", "description": "look it up", "parameters": {}},
    }
]


def _chunks(*parts: str, exc: BaseException | None = None) -> object:
    def gen():
        if exc is not None:
            raise exc
        for part in parts:
            yield part

    return gen()


# ---------------------------------------------------------------------------
# text fallback (run_prompt)
# ---------------------------------------------------------------------------


def test_gemini_success_uses_gemini(monkeypatch):
    calls = {"gemini": 0, "groq": 0}

    def fake_gemini(prompt, **kwargs):
        calls["gemini"] += 1
        assert kwargs["max_attempts"] == 1
        return "GEMINI OK"

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        raise AssertionError("groq must not be called on gemini success")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    result = llm_router.run_prompt("hi")
    assert result == "GEMINI OK"
    assert calls == {"gemini": 1, "groq": 0}


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("429 client error: Too Many Requests for url"),
        RuntimeError('Response 429: {"error": {"code": 429}}'),
        RuntimeError("503 Server Error: Service Unavailable for url"),
        RuntimeError('Response 503: {"error": {"code": "overloaded"}}'),
        RuntimeError("APITimeoutError: Request timed out"),
        RuntimeError("ReadTimeout: timed out while reading response"),
        RuntimeError("ConnectionError: Connection reset by peer"),
    ],
    ids=["429", "429-json", "503", "503-overloaded", "timeout", "read-timeout", "conn-reset"],
)
def test_gemini_transient_fallbacks_to_groq_once(monkeypatch, exc):
    calls = {"gemini": 0, "groq": 0}

    def fake_gemini(prompt, **kwargs):
        calls["gemini"] += 1
        assert kwargs["max_attempts"] == 1
        raise exc

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        assert kwargs["max_attempts"] == 1
        return "GROQ OK"

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert llm_router.run_prompt("hi") == "GROQ OK"
    # Exactly one Gemini attempt, then a single Groq attempt — no retry loop.
    assert calls == {"gemini": 1, "groq": 1}
    assert is_transient_llm_error(exc)


def test_gemini_missing_sdk_or_key_fallbacks_to_groq(monkeypatch):
    calls = {"gemini": 0, "groq": 0}

    def fake_gemini(prompt, **kwargs):
        calls["gemini"] += 1
        raise LLMNotConfiguredError("GEMINI_API_KEY/GOOGLE_API_KEY not set")

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        return "GROQ OK"

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert llm_router.run_prompt("hi") == "GROQ OK"
    assert calls == {"gemini": 1, "groq": 1}


def test_gemini_non_transient_error_raises_without_fallback(monkeypatch):
    calls = {"groq": 0}

    def fake_gemini(prompt, **kwargs):
        raise ValueError("invalid api key")

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        return "GROQ OK"

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    with pytest.raises(ValueError, match="invalid api key"):
        llm_router.run_prompt("hi")
    assert calls == {"groq": 0}


def test_next_call_after_fallback_tries_gemini_again(monkeypatch):
    calls = {"gemini": 0, "groq": 0}

    def fake_gemini(prompt, **kwargs):
        calls["gemini"] += 1
        if calls["gemini"] == 1:
            raise RuntimeError("429 client error: Too Many Requests")
        return "GEMINI OK"

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        return "GROQ OK"

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert llm_router.run_prompt("hi") == "GROQ OK"
    assert llm_router.run_prompt("hi") == "GEMINI OK"
    # Call 1: gemini(429) -> groq. Call 2: gemini again (no cooldown).
    assert calls == {"gemini": 2, "groq": 1}


def test_groq_failure_raises_explicitly(monkeypatch):
    def fake_gemini(prompt, **kwargs):
        raise RuntimeError("429 client error: Too Many Requests")

    def fake_groq(prompt, **kwargs):
        raise RuntimeError("503 Server Error: Service Unavailable")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    # No infinite loop: primary once, fallback once, then explicit error.
    with pytest.raises(RuntimeError, match="Service Unavailable"):
        llm_router.run_prompt("hi")


def test_fallback_provider_via_env(monkeypatch):
    monkeypatch.setenv("MCE_LLM_FALLBACK_PROVIDER", "openai")
    calls = {"groq": 0, "openai": 0}

    def fake_gemini(prompt, **kwargs):
        raise RuntimeError("429 client error: Too Many Requests")

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        return "GROQ OK"

    def fake_openai(prompt, **kwargs):
        calls["openai"] += 1
        return "OPENAI OK"

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)
    monkeypatch.setattr(llm_router, "_run_openai", fake_openai)

    assert llm_router.run_prompt("hi") == "OPENAI OK"
    assert calls == {"groq": 0, "openai": 1}


def test_legacy_non_default_provider_unavailable_falls_to_default(monkeypatch):
    calls = {"anthropic": 0, "gemini": 0}

    def fake_anthropic(prompt, **kwargs):
        calls["anthropic"] += 1
        raise llm_router.ProviderUnavailableError("anthropic SDK not installed")

    def fake_gemini(prompt, **kwargs):
        calls["gemini"] += 1
        return "GEMINI OK"

    monkeypatch.setattr(llm_router, "_run_anthropic", fake_anthropic)
    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)

    assert llm_router.run_prompt("hi", provider="anthropic") == "GEMINI OK"
    assert calls == {"anthropic": 1, "gemini": 1}


# ---------------------------------------------------------------------------
# tool calling preserved (function calling)
# ---------------------------------------------------------------------------


def test_tool_calling_preserved_on_fallback(monkeypatch):
    seen = {}

    def fake_gemini(prompt, **kwargs):
        raise RuntimeError("429 client error: Too Many Requests")

    def fake_groq(prompt, **kwargs):
        seen["tools"] = kwargs.get("tools")
        seen["max_attempts"] = kwargs.get("max_attempts")
        assert kwargs.get("stream", False) is False
        return "TOOL DONE"

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert llm_router.run_prompt("go", tools=TOOLS) == "TOOL DONE"
    assert seen["tools"] == TOOLS
    assert seen["max_attempts"] == 1


def test_tool_calling_preserved_on_gemini_success(monkeypatch):
    seen = {}

    def fake_gemini(prompt, **kwargs):
        seen["tools"] = kwargs.get("tools")
        return "GEMINI TOOL OK"

    def fake_groq(prompt, **kwargs):
        raise AssertionError("groq must not be called")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert llm_router.run_prompt("go", tools=TOOLS) == "GEMINI TOOL OK"
    assert seen["tools"] == TOOLS


# ---------------------------------------------------------------------------
# streaming preserved
# ---------------------------------------------------------------------------


def test_streaming_gemini_success_preserves_stream(monkeypatch):
    calls = {"groq": 0}

    def fake_gemini(prompt, **kwargs):
        assert kwargs["stream"] is True
        assert kwargs["max_attempts"] == 1
        return _chunks("GEM ", "OK")

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        raise AssertionError("groq must not be called on gemini stream success")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert list(llm_router.stream_prompt("hi")) == ["GEM ", "OK"]
    assert calls == {"groq": 0}


def test_streaming_transient_before_first_chunk_switches_to_groq(monkeypatch):
    seen = {}

    def fake_gemini(prompt, **kwargs):
        assert kwargs["stream"] is True
        return _chunks(exc=RuntimeError("429 client error: Too Many Requests"))

    def fake_groq(prompt, **kwargs):
        seen["stream"] = kwargs.get("stream")
        return _chunks("GROQ ", "OK")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert list(llm_router.stream_prompt("hi")) == ["GROQ ", "OK"]
    assert seen["stream"] is True


def test_streaming_timeout_switches_to_groq(monkeypatch):
    def fake_gemini(prompt, **kwargs):
        return _chunks(exc=RuntimeError("APITimeoutError: Request timed out"))

    def fake_groq(prompt, **kwargs):
        return _chunks("GROQ OK")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    assert list(llm_router.stream_prompt("hi")) == ["GROQ OK"]


def test_streaming_non_transient_before_first_chunk_raises(monkeypatch):
    calls = {"groq": 0}

    def fake_gemini(prompt, **kwargs):
        return _chunks(exc=ValueError("invalid api key"))

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        return _chunks("GROQ OK")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    with pytest.raises(ValueError, match="invalid api key"):
        list(llm_router.stream_prompt("hi"))
    assert calls == {"groq": 0}


def test_streaming_failure_after_first_chunk_raises_no_cutover(monkeypatch):
    calls = {"groq": 0}

    def fake_gemini(prompt, **kwargs):
        def gen():
            yield "PARTIAL"
            raise RuntimeError("503 Server Error: Service Unavailable")

        return gen()

    def fake_groq(prompt, **kwargs):
        calls["groq"] += 1
        return _chunks("GROQ OK")

    monkeypatch.setattr(llm_router, "_run_gemini", fake_gemini)
    monkeypatch.setattr(llm_router, "_run_groq", fake_groq)

    with pytest.raises(RuntimeError, match="Service Unavailable"):
        list(llm_router.stream_prompt("hi"))
    # Output already started — never switch providers mid-stream.
    assert calls == {"groq": 0}


# ---------------------------------------------------------------------------
# contract / surface checks
# ---------------------------------------------------------------------------


def test_groq_endpoint_and_defaults():
    # Only variable NAMES are wired — values come from env at call time.
    assert llm_router._GROQ_DEFAULT_BASE_URL == "https://api.groq.com/openai/v1"
    assert llm_router._GROQ_DEFAULT_MODEL == "gpt-oss-120b"
    assert "groq" in llm_router._VALID_PROVIDERS
    assert "stream_prompt" in llm_router.__all__


def test_is_provider_available_groq(monkeypatch):
    monkeypatch.setattr(llm_router, "_resolve_groq_key", lambda: None)
    assert llm_router.is_provider_available("groq") is False

    monkeypatch.setattr(llm_router, "_resolve_groq_key", lambda: "synthetic-key")
    assert llm_router.is_provider_available("groq") is True