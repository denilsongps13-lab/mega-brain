"""Subscription lifecycle for Mega Brain V7.

Payment-provider agnostic. A gateway such as Bravoo Pix can confirm a payment
and then call activate_paid_access; credentials never belong in this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid

from .plans import access_status, get_offer, subscription_expires, trial_expires


@dataclass
class Subscription:
    customer_id: str
    status: str
    trial_started_at: str | None = None
    trial_until: str | None = None
    tier: str | None = None
    days: int | None = None
    paid_started_at: str | None = None
    paid_until: str | None = None
    payment_reference: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def start_trial(customer_id: str, now: datetime | None = None) -> Subscription:
    now = now or _utcnow()
    end = trial_expires(now)
    return Subscription(customer_id=customer_id, status="trial", trial_started_at=_iso(now), trial_until=_iso(end))


def activate_paid_access(sub: Subscription, tier: str, days: int, *, payment_reference: str, now: datetime | None = None) -> Subscription:
    now = now or _utcnow()
    offer = get_offer(tier, days)
    sub.tier = offer.tier
    sub.days = offer.days
    sub.paid_started_at = _iso(now)
    sub.paid_until = _iso(subscription_expires(now, offer.days))
    sub.payment_reference = payment_reference
    sub.status = "paid"
    return sub


def refresh_status(sub: Subscription, now: datetime | None = None) -> Subscription:
    now = now or _utcnow()
    sub.status = access_status(now, trial_until=_dt(sub.trial_until), paid_until=_dt(sub.paid_until))
    return sub


def can_use(sub: Subscription, now: datetime | None = None) -> bool:
    return refresh_status(sub, now).status in {"trial", "paid"}


class SubscriptionStore:
    """Simple local JSON store; replaceable by a server database for Android/SaaS."""
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, sub: Subscription) -> None:
        data = self._read()
        data[sub.customer_id] = asdict(sub)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, customer_id: str) -> Subscription | None:
        raw = self._read().get(customer_id)
        return Subscription(**raw) if raw else None

    def create_customer(self) -> str:
        return uuid.uuid4().hex
