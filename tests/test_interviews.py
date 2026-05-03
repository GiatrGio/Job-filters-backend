from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.interview import (
    ApplicationInterviewCreate,
    ApplicationInterviewUpdate,
)
from app.services.interviews import InterviewsService
from tests.fakes.fake_db import FakeDB

USER = "user-1"
OTHER = "user-2"
APP = "app-1"
OTHER_APP = "app-2"


def _svc() -> tuple[InterviewsService, FakeDB]:
    db = FakeDB()
    return InterviewsService(db), db


def _create(**overrides) -> ApplicationInterviewCreate:
    base = {
        "title": "Phone screen",
        "scheduled_at": datetime(2026, 5, 10, 14, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location": "Google Meet",
        "interviewer": "Alex (Engineering Manager)",
        "notes": "Discuss past projects, team fit.",
    }
    base.update(overrides)
    return ApplicationInterviewCreate(**base)


def test_create_persists_user_and_application_ids() -> None:
    svc, db = _svc()
    row = svc.create(USER, APP, _create())
    assert row["user_id"] == USER
    assert row["application_id"] == APP
    assert row["title"] == "Phone screen"
    assert row["duration_minutes"] == 30
    assert row["outcome"] is None
    assert len(db.store.tables["application_interviews"]) == 1


def test_list_orders_by_scheduled_at_and_scopes_to_user_and_application() -> None:
    svc, _db = _svc()
    base = datetime(2026, 5, 10, 14, 0, tzinfo=timezone.utc)
    svc.create(USER, APP, _create(title="round 2", scheduled_at=base + timedelta(days=2)))
    svc.create(USER, APP, _create(title="round 1", scheduled_at=base))
    svc.create(USER, OTHER_APP, _create(title="other-app round"))
    svc.create(OTHER, APP, _create(title="other-user round"))

    rows = svc.list_for_application(USER, APP)
    assert [r["title"] for r in rows] == ["round 1", "round 2"]


def test_update_changes_fields_and_scopes_to_owner() -> None:
    svc, _db = _svc()
    row = svc.create(USER, APP, _create())

    updated = svc.update(
        USER,
        row["id"],
        ApplicationInterviewUpdate(outcome="passed", notes="Great chat."),
    )
    assert updated is not None
    assert updated["outcome"] == "passed"
    assert updated["notes"] == "Great chat."

    spoofed = svc.update(OTHER, row["id"], ApplicationInterviewUpdate(outcome="failed"))
    assert spoofed is None


def test_update_reschedules_and_serializes_datetime() -> None:
    svc, _db = _svc()
    row = svc.create(USER, APP, _create())
    new_time = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)

    updated = svc.update(
        USER, row["id"], ApplicationInterviewUpdate(scheduled_at=new_time)
    )
    assert updated is not None
    assert updated["scheduled_at"] == new_time.isoformat()


def test_delete_only_removes_owners_row() -> None:
    svc, db = _svc()
    row = svc.create(USER, APP, _create())

    assert svc.delete(OTHER, row["id"]) is False
    assert len(db.store.tables["application_interviews"]) == 1

    assert svc.delete(USER, row["id"]) is True
    assert db.store.tables["application_interviews"] == []


def test_create_rejects_invalid_outcome() -> None:
    with pytest.raises(Exception):
        _create(outcome="bogus")  # type: ignore[arg-type]


def test_create_rejects_invalid_duration() -> None:
    with pytest.raises(Exception):
        _create(duration_minutes=0)
    with pytest.raises(Exception):
        _create(duration_minutes=10_000)
