"""Secure payment contracts for Mega Brain V7."""
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
    external_reference: str


@dataclass(frozen=True)
class PaymentCharge:
    reference: str
    status: str
    amount_brl: Decimal
    pix_copy_paste: str | None = None
    qr_code_url: str | None = None
    external_reference: str | None = None


class PaymentGateway(Protocol):
    def create_charge(self, request: PaymentRequest) -> PaymentCharge: ...
    def get_charge(self, reference: str) -> PaymentCharge: ...


def payment_request(customer_id: str, offer, external_reference: str) -> PaymentRequest:
    return PaymentRequest(
        customer_id=customer_id,
        tier=offer.tier,
        days=offer.days,
        amount_brl=offer.price_brl,
        external_reference=external_reference,
    )
