"""Subscription lifecycle for Mega Brain V7."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json, uuid
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

def _utcnow(): return datetime.now(timezone.utc)
def _iso(value): return value.astimezone(timezone.utc).isoformat() if value else None
def _dt(value): return datetime.fromisoformat(value) if value else None

def start_trial(customer_id: str, now: datetime | None = None) -> Subscription:
    now = now or _utcnow()
    return Subscription(customer_id, "trial", _iso(now), _iso(trial_expires(now)))

def activate_paid_access(sub: Subscription, tier: str, days: int, *, payment_reference: str, now: datetime | None = None) -> Subscription:
    now = now or _utcnow(); offer = get_offer(tier, days)
    current_end = _dt(sub.paid_until)
    base = current_end if current_end and current_end > now else now
    sub.tier, sub.days = offer.tier, offer.days
    sub.paid_started_at = sub.paid_started_at or _iso(now)
    sub.paid_until = _iso(subscription_expires(base, offer.days))
    sub.payment_reference, sub.status = payment_reference, "paid"
    return sub

def refresh_status(sub: Subscription, now: datetime | None = None) -> Subscription:
    now = now or _utcnow(); sub.status = access_status(now, trial_until=_dt(sub.trial_until), paid_until=_dt(sub.paid_until)); return sub

def can_use(sub: Subscription, now: datetime | None = None) -> bool: return refresh_status(sub, now).status in {"trial", "paid"}

class SubscriptionStore:
    def __init__(self, path: Path): self.path=path; self.path.parent.mkdir(parents=True, exist_ok=True)
    def _read(self):
        if not self.path.exists(): return {}
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): return {}
    def save(self, sub):
        data=self._read(); data[sub.customer_id]=asdict(sub); self.path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    def get(self, customer_id):
        raw=self._read().get(customer_id); return Subscription(**raw) if raw else None
    def create_customer(self): return uuid.uuid4().hex
