from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from engine.commercial.plans import get_offer
from engine.commercial.subscriptions import activate_paid_access, can_use, refresh_status, start_trial
from engine.commercial.sales import SalesService
from engine.commercial.payments import PaymentCharge

class FakeGateway:
    def __init__(self): self.charges={}
    def create_charge(self, request):
        ref="tx-"+request.external_reference; c=PaymentCharge(ref,"pending",request.amount_brl,"pix-code",None,request.external_reference); self.charges[ref]=c; return c
    def get_charge(self, reference): return self.charges[reference]
    def pay(self, reference, amount=None, external_reference=None):
        old=self.charges[reference]; self.charges[reference]=PaymentCharge(reference,"paid",amount if amount is not None else old.amount_brl,old.pix_copy_paste,None,external_reference if external_reference is not None else old.external_reference)

def test_official_launch_prices_all_rows():
    expected={"plus":{7:"9.90",15:"14.90",30:"19.90",60:"34.90",90:"49.90",120:"59.90",365:"149.90"},"pro":{7:"14.90",15:"24.90",30:"34.90",60:"59.90",90:"79.90",120:"99.90",365:"249.90"},"ultra":{7:"19.90",15:"34.90",30:"49.90",60:"84.90",90:"109.90",120:"139.90",365:"349.90"}}
    for tier,rows in expected.items():
        for days,price in rows.items(): assert get_offer(tier,days).price_brl==Decimal(price)

def test_trial_blocks_after_three_days():
    start=datetime(2026,9,14,tzinfo=timezone.utc); sub=start_trial("c1",start); assert can_use(sub,start+timedelta(days=2,hours=23)); assert not can_use(sub,start+timedelta(days=3)); assert refresh_status(sub,start+timedelta(days=3)).status=="blocked"

def test_paid_access_and_active_renewal_extend():
    now=datetime(2026,9,14,tzinfo=timezone.utc); sub=activate_paid_access(start_trial("c1",now),"pro",60,payment_reference="a",now=now); activate_paid_access(sub,"pro",30,payment_reference="b",now=now+timedelta(days=10)); assert can_use(sub,now+timedelta(days=89)); assert not can_use(sub,now+timedelta(days=90))

def test_expired_renewal_starts_at_confirmation():
    now=datetime(2026,9,14,tzinfo=timezone.utc); sub=activate_paid_access(start_trial("c1",now),"plus",7,payment_reference="a",now=now); later=now+timedelta(days=20); activate_paid_access(sub,"plus",7,payment_reference="b",now=later); assert can_use(sub,later+timedelta(days=6)); assert not can_use(sub,later+timedelta(days=7))

def test_duplicate_email_cannot_repeat_trial(tmp_path):
    s=SalesService(tmp_path); s.register("A","TEST@example.com")
    with pytest.raises(ValueError): s.register("B"," test@example.com ")

def test_checkout_confirmation_verified_and_idempotent(tmp_path):
    g=FakeGateway(); s=SalesService(tmp_path,g); c,_=s.register("A","a@example.com"); checkout,charge=s.create_checkout(c.customer_id,"pro",30); assert checkout.checkout_id==charge.external_reference
    with pytest.raises(ValueError): s.confirm_payment(charge.reference)
    g.pay(charge.reference); now=datetime(2026,9,14,tzinfo=timezone.utc); sub=s.confirm_payment(charge.reference,now=now); until=sub.paid_until; assert s.confirm_payment(charge.reference,now=now+timedelta(days=1)).paid_until==until

def test_wrong_payment_never_activates(tmp_path):
    g=FakeGateway(); s=SalesService(tmp_path,g); c,_=s.register("A","a@example.com"); checkout,charge=s.create_checkout(c.customer_id,"plus",30)
    g.pay(charge.reference,amount=Decimal("1.00"))
    with pytest.raises(ValueError): s.confirm_payment(charge.reference)
    g.pay(charge.reference,external_reference="wrong")
    with pytest.raises(ValueError): s.confirm_payment(charge.reference)
