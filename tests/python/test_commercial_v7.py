from datetime import datetime, timedelta, timezone
from decimal import Decimal

from engine.commercial.plans import get_offer
from engine.commercial.subscriptions import activate_paid_access, can_use, refresh_status, start_trial
from engine.commercial.sales import SalesService


def test_official_launch_prices():
    assert get_offer("plus", 30).price_brl == Decimal("19.90")
    assert get_offer("pro", 365).price_brl == Decimal("249.90")
    assert get_offer("ultra", 365).price_brl == Decimal("349.90")


def test_trial_blocks_after_three_days():
    start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    sub = start_trial("c1", start)
    assert can_use(sub, start + timedelta(days=2, hours=23))
    assert not can_use(sub, start + timedelta(days=3))
    assert refresh_status(sub, start + timedelta(days=3)).status == "blocked"


def test_paid_access_uses_selected_period():
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    sub = activate_paid_access(start_trial("c1", now), "pro", 60, payment_reference="safe-ref", now=now)
    assert sub.status == "paid"
    assert can_use(sub, now + timedelta(days=59))
    assert not can_use(sub, now + timedelta(days=60))


def test_sales_registration_starts_trial(tmp_path):
    service = SalesService(tmp_path)
    customer, sub = service.register("Cliente Teste", "TESTE@example.com", "instagram")
    assert customer.email == "teste@example.com"
    assert customer.source == "instagram"
    assert sub.status == "trial"
    assert service.subscriptions.get(customer.customer_id) is not None
