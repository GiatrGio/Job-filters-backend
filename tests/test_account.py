from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import create_app
from app.routers.me import get_account_service
from app.schemas.user import CurrentUser
from app.services.account import AccountService
from tests.fakes.fake_db import FakeDB

USER = "user-to-delete"


@dataclass
class FakeAuthAdminGateway:
    deleted_user_ids: list[str] = field(default_factory=list)

    def delete_user(self, user_id: str) -> None:
        self.deleted_user_ids.append(user_id)


@dataclass
class FakeBillingGateway:
    cancelled: list[str] = field(default_factory=list)
    deleted_customers: list[str] = field(default_factory=list)
    cancel_error: Exception | None = None
    delete_customer_error: Exception | None = None

    def cancel_subscription(self, subscription_id: str) -> None:
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancelled.append(subscription_id)

    def delete_customer(self, customer_id: str) -> None:
        if self.delete_customer_error is not None:
            raise self.delete_customer_error
        self.deleted_customers.append(customer_id)


def _service(
    db: FakeDB | None = None,
    billing: FakeBillingGateway | None = None,
) -> tuple[AccountService, FakeDB, FakeAuthAdminGateway, FakeBillingGateway | None]:
    fake_db = db or FakeDB()
    auth_admin = FakeAuthAdminGateway()
    svc = AccountService(db=fake_db, auth_admin=auth_admin, billing=billing)
    return svc, fake_db, auth_admin, billing


def test_deletes_auth_user_when_stripe_is_not_configured() -> None:
    svc, _db, auth_admin, _billing = _service()

    svc.delete_account(USER)

    # Deleting the auth row is what cascades every user-owned table.
    assert auth_admin.deleted_user_ids == [USER]


def test_cancels_active_subscription_then_deletes_customer_and_user() -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": USER,
                "stripe_customer_id": "cus_1",
                "stripe_subscription_id": "sub_1",
                "stripe_subscription_status": "active",
            }
        ],
    )
    svc, _db, auth_admin, billing = _service(db, FakeBillingGateway())

    svc.delete_account(USER)

    assert billing is not None
    assert billing.cancelled == ["sub_1"]
    assert billing.deleted_customers == ["cus_1"]
    assert auth_admin.deleted_user_ids == [USER]


def test_leaves_inactive_subscription_alone_so_retries_are_safe() -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": USER,
                "stripe_customer_id": "cus_1",
                "stripe_subscription_id": "sub_done",
                "stripe_subscription_status": "canceled",
            }
        ],
    )
    svc, _db, auth_admin, billing = _service(db, FakeBillingGateway())

    svc.delete_account(USER)

    assert billing is not None
    assert billing.cancelled == []
    assert auth_admin.deleted_user_ids == [USER]


def test_cancels_a_stale_subscription_row_the_profile_no_longer_points_at() -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "stripe_customer_id": "cus_1"}])
    db.store.seed(
        "subscriptions",
        [
            {"user_id": USER, "stripe_subscription_id": "sub_old", "status": "trialing"},
            {"user_id": USER, "stripe_subscription_id": "sub_dead", "status": "canceled"},
            {"user_id": "someone-else", "stripe_subscription_id": "sub_other", "status": "active"},
        ],
    )
    svc, _db, _auth_admin, billing = _service(db, FakeBillingGateway())

    svc.delete_account(USER)

    assert billing is not None
    assert billing.cancelled == ["sub_old"]


def test_does_not_cancel_the_same_subscription_twice() -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": USER,
                "stripe_subscription_id": "sub_1",
                "stripe_subscription_status": "active",
            }
        ],
    )
    db.store.seed(
        "subscriptions",
        [{"user_id": USER, "stripe_subscription_id": "sub_1", "status": "active"}],
    )
    svc, _db, _auth_admin, billing = _service(db, FakeBillingGateway())

    svc.delete_account(USER)

    assert billing is not None
    assert billing.cancelled == ["sub_1"]


def test_aborts_without_deleting_when_cancellation_fails() -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": USER,
                "stripe_customer_id": "cus_1",
                "stripe_subscription_id": "sub_1",
                "stripe_subscription_status": "active",
            }
        ],
    )
    billing = FakeBillingGateway(cancel_error=HTTPException(status_code=502, detail="stripe down"))
    svc, _db, auth_admin, _billing = _service(db, billing)

    with pytest.raises(HTTPException):
        svc.delete_account(USER)

    # The account must survive, or we'd keep billing someone who can no longer
    # reach the billing portal.
    assert auth_admin.deleted_user_ids == []
    assert billing.deleted_customers == []


def test_still_deletes_the_account_when_customer_removal_fails() -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "stripe_customer_id": "cus_1"}])
    billing = FakeBillingGateway(delete_customer_error=RuntimeError("stripe down"))
    svc, _db, auth_admin, _billing = _service(db, billing)

    svc.delete_account(USER)

    assert auth_admin.deleted_user_ids == [USER]


def test_delete_me_endpoint_deletes_the_caller_only() -> None:
    recorded: list[str] = []

    class RecordingService:
        def delete_account(self, user_id: str) -> None:
            recorded.append(user_id)

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=USER, email="bye@example.com"
    )
    app.dependency_overrides[get_account_service] = lambda: RecordingService()

    with TestClient(app) as client:
        response = client.delete("/me")

    assert response.status_code == 204
    # Comes from the verified token, never from client input.
    assert recorded == [USER]


def test_delete_me_requires_authentication() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.delete("/me")

    assert response.status_code in (401, 403)
