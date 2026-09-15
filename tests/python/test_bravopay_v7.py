import json
from decimal import Decimal

import pytest

from engine.commercial.bravopay import BravoPayGateway, normalize_status
from engine.commercial.payments import PaymentRequest


def request():
    return PaymentRequest(
        customer_id="customer-1",
        tier="pro",
        days=30,
        amount_brl=Decimal("34.90"),
        external_reference="checkout-123",
    )


def test_gateway_configuration(monkeypatch):
    monkeypatch.delenv("BRAVOPAY_API_KEY", raising=False)
    gateway = BravoPayGateway(api_key=None)
    assert gateway.configured is False
    gateway = BravoPayGateway(api_key="secret-for-test")
    assert gateway.configured is True


def test_create_charge_maps_pix_without_real_network():
    gateway = BravoPayGateway(api_key="test", product_id="product-1")
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {
            "id": "tx-1",
            "status": "PAID",
            "external_reference": "checkout-123",
            "pix": {"copy_paste": "000201-test"},
        }

    gateway._request = fake_request
    charge = gateway.create_charge(request())
    assert captured["method"] == "POST"
    assert captured["path"] == "/transactions"
    assert captured["payload"]["amount_cents"] == 3490
    assert captured["payload"]["method"] == "pix"
    assert captured["payload"]["external_reference"] == "checkout-123"
    assert captured["payload"]["product_id"] == "product-1"
    assert charge.status == "paid"
    assert charge.pix_copy_paste == "000201-test"


def test_create_charge_rejects_invalid_pix_response():
    gateway = BravoPayGateway(api_key="test")
    gateway._request = lambda *args, **kwargs: {"id": "tx-1", "pix": {}}
    with pytest.raises(RuntimeError, match="PIX válido"):
        gateway.create_charge(request())


def test_get_charge_maps_amount_and_reference():
    gateway = BravoPayGateway(api_key="test")
    gateway._request = lambda *args, **kwargs: {
        "id": "tx-2",
        "status": "PENDING",
        "amount_cents": 990,
        "external_reference": "checkout-2",
        "pix": {"copy_paste": "pix"},
    }
    charge = gateway.get_charge("tx-2")
    assert charge.amount_brl == Decimal("9.90")
    assert charge.status == "pending"
    assert charge.external_reference == "checkout-2"


def test_legacy_webhook_only_extracts_id_then_requeries():
    gateway = BravoPayGateway(api_key="test")
    body = json.dumps({"transaction": {"id": "tx-3"}}).encode()
    assert gateway.webhook_transaction_id(body) == "tx-3"
    gateway.get_charge = lambda reference: reference
    assert gateway.confirm_webhook_transaction(body) == "tx-3"


def test_invalid_webhook_is_rejected():
    gateway = BravoPayGateway(api_key="test")
    for body in (b"not-json", b"{}"):
        with pytest.raises(ValueError, match="Webhook BravoPay inválido"):
            gateway.webhook_transaction_id(body)


def test_status_normalization():
    for status in ("PAID", "APPROVED", "COMPLETED", "CONFIRMED"):
        assert normalize_status(status) == "paid"
    assert normalize_status("EXPIRED") == "expired"
    assert normalize_status(None) == "pending"
