from __future__ import annotations

import pytest

from app.schemas.evaluate import JobInput
from app.services.cache import EvaluationCache, compute_filters_hash
from app.services.evaluator import Evaluator, QuotaExceeded
from app.services.quota import QuotaService, current_period
from tests.fakes.fake_db import FakeDB
from tests.fakes.fake_provider import FakeLLMProvider

USER = "user-1"


def _make_job() -> JobInput:
    return JobInput(
        linkedin_job_id="job-abc",
        job_title="Backend Engineer",
        job_company="Acme",
        job_location="Remote, EU",
        job_url="https://www.linkedin.com/jobs/view/job-abc",
        job_description="This role is fully remote within the EU. Salary not listed.",
    )


def _make_evaluator(db: FakeDB, provider: FakeLLMProvider, settings) -> Evaluator:
    return Evaluator(
        db=db,
        provider=provider,
        cache=EvaluationCache(db),
        quota=QuotaService(db, default_limit=settings.free_tier_monthly_limit),
        settings=settings,
    )


async def test_cache_miss_calls_llm_and_persists(settings) -> None:
    db = FakeDB()
    db.store.seed("profiles", [{"id": USER, "plan": "free", "monthly_eval_limit": 5}])
    db.store.seed(
        "filters",
        [{"id": "f1", "user_id": USER, "text": "fully remote", "position": 0, "enabled": True}],
    )
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    resp = await ev.evaluate(user_id=USER, job=_make_job())

    assert resp.cached is False
    assert provider.calls == 1
    assert len(resp.results) == 1
    assert resp.results[0].pass_ is True
    assert resp.usage.used == 1
    assert resp.usage.limit == 5
    assert len(db.store.tables["evaluations"]) == 1


async def test_cache_hit_does_not_call_llm_or_bump_quota(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "filters",
        [{"id": "f1", "user_id": USER, "text": "fully remote", "position": 0, "enabled": True}],
    )
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    # First call populates the cache.
    await ev.evaluate(user_id=USER, job=_make_job())
    provider.calls = 0  # reset

    # Second call with the same filters must hit the cache.
    resp = await ev.evaluate(user_id=USER, job=_make_job())

    assert resp.cached is True
    assert provider.calls == 0
    assert resp.usage.used == 1  # unchanged


async def test_filter_edit_invalidates_cache(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "filters",
        [{"id": "f1", "user_id": USER, "text": "fully remote", "position": 0, "enabled": True}],
    )
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    await ev.evaluate(user_id=USER, job=_make_job())
    # Edit the filter — filters_hash changes, cache must miss.
    db.store.tables["filters"][0]["text"] = "remote within EU"
    provider.calls = 0

    resp = await ev.evaluate(user_id=USER, job=_make_job())

    assert resp.cached is False
    assert provider.calls == 1


async def test_no_filters_returns_empty_without_llm_call(settings) -> None:
    db = FakeDB()
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    resp = await ev.evaluate(user_id=USER, job=_make_job())

    assert resp.cached is False
    assert resp.results == []
    assert provider.calls == 0
    assert resp.usage.used == 0


def test_compute_filters_hash_is_order_sensitive() -> None:
    from app.schemas.evaluate import FilterInput

    a = [FilterInput(id="1", text="x"), FilterInput(id="2", text="y")]
    b = [FilterInput(id="2", text="y"), FilterInput(id="1", text="x")]
    assert compute_filters_hash(a) != compute_filters_hash(b)


async def test_quota_exceeded_on_cache_miss(settings) -> None:
    db = FakeDB()
    db.store.seed(
        "filters",
        [{"id": "f1", "user_id": USER, "text": "fully remote", "position": 0, "enabled": True}],
    )
    # Pre-set usage at the limit for the current period.
    db.store.seed(
        "usage_counters",
        [{"user_id": USER, "year_month": current_period(), "evaluations_used": 3}],
    )
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    with pytest.raises(QuotaExceeded):
        await ev.evaluate(user_id=USER, job=_make_job())
    assert provider.calls == 0
