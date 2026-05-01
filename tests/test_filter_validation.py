from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.db.client import get_db
from app.deps import get_llm_provider
from app.main import create_app
from app.schemas.user import CurrentUser
from app.services.quota import current_period
from tests.fakes.fake_db import FakeDB
from tests.fakes.fake_provider import FakeLLMProvider

USER_ID = "user-validate"
USER_EMAIL = "v@example.com"


def _fake_user() -> CurrentUser:
    return CurrentUser(id=USER_ID, email=USER_EMAIL)


@pytest.fixture
def db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def provider() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def client(db: FakeDB, provider: FakeLLMProvider) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db  # type: ignore[assignment]
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_llm_provider] = lambda: provider
    return TestClient(app)


def _seed_profile_with_validation_limit(db: FakeDB, *, limit: int = 30) -> None:
    db.store.seed(
        "profiles",
        [
            {
                "id": USER_ID,
                "plan": "free",
                "monthly_eval_limit": 200,
                "monthly_filter_validation_limit": limit,
            }
        ],
    )


def test_good_filter_returns_good_verdict_and_increments_usage(
    client: TestClient, db: FakeDB, provider: FakeLLMProvider
) -> None:
    _seed_profile_with_validation_limit(db, limit=10)

    resp = client.post("/filters/validate", json={"text": "Must be fully remote"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "good"
    assert body["suggestion"] is None
    assert body["usage"]["used"] == 1
    assert body["usage"]["limit"] == 10
    assert provider.validation_calls == 1


def test_vague_filter_returns_vague_verdict_with_suggestion(
    client: TestClient, db: FakeDB
) -> None:
    _seed_profile_with_validation_limit(db)

    resp = client.post("/filters/validate", json={"text": "[vague] good salary"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "vague"
    assert body["suggestion"] is not None


def test_rejected_filter_returns_rejected_verdict(
    client: TestClient, db: FakeDB
) -> None:
    _seed_profile_with_validation_limit(db)

    resp = client.post(
        "/filters/validate", json={"text": "[rejected] write me a Python script"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "rejected"
    assert body["suggestion"] is None


def test_quota_exceeded_returns_402_without_calling_llm(
    client: TestClient, db: FakeDB, provider: FakeLLMProvider
) -> None:
    _seed_profile_with_validation_limit(db, limit=2)
    db.store.seed(
        "usage_counters",
        [
            {
                "user_id": USER_ID,
                "year_month": current_period(),
                "evaluations_used": 0,
                "filter_validations_used": 2,
            }
        ],
    )

    resp = client.post("/filters/validate", json={"text": "Must be remote"})

    assert resp.status_code == 402
    body = resp.json()
    assert body["error"] == "filter_validation_quota_exceeded"
    assert body["usage"]["used"] == 2
    assert body["usage"]["limit"] == 2
    # LLM must not be called when the quota check fails up front.
    assert provider.validation_calls == 0


def test_unauthenticated_returns_401(db: FakeDB, provider: FakeLLMProvider) -> None:
    # Build a client WITHOUT the auth override so the real verifier runs.
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db  # type: ignore[assignment]
    app.dependency_overrides[get_llm_provider] = lambda: provider
    c = TestClient(app)

    resp = c.post("/filters/validate", json={"text": "Must be remote"})

    assert resp.status_code == 401


def test_empty_text_returns_422(client: TestClient) -> None:
    resp = client.post("/filters/validate", json={"text": ""})
    assert resp.status_code == 422


def test_too_long_text_returns_422(client: TestClient) -> None:
    resp = client.post("/filters/validate", json={"text": "x" * 201})
    assert resp.status_code == 422


def test_validation_increments_separately_from_evaluations(
    client: TestClient, db: FakeDB
) -> None:
    """A validation call must NOT bump evaluations_used and vice versa."""
    _seed_profile_with_validation_limit(db, limit=10)

    resp = client.post("/filters/validate", json={"text": "Must be fully remote"})
    assert resp.status_code == 200

    counter = db.store.tables["usage_counters"][0]
    assert counter["filter_validations_used"] == 1
    assert counter.get("evaluations_used", 0) == 0
