from __future__ import annotations

import pytest

from app.schemas.contact import ApplicationContactCreate, ApplicationContactUpdate
from app.services.contacts import ContactsService
from tests.fakes.fake_db import FakeDB

USER = "user-1"
OTHER = "user-2"
APP = "app-1"
OTHER_APP = "app-2"


def _svc() -> tuple[ContactsService, FakeDB]:
    db = FakeDB()
    return ContactsService(db), db


def _create(**overrides) -> ApplicationContactCreate:
    base = {
        "name": "Jane Recruiter",
        "role": "Senior Recruiter",
        "email": "jane@acme.test",
        "linkedin_url": "https://www.linkedin.com/in/jane",
        "notes": "Found me via the careers page.",
    }
    base.update(overrides)
    return ApplicationContactCreate(**base)


def test_create_persists_user_and_application_ids() -> None:
    svc, db = _svc()
    row = svc.create(USER, APP, _create())
    assert row["user_id"] == USER
    assert row["application_id"] == APP
    assert row["name"] == "Jane Recruiter"
    assert len(db.store.tables["application_contacts"]) == 1


def test_list_scopes_to_user_and_application() -> None:
    svc, _db = _svc()
    svc.create(USER, APP, _create(name="A"))
    svc.create(USER, APP, _create(name="B"))
    svc.create(USER, OTHER_APP, _create(name="C"))
    svc.create(OTHER, APP, _create(name="D"))

    rows = svc.list_for_application(USER, APP)
    assert {r["name"] for r in rows} == {"A", "B"}


def test_update_only_works_for_owner() -> None:
    svc, _db = _svc()
    row = svc.create(USER, APP, _create())

    updated = svc.update(USER, row["id"], ApplicationContactUpdate(role="Hiring Manager"))
    assert updated is not None
    assert updated["role"] == "Hiring Manager"

    spoofed = svc.update(OTHER, row["id"], ApplicationContactUpdate(role="haxxor"))
    assert spoofed is None


def test_update_with_no_fields_returns_existing() -> None:
    svc, _db = _svc()
    row = svc.create(USER, APP, _create())
    out = svc.update(USER, row["id"], ApplicationContactUpdate())
    assert out is not None
    assert out["id"] == row["id"]


def test_delete_only_removes_owners_row() -> None:
    svc, db = _svc()
    row = svc.create(USER, APP, _create())

    assert svc.delete(OTHER, row["id"]) is False
    assert len(db.store.tables["application_contacts"]) == 1

    assert svc.delete(USER, row["id"]) is True
    assert db.store.tables["application_contacts"] == []


def test_create_rejects_blank_name() -> None:
    with pytest.raises(Exception):
        _create(name="")
