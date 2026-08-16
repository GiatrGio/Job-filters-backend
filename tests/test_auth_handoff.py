from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import get_current_user
from app.main import create_app
from app.routers.auth_handoff import get_auth_handoff_service
from app.schemas.auth_handoff import WebHandoffCreate
from app.schemas.user import CurrentUser
from app.services.auth_handoff import (
    AuthHandoffAccountMismatch,
    AuthHandoffInvalid,
    AuthHandoffService,
)
from tests.fakes.fake_db import FakeDB

USER = "00000000-0000-4000-8000-000000000001"
OTHER_USER = "00000000-0000-4000-8000-000000000002"
TICKET = "a" * 43
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


@dataclass
class FakeAuthGateway:
    token_hash: str = "supabase-email-token-hash"
    calls: list[str] = field(default_factory=list)

    def create_email_token_hash(self, user_id: str) -> str:
        self.calls.append(user_id)
        return self.token_hash


def _service(settings, *, now: datetime = NOW):
    settings.website_url = "https://www.canvasjob.com"
    settings.auth_handoff_ttl_seconds = 60
    db = FakeDB()
    gateway = FakeAuthGateway()
    service = AuthHandoffService(
        db,  # type: ignore[arg-type]
        settings,
        gateway,
        clock=lambda: now,
        ticket_factory=lambda: TICKET,
    )
    return service, db, gateway


def test_create_stores_only_hash_and_returns_short_lived_web_url(settings) -> None:
    service, db, _gateway = _service(settings)

    created = service.create(user_id=USER, destination="/app?view=board")

    assert created.url == f"https://www.canvasjob.com/auth/extension?ticket={TICKET}"
    assert created.expires_in == 60
    row = db.store.tables["auth_handoffs"][0]
    assert row["token_hash"] == hashlib.sha256(TICKET.encode()).hexdigest()
    assert TICKET not in row.values()
    assert row["expires_at"] == (NOW + timedelta(seconds=60)).isoformat()


def test_create_removes_abandoned_expired_tickets(settings) -> None:
    service, db, _gateway = _service(settings)
    db.store.seed(
        "auth_handoffs",
        [
            {
                "token_hash": "expired",
                "user_id": USER,
                "destination": "/app",
                "expires_at": (NOW - timedelta(seconds=1)).isoformat(),
            },
            {
                "token_hash": "live",
                "user_id": USER,
                "destination": "/app",
                "expires_at": (NOW + timedelta(seconds=1)).isoformat(),
            },
        ],
    )

    service.create(user_id=USER, destination="/app")

    hashes = {row["token_hash"] for row in db.store.tables["auth_handoffs"]}
    assert "expired" not in hashes
    assert "live" in hashes


def test_anonymous_exchange_mints_independent_website_session(settings) -> None:
    service, db, gateway = _service(settings)
    service.create(user_id=USER, destination="/app?view=board")

    exchanged = service.exchange(ticket=TICKET, website_user_id=None)

    assert exchanged.user_id == USER
    assert exchanged.destination == "/app?view=board"
    assert exchanged.token_hash == gateway.token_hash
    assert gateway.calls == [USER]
    assert db.store.tables["auth_handoffs"] == []


def test_matching_website_session_does_not_mint_another_session(settings) -> None:
    service, _db, gateway = _service(settings)
    service.create(user_id=USER, destination="/app")

    exchanged = service.exchange(ticket=TICKET, website_user_id=USER)

    assert exchanged.token_hash is None
    assert gateway.calls == []


def test_mismatched_website_account_does_not_consume_ticket(settings) -> None:
    service, db, gateway = _service(settings)
    service.create(user_id=USER, destination="/app")

    with pytest.raises(AuthHandoffAccountMismatch):
        service.exchange(ticket=TICKET, website_user_id=OTHER_USER)

    assert len(db.store.tables["auth_handoffs"]) == 1
    assert gateway.calls == []

    # The user can explicitly choose the extension account and retry without
    # presenting the mismatched website bearer token.
    exchanged = service.exchange(ticket=TICKET, website_user_id=None)
    assert exchanged.user_id == USER


def test_ticket_is_single_use(settings) -> None:
    service, _db, _gateway = _service(settings)
    service.create(user_id=USER, destination="/app")
    service.exchange(ticket=TICKET, website_user_id=None)

    with pytest.raises(AuthHandoffInvalid):
        service.exchange(ticket=TICKET, website_user_id=None)


def test_expired_ticket_is_rejected(settings) -> None:
    service, _db, _gateway = _service(settings)
    service.create(user_id=USER, destination="/app")
    service._clock = lambda: NOW + timedelta(seconds=61)  # noqa: SLF001

    with pytest.raises(AuthHandoffInvalid):
        service.exchange(ticket=TICKET, website_user_id=None)


@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/%5Cevil.example",
        "/%2F%2Fevil.example",
        "/%252F%252Fevil.example",
        "/app%0D%0AX-Test:true",
    ],
)
def test_external_destinations_are_rejected(destination: str) -> None:
    with pytest.raises(ValidationError):
        WebHandoffCreate(destination=destination)


def test_router_requires_authentication_and_disables_caching(settings) -> None:
    service, _db, _gateway = _service(settings)
    app = create_app()
    app.dependency_overrides[get_auth_handoff_service] = lambda: service

    with TestClient(app) as client:
        unauthorized = client.post(
            "/auth/web-handoffs",
            json={"destination": "/app"},
        )
        assert unauthorized.status_code == 401

        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=USER,
            email="user@example.com",
        )
        created = client.post(
            "/auth/web-handoffs",
            json={"destination": "/app?view=board"},
        )
        exchanged = client.post(
            "/auth/web-handoffs/exchange",
            json={"ticket": TICKET},
        )

    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    assert created.json() == {
        "url": f"https://www.canvasjob.com/auth/extension?ticket={TICKET}",
        "expires_in": 60,
    }
    assert exchanged.status_code == 200
    assert exchanged.headers["cache-control"] == "no-store"
    assert exchanged.json() == {
        "user_id": USER,
        "destination": "/app?view=board",
        "token_hash": "supabase-email-token-hash",
    }
