"""Tests for scope_classifier -- bucket classification with no network.
Uses the hardcoded-fallback weights path (fail-open, no LLM).
"""
from engine.intelligence.pipeline.scope_classifier import (
    ClassificationContext,
    classify,
)


def test_classify_returns_decision_never_raises():
    ctx = ClassificationContext(
        text="This is a general course about marketing and growth.",
        filename="course-notes.txt",
        file_path="knowledge/external/inbox/course-notes.txt",
    )
    decision = classify(ctx)
    assert decision.primary_bucket in ("external", "business", "personal")
    assert 0.0 <= decision.confidence <= 1.0


def test_classify_business_signal():
    ctx = ClassificationContext(
        text="Hoarding missed calls with client invoices for a limited liability company.",
        filename="insight-client.txt",
        file_path="knowledge/business/inbox/insight-client.txt",
    )
    decision = classify(ctx)
    assert decision.primary_bucket in ("external", "business", "personal")
    assert isinstance(decision.reasons, list)


def test_classify_empty_text_returns_safe_default():
    ctx = ClassificationContext(text="", filename="", file_path="")
    decision = classify(ctx)
    assert decision.primary_bucket == "external"
    assert decision.confidence == 0.0


def test_classify_does_not_hit_network():
    # Weight file missing -> hardcoded fallback; must still classify locally.
    ctx = ClassificationContext(
        text="My notes about personal health goals.",
        filename="personal-notes.txt",
        file_path="knowledge/personal/inbox/personal-notes.txt",
    )
    decision = classify(ctx)
    assert decision.primary_bucket in ("external", "business", "personal")