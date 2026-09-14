"""Sales funnel service for Mega Brain V7.

Orchestrates trial, plan selection and payment confirmation without coupling the
core to a specific Pix provider or social network.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

from .payments import PaymentGateway, payment_request
from .plans import get_offer
from .subscriptions import SubscriptionStore, activate_paid_access, refresh_status, start_trial


@dataclass
class Customer:
    customer_id: str
    name: str
    email: str
    source: str = "direct"


class CustomerStore:
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

    def save(self, customer: Customer) -> None:
        data = self._read()
        data[customer.customer_id] = asdict(customer)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, customer_id: str) -> Customer | None:
        raw = self._read().get(customer_id)
        return Customer(**raw) if raw else None


class SalesService:
    def __init__(self, data_dir: Path, gateway: PaymentGateway | None = None):
        self.customers = CustomerStore(data_dir / "customers.json")
        self.subscriptions = SubscriptionStore(data_dir / "subscriptions.json")
        self.gateway = gateway

    def register(self, name: str, email: str, source: str = "direct"):
        customer_id = self.subscriptions.create_customer()
        customer = Customer(customer_id, name.strip(), email.strip().lower(), source.strip().lower())
        self.customers.save(customer)
        sub = start_trial(customer_id)
        self.subscriptions.save(sub)
        return customer, sub

    def create_checkout(self, customer_id: str, tier: str, days: int):
        if self.gateway is None:
            raise RuntimeError("Gateway de pagamento ainda não configurado")
        if self.customers.get(customer_id) is None:
            raise ValueError("Cliente não encontrado")
        offer = get_offer(tier, days)
        return self.gateway.create_charge(payment_request(customer_id, offer))

    def confirm_payment(self, customer_id: str, reference: str, *, now: datetime | None = None):
        if self.gateway is None:
            raise RuntimeError("Gateway de pagamento ainda não configurado")
        charge = self.gateway.get_charge(reference)
        if charge.status.lower() not in {"paid", "approved", "confirmed"}:
            raise ValueError("Pagamento ainda não confirmado")
        sub = self.subscriptions.get(customer_id)
        if sub is None:
            raise ValueError("Assinatura não encontrada")
        # Tier/days are resolved from the pending checkout by provider integration.
        return charge, refresh_status(sub, now or datetime.now(timezone.utc))

    def activate_confirmed_offer(self, customer_id: str, tier: str, days: int, reference: str, *, now: datetime | None = None):
        sub = self.subscriptions.get(customer_id)
        if sub is None:
            raise ValueError("Assinatura não encontrada")
        sub = activate_paid_access(sub, tier, days, payment_reference=reference, now=now)
        self.subscriptions.save(sub)
        return sub
