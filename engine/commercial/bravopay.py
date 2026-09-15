"""BravoPay PIX adapter prepared from the working Nexora integration.

Credentials are read only from environment/configuration and never persisted in
source control. Webhook payment state is never trusted: callers must re-query
the authenticated transaction endpoint before activating access.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .payments import PaymentCharge, PaymentRequest

PAID_STATUSES = {"PAID", "APPROVED", "COMPLETED", "CONFIRMED"}


class BravoPayGateway:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, product_id: str | None = None, timeout: int = 15):
        self.api_key = api_key or os.getenv("BRAVOPAY_API_KEY")
        self.base_url = (base_url or os.getenv("BRAVOPAY_BASE_URL") or "https://bravopay.club/api/v1").rstrip("/")
        self.product_id = product_id or os.getenv("BRAVOPAY_PRODUCT_ID")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self.api_key:
            raise RuntimeError("BRAVOPAY_API_KEY não configurada")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = Request(f"{self.base_url}{path}", data=body, method=method, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"BravoPay HTTP {exc.code}: {detail[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"BravoPay indisponível: {exc.reason}") from exc

    def create_charge(self, request: PaymentRequest) -> PaymentCharge:
        payload = {"amount_cents": int(request.amount_brl * 100), "method": "pix", "external_reference": request.external_reference}
        if self.product_id:
            payload["product_id"] = self.product_id
        tx = self._request("POST", "/transactions", payload)
        pix = tx.get("pix") or {}
        if not tx.get("id") or not pix.get("copy_paste"):
            raise RuntimeError("BravoPay não retornou um PIX válido")
        return PaymentCharge(str(tx["id"]), normalize_status(tx.get("status")), request.amount_brl, pix.get("copy_paste"), pix.get("qr_code_url"), str(tx.get("external_reference") or request.external_reference))

    def get_charge(self, reference: str) -> PaymentCharge:
        tx = self._request("GET", f"/transactions/{quote(str(reference), safe='')}")
        cents = tx.get("amount_cents") or tx.get("amount") or 0
        amount = Decimal(str(cents)) / Decimal("100") if tx.get("amount_cents") is not None else Decimal(str(cents or 0))
        pix = tx.get("pix") or {}
        return PaymentCharge(str(tx.get("id") or reference), normalize_status(tx.get("status")), amount, pix.get("copy_paste"), pix.get("qr_code_url"), tx.get("external_reference"))

    def webhook_transaction_id(self, body: bytes) -> str:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Webhook BravoPay inválido") from exc
        tx_id = (payload.get("transaction") or {}).get("id")
        if not tx_id:
            raise ValueError("Webhook BravoPay inválido")
        return str(tx_id)

    def confirm_webhook_transaction(self, body: bytes) -> PaymentCharge:
        return self.get_charge(self.webhook_transaction_id(body))


def normalize_status(value) -> str:
    status = str(value or "PENDING").upper()
    return "paid" if status in PAID_STATUSES else status.lower()
