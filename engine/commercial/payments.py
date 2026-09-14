"""Payment contracts for Mega Brain V7.

Bravoo Pix will implement this interface after its official API contract is
mapped. Never persist gateway secrets or trust client-side payment status.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class PaymentRequest:
    customer_id: str
    tier: str
    days: int
    amount_brl: Decimal


@dataclass(frozen=True)
class PaymentCharge:
    reference: str
    status: str
    amount_brl: Decimal
    pix_copy_paste: str | None = None
    qr_code_url: str | None = None


class PaymentGateway(Protocol):
    def create_charge(self, request: PaymentRequest) -> PaymentCharge: ...
    def get_charge(self, reference: str) -> PaymentCharge: ...
    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool: ...


def payment_request(customer_id: str, offer) -> PaymentRequest:
    return PaymentRequest(customer_id=customer_id, tier=offer.tier, days=offer.days, amount_brl=offer.price_brl)
