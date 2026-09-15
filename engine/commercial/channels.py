"""Official-channel contracts for the V7 commercial automation layer.

Adapters must use each platform's supported API/OAuth flow. This module does
not store social passwords or implement scraping/spam automation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SUPPORTED_CHANNELS = ("instagram", "facebook", "tiktok", "kwai")


@dataclass(frozen=True)
class CampaignContent:
    title: str
    caption: str
    media_path: str | None = None
    call_to_action: str = "Comece seu teste de 3 dias grátis"


@dataclass(frozen=True)
class PublishResult:
    channel: str
    ok: bool
    external_id: str | None = None
    error: str | None = None


class SocialChannel(Protocol):
    name: str
    def publish(self, content: CampaignContent) -> PublishResult: ...


class CampaignPublisher:
    def __init__(self, channels: list[SocialChannel]):
        self.channels = channels

    def publish(self, content: CampaignContent) -> list[PublishResult]:
        results = []
        for channel in self.channels:
            try:
                results.append(channel.publish(content))
            except Exception as exc:
                results.append(PublishResult(channel=getattr(channel, "name", "unknown"), ok=False, error=str(exc)))
        return results
