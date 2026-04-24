from __future__ import annotations

from app.services.quota import QuotaService, current_period
from tests.fakes.fake_db import FakeDB

USER = "user-q"


def test_status_uses_profile_limit_when_present() -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "monthly_eval_limit": 200}])
    q = QuotaService(db, default_limit=50)

    status = q.status(USER)

    assert status.limit == 200
    assert status.used == 0
    assert status.exceeded is False


def test_status_falls_back_to_default_limit_without_profile() -> None:
    db = FakeDB()
    q = QuotaService(db, default_limit=50)

    status = q.status(USER)

    assert status.limit == 50
    assert status.used == 0


def test_increment_calls_atomic_rpc() -> None:
    db = FakeDB()
    q = QuotaService(db, default_limit=10)

    s1 = q.increment(USER)
    s2 = q.increment(USER)

    assert s1.used == 1
    assert s2.used == 2
    rows = db.store.tables["usage_counters"]
    assert len(rows) == 1
    assert rows[0]["year_month"] == current_period()
    assert rows[0]["evaluations_used"] == 2


def test_exceeded_flag() -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "monthly_eval_limit": 2}])
    q = QuotaService(db, default_limit=50)

    q.increment(USER)
    q.increment(USER)
    status = q.status(USER)

    assert status.used == 2
    assert status.limit == 2
    assert status.exceeded is True
