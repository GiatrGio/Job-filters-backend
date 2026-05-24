from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.main import create_app
from app.routers.admin import get_admin_service
from app.schemas.user import CurrentUser
from app.services.admin import AdminService
from app.services.llm_calls import estimate_cost_usd_micros
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


@dataclass
class FakeStripeSubscriptionGateway:
    subscriptions_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    subscriptions_by_customer: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        return self.subscriptions_by_id.get(subscription_id)

    def list_customer_subscriptions(self, customer_id: str) -> list[dict[str, Any]]:
        return self.subscriptions_by_customer.get(customer_id, [])


def test_list_users_merges_auth_users_with_profiles(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": "u-pro",
                "plan": "pro",
                "monthly_eval_limit": 5000,
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
            },
            {
                "user_id": "u-free",
                "year_month": "1999-01",
                "evaluations_used": 99,
            },
        ],
    )
    db.store.seed(
        "applications",
        [
            {"id": "app-1", "user_id": "u-pro"},
            {"id": "app-2", "user_id": "u-pro"},
            {"id": "app-3", "user_id": "u-free"},
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
    assert users["u-free"]["tracked_jobs_count"] == 1
    assert users["u-free"]["tracked_jobs_limit"] == settings.free_tracked_jobs_limit
    assert users["u-pro"]["plan"] == "pro"
    assert users["u-pro"]["evaluations_used"] == 400
    assert users["u-pro"]["tracked_jobs_count"] == 2
    assert users["u-pro"]["tracked_jobs_limit"] == settings.pro_tracked_jobs_limit
    assert users["u-pro"]["last_sign_in_at"] == "2026-01-03T00:00:00Z"


def test_llm_pricing_uses_default_catalog(settings) -> None:
    svc = AdminService(FakeDB(), settings, FakeAuthAdminGateway([]))

    pricing = svc.get_llm_pricing()

    anthropic = next(
        model
        for model in pricing["models"]
        if model["provider"] == "anthropic" and model["model"] == settings.anthropic_model
    )
    assert pricing["active_provider"] == settings.llm_provider
    assert anthropic["input_cost_usd_per_million"] == 1.0
    assert anthropic["output_cost_usd_per_million"] == 5.0
    assert anthropic["source"] == "default"


def test_llm_cost_estimate_uses_model_rates(settings) -> None:
    cost = estimate_cost_usd_micros(
        settings=settings,
        provider_name="openai",
        model="gpt-4o-mini",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert cost == 750_000


def test_update_plan_sets_limits(settings) -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": "u-free", "plan": "free"}])
    gateway = FakeAuthAdminGateway([{"id": "u-free", "email": "user@example.com"}])
    svc = AdminService(db, settings, gateway)

    upgraded = svc.update_plan("u-free", "pro")

    assert upgraded["plan"] == "pro"
    assert upgraded["monthly_eval_limit"] == settings.pro_monthly_eval_limit
    assert upgraded["tracked_jobs_limit"] == settings.pro_tracked_jobs_limit
    assert db.store.tables["profiles"][0]["plan"] == "pro"


def test_refresh_users_syncs_latest_stripe_subscription_status(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "profiles",
        [
            {
                "id": "u-stale",
                "plan": "free",
                "monthly_eval_limit": settings.free_tier_monthly_limit,
                "stripe_customer_id": "cus_test",
                "stripe_subscription_id": "sub_test",
            }
        ],
    )
    gateway = FakeAuthAdminGateway([{"id": "u-stale", "email": "stale@example.com"}])
    stripe = FakeStripeSubscriptionGateway(
        subscriptions_by_id={
            "sub_test": {
                "id": "sub_test",
                "customer": "cus_test",
                "status": "active",
                "current_period_end": 1_800_000_000,
                "cancel_at_period_end": False,
                "items": {"data": [{"price": {"id": "price_pro"}}]},
            }
        }
    )
    svc = AdminService(db, settings, gateway, stripe_subscriptions=stripe)

    users = {user["id"]: user for user in svc.refresh_users()}

    assert users["u-stale"]["plan"] == "pro"
    assert users["u-stale"]["monthly_eval_limit"] == settings.pro_monthly_eval_limit
    profile = db.store.tables["profiles"][0]
    assert profile["plan"] == "pro"
    assert profile["monthly_eval_limit"] == settings.pro_monthly_eval_limit
    assert profile["stripe_subscription_status"] == "active"
    assert db.store.tables["subscriptions"][0]["status"] == "active"


def test_delete_user_calls_auth_admin_gateway(settings) -> None:
    gateway = FakeAuthAdminGateway([{"id": "u-delete"}])
    svc = AdminService(FakeDB(), settings, gateway)

    svc.delete_user("u-delete")

    assert gateway.deleted_user_ids == ["u-delete"]


def test_list_llm_calls_filters_by_range_and_merges_user_email(settings) -> None:
    db = FakeDB()
    recent = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    db.store.seed(
        "llm_calls",
        [
            {
                "id": "recent-call",
                "user_id": "u-one",
                "call_type": "job_evaluation",
                "provider": "fake",
                "model": "fake-model",
                "status": "success",
                "summary": "Backend at Acme",
                "prompt": {"messages": []},
                "response": {"results": []},
                "tokens_input": 100,
                "tokens_output": 25,
                "cost_usd_micros": 123,
                "duration_ms": 250,
                "created_at": recent,
            },
            {
                "id": "old-call",
                "user_id": "u-one",
                "call_type": "filter_validation",
                "provider": "fake",
                "model": "fake-model",
                "status": "success",
                "prompt": {"messages": []},
                "tokens_input": 1,
                "tokens_output": 1,
                "created_at": old,
            },
        ],
    )
    gateway = FakeAuthAdminGateway([{"id": "u-one", "email": "one@example.com"}])
    svc = AdminService(db, settings, gateway)

    calls = svc.list_llm_calls("1h")

    assert len(calls) == 1
    assert calls[0]["id"] == "recent-call"
    assert calls[0]["user_email"] == "one@example.com"
    assert calls[0]["tokens_input"] == 100
    assert calls[0]["cost_usd_micros"] == 123


def test_get_llm_call_includes_prompt_and_response(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "llm_calls",
        [
            {
                "id": "call-detail",
                "user_id": "u-one",
                "call_type": "filter_validation",
                "provider": "fake",
                "model": "fake-model",
                "status": "success",
                "prompt": {"messages": [{"role": "user", "content": "hello"}]},
                "response": {"verdict": "good"},
                "tokens_input": 10,
                "tokens_output": 5,
                "created_at": datetime.now(UTC).isoformat(),
            }
        ],
    )
    svc = AdminService(
        db,
        settings,
        FakeAuthAdminGateway([{"id": "u-one", "email": "one@example.com"}]),
    )

    call = svc.get_llm_call("call-detail")

    assert call is not None
    assert call["prompt"]["messages"][0]["content"] == "hello"
    assert call["response"]["verdict"] == "good"


def test_delete_llm_calls_older_than_range(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "llm_calls",
        [
            {
                "id": "recent-call",
                "call_type": "job_evaluation",
                "provider": "fake",
                "model": "fake-model",
                "status": "success",
                "prompt": {},
                "tokens_input": 1,
                "tokens_output": 1,
                "created_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
            },
            {
                "id": "old-call",
                "call_type": "job_evaluation",
                "provider": "fake",
                "model": "fake-model",
                "status": "success",
                "prompt": {},
                "tokens_input": 1,
                "tokens_output": 1,
                "created_at": (datetime.now(UTC) - timedelta(days=40)).isoformat(),
            },
        ],
    )
    svc = AdminService(db, settings, FakeAuthAdminGateway([]))

    deleted = svc.delete_llm_calls_older_than("30d")

    assert deleted == 1
    assert [row["id"] for row in db.store.tables["llm_calls"]] == ["recent-call"]


@dataclass
class FakeAdminService:
    deleted_user_ids: list[str] = field(default_factory=list)
    deleted_llm_call_ids: list[str] = field(default_factory=list)

    def list_users(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "u-one",
                "email": "one@example.com",
                "plan": "free",
                "evaluations_used": 12,
                "monthly_eval_limit": 50,
                "tracked_jobs_count": 3,
                "tracked_jobs_limit": 5,
                "usage_period": current_period(),
            }
        ]

    def refresh_users(self) -> list[dict[str, Any]]:
        return self.list_users()

    def update_plan(self, user_id: str, plan: str) -> dict[str, Any]:
        return {
            "id": user_id,
            "email": "one@example.com",
            "plan": plan,
            "evaluations_used": 12,
            "monthly_eval_limit": 5000 if plan == "pro" else 50,
            "tracked_jobs_count": 3,
            "tracked_jobs_limit": 1000 if plan == "pro" else 5,
            "usage_period": current_period(),
        }

    def delete_user(self, user_id: str) -> None:
        self.deleted_user_ids.append(user_id)

    def list_llm_calls(self, range_key: str) -> list[dict[str, Any]]:
        return [
            {
                "id": f"call-{range_key}",
                "user_id": "u-one",
                "user_email": "one@example.com",
                "call_type": "job_evaluation",
                "provider": "fake",
                "model": "fake-model",
                "status": "success",
                "summary": "Backend at Acme",
                "tokens_input": 100,
                "tokens_output": 25,
                "cost_usd_micros": 123,
                "duration_ms": 250,
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]

    def get_llm_call(self, call_id: str) -> dict[str, Any] | None:
        return {
            "id": call_id,
            "user_id": "u-one",
            "user_email": "one@example.com",
            "call_type": "job_evaluation",
            "provider": "fake",
            "model": "fake-model",
            "status": "success",
            "summary": "Backend at Acme",
            "tokens_input": 100,
            "tokens_output": 25,
            "cost_usd_micros": 123,
            "duration_ms": 250,
            "created_at": datetime.now(UTC).isoformat(),
            "prompt": {"messages": [{"role": "user", "content": "prompt"}]},
            "response": {"results": []},
            "error": None,
        }

    def delete_llm_call(self, call_id: str) -> bool:
        self.deleted_llm_call_ids.append(call_id)
        return True

    def delete_llm_calls_older_than(self, range_key: str) -> int:
        return 2

    def get_llm_pricing(self) -> dict[str, Any]:
        return {
            "active_provider": "anthropic",
            "active_model": "claude-haiku-4-5",
            "fetched_at": datetime.now(UTC).isoformat(),
            "models": [
                {
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5",
                    "input_cost_usd_per_million": 1.0,
                    "output_cost_usd_per_million": 5.0,
                    "source": "default",
                }
            ],
        }


def make_admin_client(
    settings: Settings,
    *,
    email: str = "admin@example.com",
    client: tuple[str, int] | None = None,
) -> tuple[TestClient, FakeAdminService]:
    fake_service = FakeAdminService()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=ADMIN_ID,
        email=email,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_admin_service] = lambda: fake_service
    if client is None:
        return TestClient(app), fake_service
    return TestClient(app, client=client), fake_service


@pytest.fixture
def admin_client(settings: Settings) -> tuple[TestClient, FakeAdminService]:
    return make_admin_client(settings)


def test_admin_router_lists_users(admin_client: tuple[TestClient, FakeAdminService]) -> None:
    client, _service = admin_client

    resp = client.get("/admin/users")

    assert resp.status_code == 200
    assert resp.json()[0]["email"] == "one@example.com"
    assert resp.json()[0]["evaluations_used"] == 12
    assert resp.json()[0]["tracked_jobs_count"] == 3
    assert resp.json()[0]["tracked_jobs_limit"] == 5


def test_admin_router_refreshes_users(admin_client: tuple[TestClient, FakeAdminService]) -> None:
    client, _service = admin_client

    resp = client.post("/admin/users/refresh")

    assert resp.status_code == 200
    assert resp.json()[0]["email"] == "one@example.com"


def test_admin_router_allows_configured_admin_email_from_remote(settings: Settings) -> None:
    settings.admin_emails = "admin@example.com"
    client, _service = make_admin_client(settings, client=("203.0.113.10", 50000))

    resp = client.get("/admin/users")

    assert resp.status_code == 200


def test_admin_router_hides_non_admin_email_from_remote(settings: Settings) -> None:
    settings.admin_emails = "owner@example.com"
    client, _service = make_admin_client(
        settings,
        email="other@example.com",
        client=("203.0.113.10", 50000),
    )

    resp = client.get("/admin/users")

    assert resp.status_code == 404


def test_admin_router_updates_plan(admin_client: tuple[TestClient, FakeAdminService]) -> None:
    client, _service = admin_client

    resp = client.patch("/admin/users/u-one", json={"plan": "pro"})

    assert resp.status_code == 200
    assert resp.json()["plan"] == "pro"
    assert resp.json()["monthly_eval_limit"] == 5000
    assert resp.json()["tracked_jobs_limit"] == 1000


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


def test_admin_router_lists_llm_calls(
    admin_client: tuple[TestClient, FakeAdminService],
) -> None:
    client, _service = admin_client

    resp = client.get("/admin/llm-calls?range=7d")

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "call-7d"
    assert "user_id" not in resp.json()[0]
    assert resp.json()[0]["tokens_input"] == 100


def test_admin_router_gets_llm_pricing(
    admin_client: tuple[TestClient, FakeAdminService],
) -> None:
    client, _service = admin_client

    resp = client.get("/admin/llm-pricing")

    assert resp.status_code == 200
    assert resp.json()["active_model"] == "claude-haiku-4-5"
    assert resp.json()["models"][0]["input_cost_usd_per_million"] == 1.0


def test_admin_router_gets_llm_call_detail(
    admin_client: tuple[TestClient, FakeAdminService],
) -> None:
    client, _service = admin_client

    resp = client.get("/admin/llm-calls/call-one")

    assert resp.status_code == 200
    assert resp.json()["prompt"]["messages"][0]["content"] == "prompt"


def test_admin_router_deletes_llm_call(
    admin_client: tuple[TestClient, FakeAdminService],
) -> None:
    client, service = admin_client

    resp = client.delete("/admin/llm-calls/call-one")

    assert resp.status_code == 204
    assert service.deleted_llm_call_ids == ["call-one"]


def test_admin_router_purges_old_llm_calls(
    admin_client: tuple[TestClient, FakeAdminService],
) -> None:
    client, _service = admin_client

    resp = client.delete("/admin/llm-calls?older_than=30d")

    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 2
