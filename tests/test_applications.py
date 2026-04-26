from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.application import ApplicationCreate, ApplicationUpdate
from app.services.applications import ApplicationsService
from tests.fakes.fake_db import FakeDB

USER = "user-1"
OTHER = "user-2"


def _svc() -> tuple[ApplicationsService, FakeDB]:
    db = FakeDB()
    return ApplicationsService(db), db


def _make_create(**overrides) -> ApplicationCreate:
    base = {
        "source": "linkedin",
        "external_id": "3891234567",
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "location": "Remote, EU",
        "url": "https://www.linkedin.com/jobs/view/3891234567",
        "description": "We are hiring …",
    }
    base.update(overrides)
    return ApplicationCreate(**base)


def test_create_inserts_new_row() -> None:
    svc, db = _svc()
    row, created = svc.create_or_get(USER, _make_create())
    assert created is True
    assert row["user_id"] == USER
    assert row["source"] == "linkedin"
    assert row["external_id"] == "3891234567"
    assert row["status"] == "saved"
    assert len(db.store.tables["applications"]) == 1


def test_create_is_idempotent_on_source_external_id() -> None:
    """Re-tracking the same job is a no-op — the extension can fire-and-forget
    without first checking whether the row exists. The second call returns the
    existing row with `created=False` so the router can map it to 200, not 201."""
    svc, db = _svc()
    first, created_first = svc.create_or_get(USER, _make_create())
    second, created_second = svc.create_or_get(USER, _make_create(title="Different title"))

    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]
    # Title is NOT updated on re-track. We don't want a stale scrape from a
    # second extension click to overwrite a title the user manually edited.
    assert second["title"] == "Senior Backend Engineer"
    assert len(db.store.tables["applications"]) == 1


def test_same_external_id_different_users_are_distinct() -> None:
    svc, _db = _svc()
    a, _ = svc.create_or_get(USER, _make_create())
    b, _ = svc.create_or_get(OTHER, _make_create())
    assert a["id"] != b["id"]
    assert svc.get_by_job(USER, "linkedin", "3891234567")["id"] == a["id"]
    assert svc.get_by_job(OTHER, "linkedin", "3891234567")["id"] == b["id"]


def test_list_returns_only_callers_rows() -> None:
    svc, _db = _svc()
    svc.create_or_get(USER, _make_create(external_id="a"))
    svc.create_or_get(USER, _make_create(external_id="b"))
    svc.create_or_get(OTHER, _make_create(external_id="c"))

    rows = svc.list_for_user(USER)
    assert {r["external_id"] for r in rows} == {"a", "b"}


def test_update_changes_fields_and_scopes_to_owner() -> None:
    svc, _db = _svc()
    row, _ = svc.create_or_get(USER, _make_create())
    applied_at = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)

    updated = svc.update(
        USER,
        row["id"],
        ApplicationUpdate(status="applied", applied_at=applied_at, notes="referred by friend"),
    )
    assert updated is not None
    assert updated["status"] == "applied"
    assert updated["notes"] == "referred by friend"

    # The other user can't update it.
    spoofed = svc.update(OTHER, row["id"], ApplicationUpdate(status="rejected"))
    assert spoofed is None


def test_update_with_no_fields_returns_existing_row() -> None:
    svc, _db = _svc()
    row, _ = svc.create_or_get(USER, _make_create())
    out = svc.update(USER, row["id"], ApplicationUpdate())
    assert out is not None
    assert out["id"] == row["id"]


def test_delete_only_removes_owners_row() -> None:
    svc, db = _svc()
    row, _ = svc.create_or_get(USER, _make_create())

    assert svc.delete(OTHER, row["id"]) is False
    assert len(db.store.tables["applications"]) == 1

    assert svc.delete(USER, row["id"]) is True
    assert db.store.tables["applications"] == []


def test_get_by_job_returns_none_when_not_tracked() -> None:
    svc, _db = _svc()
    assert svc.get_by_job(USER, "linkedin", "missing") is None


def test_create_rejects_invalid_status() -> None:
    """Status is a Literal; pydantic must reject anything outside the set."""
    with pytest.raises(Exception):
        _make_create(status="bogus")  # type: ignore[arg-type]
