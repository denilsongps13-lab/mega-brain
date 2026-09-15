"""Secure sales funnel for Mega Brain V7."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import json, uuid
from .payments import PaymentGateway, payment_request
from .plans import get_offer
from .subscriptions import SubscriptionStore, activate_paid_access, start_trial

@dataclass
class Customer:
    customer_id: str; name: str; email: str; source: str = "direct"

@dataclass
class Checkout:
    checkout_id: str; customer_id: str; tier: str; days: int; amount_brl: str
    status: str = "created"; provider_reference: str | None = None; activated: bool = False

class JsonStore:
    def __init__(self,path:Path): self.path=path; path.parent.mkdir(parents=True,exist_ok=True)
    def read(self):
        if not self.path.exists(): return {}
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): return {}
    def write(self,data): self.path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

class CustomerStore(JsonStore):
    def save(self,c): d=self.read(); d[c.customer_id]=asdict(c); self.write(d)
    def get(self,i):
        raw=self.read().get(i); return Customer(**raw) if raw else None
    def by_email(self,email):
        target=email.strip().lower()
        for raw in self.read().values():
            if raw.get("email","").strip().lower()==target: return Customer(**raw)
        return None

class CheckoutStore(JsonStore):
    def save(self,c): d=self.read(); d[c.checkout_id]=asdict(c); self.write(d)
    def get(self,i):
        raw=self.read().get(i); return Checkout(**raw) if raw else None
    def by_provider(self,ref):
        for raw in self.read().values():
            if raw.get("provider_reference")==ref: return Checkout(**raw)
        return None

class SalesService:
    def __init__(self,data_dir:Path,gateway:PaymentGateway|None=None):
        self.customers=CustomerStore(data_dir/"customers.json"); self.subscriptions=SubscriptionStore(data_dir/"subscriptions.json"); self.checkouts=CheckoutStore(data_dir/"checkouts.json"); self.gateway=gateway
    def register(self,name,email,source="direct"):
        email=email.strip().lower()
        if not email or self.customers.by_email(email): raise ValueError("E-mail já cadastrado; teste grátis disponível uma única vez")
        cid=self.subscriptions.create_customer(); c=Customer(cid,name.strip(),email,source.strip().lower()); self.customers.save(c)
        sub=start_trial(cid); self.subscriptions.save(sub); return c,sub
    def create_checkout(self,customer_id,tier,days):
        if self.gateway is None: raise RuntimeError("Gateway de pagamento ainda não configurado")
        if self.customers.get(customer_id) is None: raise ValueError("Cliente não encontrado")
        offer=get_offer(tier,days); checkout=Checkout(uuid.uuid4().hex,customer_id,offer.tier,offer.days,str(offer.price_brl)); self.checkouts.save(checkout)
        charge=self.gateway.create_charge(payment_request(customer_id,offer,checkout.checkout_id)); checkout.provider_reference=charge.reference; checkout.status=charge.status; self.checkouts.save(checkout); return checkout,charge
    def confirm_payment(self,reference,*,now:datetime|None=None):
        if self.gateway is None: raise RuntimeError("Gateway de pagamento ainda não configurado")
        checkout=self.checkouts.by_provider(reference)
        if checkout is None: raise ValueError("Pagamento não pertence a um checkout conhecido")
        if checkout.activated: return self.subscriptions.get(checkout.customer_id)
        charge=self.gateway.get_charge(reference)
        if charge.reference != reference: raise ValueError("Referência de pagamento divergente")
        if charge.external_reference and charge.external_reference != checkout.checkout_id: raise ValueError("Checkout de pagamento divergente")
        if charge.status.lower() != "paid": raise ValueError("Pagamento ainda não confirmado")
        expected=Decimal(checkout.amount_brl)
        if charge.amount_brl != expected: raise ValueError("Valor de pagamento divergente")
        sub=self.subscriptions.get(checkout.customer_id)
        if sub is None: raise ValueError("Assinatura não encontrada")
        sub=activate_paid_access(sub,checkout.tier,checkout.days,payment_reference=reference,now=now); self.subscriptions.save(sub)
        checkout.status="paid"; checkout.activated=True; self.checkouts.save(checkout); return sub
