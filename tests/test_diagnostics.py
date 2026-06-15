from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import get_settings
from app.db.client import get_db
from app.deps import get_llm_provider
from app.main import create_app
from app.schemas.user import CurrentUser
from tests.fakes.fake_db import FakeDB
from tests.fakes.fake_provider import FakeLLMProvider

USER_ID = "user-diag"
USER_EMAIL = "d@example.com"

PARTIAL_TELEMETRY = {
    "extractor": "jobs-v1",
    "outcome": "partial",
    "job_id": "4267892341",
    "url": "https://www.linkedin.com/jobs/view/4267892341/",
    "doc_title": "Senior Backend Engineer | Acme Corp | LinkedIn",
    "missing": ["title", "company"],
    "fields": [
        {"name": "title", "found": False, "source": None},
        {"name": "company", "found": False, "source": None},
        {"name": "location", "found": False, "source": None},
        {"name": "description", "found": True, "source": "#job-details"},
    ],
    "job_html": '<main><h1 class="_abc123">Senior Backend Engineer</h1>'
    '<section id="job-details">About the job ...</section></main>',
    "user_agent": "Mozilla/5.0 (Macintosh)",
    "captured_at": "2026-06-12T10:00:00.000Z",
}


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


def test_dom_diagnostics_runs_analysis_and_logs_an_llm_call(
    client: TestClient, db: FakeDB, provider: FakeLLMProvider
) -> None:
    resp = client.post("/diagnostics/dom", json=PARTIAL_TELEMETRY)

    assert resp.status_code == 204
    assert provider.diagnostics_calls == 1

    rows = db.store.tables.get("llm_calls", [])
    assert len(rows) == 1
    row = rows[0]
    assert row["call_type"] == "dom_diagnostics"
    assert row["status"] == "success"
    assert row["external_id"] == "4267892341"
    assert row["source"] == "linkedin"
    assert "partial" in row["summary"]
    # The diagnostic analysis is stored so it's visible in /admin.
    assert row["response"]["recommended_fix"]
    # The sanitized HTML is forwarded to the model as a fenced html block (not a
    # giant escaped JSON string) so it can read selectors off the real markup.
    user_message = row["prompt"]["messages"][-1]["content"]
    assert "```html" in user_message
    assert "_abc123" in user_message
    # With HTML present the model returns concrete selector suggestions.
    assert row["response"]["suggested_selectors"]


def test_dom_diagnostics_does_not_touch_evaluation_quota(
    client: TestClient, db: FakeDB
) -> None:
    resp = client.post("/diagnostics/dom", json=PARTIAL_TELEMETRY)
    assert resp.status_code == 204
    # No usage_counters row created/incremented — diagnostics are free.
    assert db.store.tables.get("usage_counters", []) == []


def test_dom_diagnostics_daily_cap_drops_without_calling_llm(
    db: FakeDB, provider: FakeLLMProvider
) -> None:
    os.environ["DOM_DIAGNOSTICS_DAILY_CAP_PER_USER"] = "1"
    get_settings.cache_clear()
    try:
        # One existing diagnostic in the last 24h already hits the cap of 1.
        db.store.seed(
            "llm_calls",
            [
                {
                    "user_id": USER_ID,
                    "call_type": "dom_diagnostics",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
        )
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db  # type: ignore[assignment]
        app.dependency_overrides[get_current_user] = _fake_user
        app.dependency_overrides[get_llm_provider] = lambda: provider
        c = TestClient(app)

        resp = c.post("/diagnostics/dom", json=PARTIAL_TELEMETRY)

        assert resp.status_code == 204  # still 204 — best-effort, silent drop
        assert provider.diagnostics_calls == 0
        # No new row added beyond the seeded one.
        assert len(db.store.tables["llm_calls"]) == 1
    finally:
        os.environ.pop("DOM_DIAGNOSTICS_DAILY_CAP_PER_USER", None)
        get_settings.cache_clear()


def test_dom_diagnostics_unauthenticated_returns_401(
    db: FakeDB, provider: FakeLLMProvider
) -> None:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db  # type: ignore[assignment]
    app.dependency_overrides[get_llm_provider] = lambda: provider
    c = TestClient(app)

    resp = c.post("/diagnostics/dom", json=PARTIAL_TELEMETRY)

    assert resp.status_code == 401


def test_dom_diagnostics_rejects_malformed_payload(client: TestClient) -> None:
    # Missing required `extractor`/`outcome`/`job_id`.
    resp = client.post("/diagnostics/dom", json={"url": "https://x"})
    assert resp.status_code == 422
