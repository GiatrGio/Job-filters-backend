from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.db.client import get_db
from app.main import create_app
from app.schemas.user import CurrentUser
from tests.fakes.fake_db import FakeDB

USER_ID = "user-1"
USER_EMAIL = "u@example.com"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fake_user() -> CurrentUser:
    return CurrentUser(id=USER_ID, email=USER_EMAIL)


@pytest.fixture
def db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def client(db: FakeDB) -> TestClient:
    app = create_app()
    # Cast through SupabaseDB so the type annotation matches; FakeDB exposes
    # the same .table()/.rpc() surface used by routers and services.
    app.dependency_overrides[get_db] = lambda: db  # type: ignore[assignment]
    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def _seed_profile(db: FakeDB, *, pid: str, name: str, position: int, is_active: bool) -> None:
    now = _now_iso()
    db.store.seed(
        "filter_profiles",
        [
            {
                "id": pid,
                "user_id": USER_ID,
                "name": name,
                "position": position,
                "is_active": is_active,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def _seed_filter(db: FakeDB, *, fid: str, profile_id: str, text: str, position: int) -> None:
    now = _now_iso()
    db.store.seed(
        "filters",
        [
            {
                "id": fid,
                "user_id": USER_ID,
                "profile_id": profile_id,
                "text": text,
                "position": position,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


# ---------------------------------------------------------------------------
# /profiles CRUD
# ---------------------------------------------------------------------------

def test_list_profiles_returns_filters_embedded(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="Backend", position=0, is_active=True)
    _seed_filter(db, fid="f1", profile_id="p1", text="remote", position=0)

    resp = client.get("/profiles")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Backend"
    assert body[0]["is_active"] is True
    assert len(body[0]["filters"]) == 1
    assert body[0]["filters"][0]["text"] == "remote"


def test_create_profile_first_one_is_auto_active(client: TestClient, db: FakeDB) -> None:
    resp = client.post("/profiles", json={"name": "First"})
    assert resp.status_code == 201
    assert resp.json()["is_active"] is True


def test_create_profile_subsequent_are_inactive(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="Backend", position=0, is_active=True)
    resp = client.post("/profiles", json={"name": "Frontend"})
    assert resp.status_code == 201
    assert resp.json()["is_active"] is False
    assert resp.json()["position"] == 1


def test_profile_creation_caps_at_5(client: TestClient, db: FakeDB) -> None:
    for i in range(5):
        _seed_profile(db, pid=f"p{i}", name=f"P{i}", position=i, is_active=(i == 0))

    resp = client.post("/profiles", json={"name": "Sixth"})
    assert resp.status_code == 409
    assert "limit" in resp.json()["detail"]


def test_profile_name_max_50_chars(client: TestClient) -> None:
    resp = client.post("/profiles", json={"name": "x" * 51})
    assert resp.status_code == 422  # pydantic validation


def test_activate_profile_swaps_is_active(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="Backend", position=0, is_active=True)
    _seed_profile(db, pid="p2", name="Frontend", position=1, is_active=False)

    resp = client.post("/profiles/p2/activate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    rows = {r["id"]: r["is_active"] for r in db.store.tables["filter_profiles"]}
    assert rows == {"p1": False, "p2": True}


def test_delete_last_profile_blocked(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="Only", position=0, is_active=True)
    resp = client.delete("/profiles/p1")
    assert resp.status_code == 409


def test_delete_active_profile_promotes_next(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="A", position=0, is_active=True)
    _seed_profile(db, pid="p2", name="B", position=1, is_active=False)

    resp = client.delete("/profiles/p1")
    assert resp.status_code == 204

    remaining = db.store.tables["filter_profiles"]
    assert len(remaining) == 1
    assert remaining[0]["id"] == "p2"
    assert remaining[0]["is_active"] is True


def test_reorder_profiles(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="a", name="A", position=0, is_active=True)
    _seed_profile(db, pid="b", name="B", position=1, is_active=False)
    _seed_profile(db, pid="c", name="C", position=2, is_active=False)

    resp = client.patch("/profiles/reorder", json={"ids": ["c", "a", "b"]})
    assert resp.status_code == 200
    positions = {r["id"]: r["position"] for r in db.store.tables["filter_profiles"]}
    assert positions == {"c": 0, "a": 1, "b": 2}


def test_reorder_rejects_mismatched_set(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="a", name="A", position=0, is_active=True)
    resp = client.patch("/profiles/reorder", json={"ids": ["a", "b"]})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /profiles/{id}/filters CRUD
# ---------------------------------------------------------------------------

def test_create_filter_under_profile(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="P", position=0, is_active=True)
    resp = client.post("/profiles/p1/filters", json={"text": "remote"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["text"] == "remote"
    assert body["profile_id"] == "p1"
    assert body["position"] == 0
    # kind defaults to criterion when the client doesn't send one — keeps
    # older extension builds working unchanged.
    assert body["kind"] == "criterion"


def test_create_filter_accepts_kind(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="P", position=0, is_active=True)
    resp = client.post(
        "/profiles/p1/filters",
        json={"text": "What languages are required?", "kind": "question"},
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "question"


def test_update_filter_accepts_kind(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="P", position=0, is_active=True)
    _seed_filter(db, fid="f1", profile_id="p1", text="remote", position=0)

    resp = client.patch("/filters/f1", json={"kind": "question"})
    assert resp.status_code == 200
    assert resp.json()["kind"] == "question"


def test_filter_creation_caps_at_10(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="P", position=0, is_active=True)
    for i in range(10):
        _seed_filter(db, fid=f"f{i}", profile_id="p1", text=f"f{i}", position=i)

    resp = client.post("/profiles/p1/filters", json={"text": "eleventh"})
    assert resp.status_code == 409


def test_filter_text_max_200_chars(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="P", position=0, is_active=True)
    resp = client.post("/profiles/p1/filters", json={"text": "x" * 201})
    assert resp.status_code == 422


def test_reorder_profile_filters(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="P", position=0, is_active=True)
    _seed_filter(db, fid="a", profile_id="p1", text="a", position=0)
    _seed_filter(db, fid="b", profile_id="p1", text="b", position=1)

    resp = client.patch(
        "/profiles/p1/filters/reorder", json={"ids": ["b", "a"]}
    )
    assert resp.status_code == 200
    positions = {r["id"]: r["position"] for r in db.store.tables["filters"]}
    assert positions == {"b": 0, "a": 1}


def test_filter_update_and_delete(client: TestClient, db: FakeDB) -> None:
    _seed_profile(db, pid="p1", name="P", position=0, is_active=True)
    _seed_filter(db, fid="f1", profile_id="p1", text="old", position=0)

    upd = client.patch("/filters/f1", json={"text": "new"})
    assert upd.status_code == 200
    assert upd.json()["text"] == "new"

    delete = client.delete("/filters/f1")
    assert delete.status_code == 204
    assert db.store.tables["filters"] == []
