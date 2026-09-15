"""Mega Brain V7 commercial plans and access rules.

Pure domain layer: no payment-provider credentials live here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

TRIAL_DAYS = 3


@dataclass(frozen=True)
class PlanOffer:
    tier: str
    days: int
    price_brl: Decimal
    usage_weight: int


# Launch pricing agreed for the accessible commercial edition.
_PRICES = {
    "plus": {7: "9.90", 15: "14.90", 30: "19.90", 60: "34.90", 90: "49.90", 120: "59.90", 365: "149.90"},
    "pro": {7: "14.90", 15: "24.90", 30: "34.90", 60: "59.90", 90: "79.90", 120: "99.90", 365: "249.90"},
    "ultra": {7: "19.90", 15: "34.90", 30: "49.90", 60: "84.90", 90: "109.90", 120: "139.90", 365: "349.90"},
}

# Internal cost-protection weights. These are implementation controls, not advertising claims.
_USAGE_WEIGHTS = {"plus": 30, "pro": 60, "ultra": 100}


def offers() -> list[PlanOffer]:
    return [
        PlanOffer(tier, days, Decimal(price), _USAGE_WEIGHTS[tier])
        for tier, periods in _PRICES.items()
        for days, price in periods.items()
    ]


def get_offer(tier: str, days: int) -> PlanOffer:
    key = tier.strip().lower()
    try:
        price = _PRICES[key][int(days)]
    except (KeyError, ValueError):
        raise ValueError("Plano ou período inválido") from None
    return PlanOffer(key, int(days), Decimal(price), _USAGE_WEIGHTS[key])


def trial_expires(started_at: datetime) -> datetime:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at + timedelta(days=TRIAL_DAYS)


def subscription_expires(activated_at: datetime, days: int) -> datetime:
    if activated_at.tzinfo is None:
        activated_at = activated_at.replace(tzinfo=timezone.utc)
    return activated_at + timedelta(days=int(days))


def access_status(now: datetime, *, trial_until: datetime | None = None, paid_until: datetime | None = None) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if paid_until and now < paid_until:
        return "paid"
    if trial_until and now < trial_until:
        return "trial"
    return "blocked"
