from __future__ import annotations

import hmac
import json
import time
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

import pytest
from fastapi import HTTPException

from app.services.billing import (
    BillingService,
    StripeCustomer,
    StripeSession,
    verify_stripe_signature,
)
from tests.fakes.fake_db import FakeDB

USER = "user-billing"


@dataclass
class FakeGateway:
    customers: list[dict[str, str]] = field(default_factory=list)
    checkout_sessions: list[dict[str, Any]] = field(default_factory=list)
    portal_sessions: list[dict[str, Any]] = field(default_factory=list)

    def create_customer(self, *, email: str, user_id: str) -> StripeCustomer:
        self.customers.append({"email": email, "user_id": user_id})
        return StripeCustomer(id="cus_test")

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        user_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax_enabled: bool,
    ) -> StripeSession:
        self.checkout_sessions.append(
            {
                "customer_id": customer_id,
                "user_id": user_id,
                "price_id": price_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "automatic_tax_enabled": automatic_tax_enabled,
            }
        )
        return StripeSession(id="cs_test", url="https://checkout.stripe.com/c/pay/cs_test")

    def create_portal_session(self, *, customer_id: str, return_url: str) -> StripeSession:
        self.portal_sessions.append({"customer_id": customer_id, "return_url": return_url})
        return StripeSession(id="bps_test", url="https://billing.stripe.com/p/session")


def _service(settings, db: FakeDB | None = None) -> tuple[BillingService, FakeDB, FakeGateway]:
    settings.stripe_pro_price_id = "price_pro"
    settings.website_url = "http://localhost:3000"
    settings.pro_monthly_eval_limit = 5000
    settings.pro_monthly_cv_tailoring_limit = 20
    fake_db = db or FakeDB()
    gateway = FakeGateway()
    return BillingService(fake_db, settings, gateway), fake_db, gateway


def test_checkout_creates_customer_once_and_returns_stripe_url(settings) -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "plan": "free"}])
    svc, db, gateway = _service(settings, db)

    url = svc.create_checkout_session(user_id=USER, email="user@example.com")

    assert url == "https://checkout.stripe.com/c/pay/cs_test"
    assert gateway.customers == [{"email": "user@example.com", "user_id": USER}]
    assert gateway.checkout_sessions[0]["customer_id"] == "cus_test"
    assert gateway.checkout_sessions[0]["price_id"] == "price_pro"
    assert gateway.checkout_sessions[0]["automatic_tax_enabled"] is True
    assert db.store.tables["profiles"][0]["stripe_customer_id"] == "cus_test"


def test_checkout_reuses_existing_customer(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [{"id": USER, "plan": "free", "stripe_customer_id": "cus_existing"}],
    )
    svc, _db, gateway = _service(settings, db)

    svc.create_checkout_session(user_id=USER, email="user@example.com")

    assert gateway.customers == []
    assert gateway.checkout_sessions[0]["customer_id"] == "cus_existing"


def test_checkout_completed_upgrades_profile(settings) -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "plan": "free", "monthly_eval_limit": 200}])
    svc, db, _gateway = _service(settings, db)

    svc.handle_event(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "subscription",
                    "client_reference_id": USER,
                    "customer": "cus_test",
                    "subscription": "sub_test",
                }
            },
        }
    )

    profile = db.store.tables["profiles"][0]
    assert profile["plan"] == "pro"
    assert profile["monthly_eval_limit"] == 5000
    assert profile["monthly_cv_tailoring_limit"] == 20
    assert profile["stripe_customer_id"] == "cus_test"
    assert profile["stripe_subscription_id"] == "sub_test"


def test_active_subscription_with_cancel_at_period_end_keeps_pro(settings) -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "stripe_customer_id": "cus_test"}])
    svc, db, _gateway = _service(settings, db)

    svc.handle_event(
        {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test",
                    "customer": "cus_test",
                    "status": "active",
                    "cancel_at_period_end": True,
                    "current_period_end": 1_800_000_000,
                    "items": {"data": [{"price": {"id": "price_pro"}}]},
                }
            },
        }
    )

    profile = db.store.tables["profiles"][0]
    assert profile["plan"] == "pro"
    assert profile["stripe_cancel_at_period_end"] is True
    assert db.store.tables["subscriptions"][0]["status"] == "active"


def test_canceled_subscription_downgrades_profile(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": USER,
                "plan": "pro",
                "stripe_subscription_id": "sub_test",
                "monthly_eval_limit": 5000,
                "monthly_cv_tailoring_limit": 20,
            }
        ],
    )
    svc, db, _gateway = _service(settings, db)

    svc.handle_event(
        {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_test",
                    "customer": "cus_test",
                    "status": "canceled",
                    "cancel_at_period_end": False,
                    "items": {"data": [{"price": {"id": "price_pro"}}]},
                }
            },
        }
    )

    profile = db.store.tables["profiles"][0]
    assert profile["plan"] == "free"
    assert profile["monthly_eval_limit"] == 200
    assert profile["monthly_cv_tailoring_limit"] == 0


def test_portal_session_requires_existing_customer(settings) -> None:
    svc, _db, _gateway = _service(settings)

    with pytest.raises(HTTPException) as exc:
        svc.create_portal_session(user_id=USER)

    assert exc.value.status_code == 404


def test_verify_stripe_signature_accepts_valid_payload() -> None:
    payload = json.dumps({"type": "ping", "data": {"object": {}}}).encode("utf-8")
    secret = "whsec_test"
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.{payload.decode()}".encode(), sha256)
    event = verify_stripe_signature(
        payload=payload,
        signature_header=f"t={timestamp},v1={signature.hexdigest()}",
        webhook_secret=secret,
    )

    assert event["type"] == "ping"


def test_verify_stripe_signature_rejects_bad_signature() -> None:
    with pytest.raises(HTTPException) as exc:
        verify_stripe_signature(
            payload=b'{"type":"ping"}',
            signature_header=f"t={int(time.time())},v1=bad",
            webhook_secret="whsec_test",
        )

    assert exc.value.status_code == 400
