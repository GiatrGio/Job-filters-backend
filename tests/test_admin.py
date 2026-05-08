from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import create_app
from app.routers.admin import get_admin_service
from app.schemas.user import CurrentUser
from app.services.admin import AdminService
from app.services.quota import current_period
from tests.fakes.fake_db import FakeDB

ADMIN_ID = "admin-user"


@dataclass
class FakeAuthAdminGateway:
    users: list[dict[str, Any]]
    deleted_user_ids: list[str] = field(default_factory=list)

    def list_users(self) -> list[dict[str, Any]]:
        return self.users

    def delete_user(self, user_id: str) -> None:
        self.deleted_user_ids.append(user_id)


def test_list_users_merges_auth_users_with_profiles(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": "u-pro",
                "plan": "pro",
                "monthly_eval_limit": 5000,
                "monthly_cv_tailoring_limit": 20,
            }
        ],
    )
    db.store.seed(
        "usage_counters",
        [
            {
                "user_id": "u-pro",
                "year_month": current_period(),
                "evaluations_used": 400,
                "cv_tailorings_used": 7,
            },
            {
                "user_id": "u-free",
                "year_month": "1999-01",
                "evaluations_used": 99,
                "cv_tailorings_used": 99,
            },
        ],
    )
    gateway = FakeAuthAdminGateway(
        [
            {
                "id": "u-free",
                "email": "free@example.com",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "u-pro",
                "email": "pro@example.com",
                "created_at": "2026-01-02T00:00:00Z",
                "last_sign_in_at": "2026-01-03T00:00:00Z",
            },
        ]
    )
    svc = AdminService(db, settings, gateway)

    users = {user["id"]: user for user in svc.list_users()}

    assert users["u-free"]["plan"] == "free"
    assert users["u-free"]["monthly_eval_limit"] == settings.free_tier_monthly_limit
    assert users["u-free"]["evaluations_used"] == 0
    assert users["u-pro"]["plan"] == "pro"
    assert users["u-pro"]["evaluations_used"] == 400
    assert users["u-pro"]["cv_tailorings_used"] == 7
    assert users["u-pro"]["monthly_cv_tailoring_limit"] == 20
    assert users["u-pro"]["last_sign_in_at"] == "2026-01-03T00:00:00Z"


def test_update_plan_sets_limits(settings) -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": "u-free", "plan": "free"}])
    gateway = FakeAuthAdminGateway([{"id": "u-free", "email": "user@example.com"}])
    svc = AdminService(db, settings, gateway)

    upgraded = svc.update_plan("u-free", "pro")

    assert upgraded["plan"] == "pro"
    assert upgraded["monthly_eval_limit"] == settings.pro_monthly_eval_limit
    assert upgraded["monthly_cv_tailoring_limit"] == settings.pro_monthly_cv_tailoring_limit
    assert db.store.tables["profiles"][0]["plan"] == "pro"


def test_delete_user_calls_auth_admin_gateway(settings) -> None:
    gateway = FakeAuthAdminGateway([{"id": "u-delete"}])
    svc = AdminService(FakeDB(), settings, gateway)

    svc.delete_user("u-delete")

    assert gateway.deleted_user_ids == ["u-delete"]


@dataclass
class FakeAdminService:
    deleted_user_ids: list[str] = field(default_factory=list)

    def list_users(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "u-one",
                "email": "one@example.com",
                "plan": "free",
                "evaluations_used": 12,
                "monthly_eval_limit": 200,
                "cv_tailorings_used": 0,
                "monthly_cv_tailoring_limit": 0,
                "usage_period": current_period(),
            }
        ]

    def update_plan(self, user_id: str, plan: str) -> dict[str, Any]:
        return {
            "id": user_id,
            "email": "one@example.com",
            "plan": plan,
            "evaluations_used": 12,
            "monthly_eval_limit": 5000 if plan == "pro" else 200,
            "cv_tailorings_used": 0,
            "monthly_cv_tailoring_limit": 20 if plan == "pro" else 0,
            "usage_period": current_period(),
        }

    def delete_user(self, user_id: str) -> None:
        self.deleted_user_ids.append(user_id)


@pytest.fixture
def admin_client() -> tuple[TestClient, FakeAdminService]:
    fake_service = FakeAdminService()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=ADMIN_ID,
        email="admin@example.com",
    )
    app.dependency_overrides[get_admin_service] = lambda: fake_service
    return TestClient(app), fake_service


def test_admin_router_lists_users(admin_client: tuple[TestClient, FakeAdminService]) -> None:
    client, _service = admin_client

    resp = client.get("/admin/users")

    assert resp.status_code == 200
    assert resp.json()[0]["email"] == "one@example.com"
    assert resp.json()[0]["evaluations_used"] == 12


def test_admin_router_updates_plan(admin_client: tuple[TestClient, FakeAdminService]) -> None:
    client, _service = admin_client

    resp = client.patch("/admin/users/u-one", json={"plan": "pro"})

    assert resp.status_code == 200
    assert resp.json()["plan"] == "pro"
    assert resp.json()["monthly_cv_tailoring_limit"] == 20


def test_admin_router_rejects_self_delete(
    admin_client: tuple[TestClient, FakeAdminService],
) -> None:
    client, service = admin_client

    resp = client.delete(f"/admin/users/{ADMIN_ID}")

    assert resp.status_code == 400
    assert service.deleted_user_ids == []


def test_admin_router_deletes_other_users(
    admin_client: tuple[TestClient, FakeAdminService],
) -> None:
    client, service = admin_client

    resp = client.delete("/admin/users/u-one")

    assert resp.status_code == 204
    assert service.deleted_user_ids == ["u-one"]
