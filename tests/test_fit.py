from __future__ import annotations

import pytest

from app.schemas.cv import CvProfile
from app.schemas.evaluate import JobInput
from app.services.cv import CvService, compute_cv_hash
from app.services.evaluator import QuotaExceeded
from app.services.fit_cache import JobFitCache
from app.services.fit_evaluator import FitEvaluator
from app.services.quota import QuotaService, current_period
from tests.fakes.fake_db import FakeDB
from tests.fakes.fake_provider import FakeLLMProvider

USER = "user-fit"


def _make_job() -> JobInput:
    return JobInput(
        job_id="job-fit-1",
        source="linkedin",
        job_title="Backend Engineer",
        job_company="Acme",
        job_location="Remote, EU",
        job_url="https://www.linkedin.com/jobs/view/job-fit-1",
        job_description="We use Python and AWS. Fully remote within the EU.",
    )


def _make_evaluator(db: FakeDB, provider: FakeLLMProvider, settings) -> FitEvaluator:
    return FitEvaluator(
        db=db,
        provider=provider,
        cv_service=CvService(db=db, provider=provider, settings=settings),
        cache=JobFitCache(db),
        quota=QuotaService(db, default_limit=settings.free_tier_monthly_limit),
        settings=settings,
    )


def _seed_cv(db: FakeDB, *, skills: list[str], cv_hash: str | None = None) -> None:
    profile = CvProfile(skills=skills, seniority="senior")
    db.store.tables["cv_profiles"] = [
        {
            "user_id": USER,
            "profile": profile.model_dump(mode="json"),
            "cv_hash": cv_hash or compute_cv_hash(profile),
            "provider": "fake",
            "model": "fake-model",
        }
    ]


async def test_no_cv_returns_has_cv_false_without_llm(settings) -> None:
    db = FakeDB()
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    resp = await ev.evaluate_fit(user_id=USER, job=_make_job())

    assert resp.has_cv is False
    assert resp.fit is None
    assert provider.fit_calls == 0


async def test_cache_miss_calls_llm_persists_and_does_not_bump_quota(settings) -> None:
    db = FakeDB()
    _seed_cv(db, skills=["Python", "Aws"])
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    resp = await ev.evaluate_fit(user_id=USER, job=_make_job())

    assert resp.has_cv is True
    assert resp.cached is False
    assert provider.fit_calls == 1
    assert resp.fit is not None
    # Both seeded skills appear in the description → 2 matches → score 3.
    assert resp.fit.score == 3
    assert {s.point for s in resp.fit.strengths} == {"Has Python", "Has Aws"}
    assert len(db.store.tables["job_fit_evaluations"]) == 1
    # Fit rides free: the eval counter is untouched (no counter row written —
    # only the increment RPC creates one; a status read does not).
    assert resp.usage.used == 0
    assert db.store.tables.get("usage_counters", []) == []


async def test_cache_hit_does_not_call_llm(settings) -> None:
    db = FakeDB()
    _seed_cv(db, skills=["Python"])
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    await ev.evaluate_fit(user_id=USER, job=_make_job())
    provider.fit_calls = 0

    resp = await ev.evaluate_fit(user_id=USER, job=_make_job())

    assert resp.cached is True
    assert provider.fit_calls == 0


async def test_new_cv_invalidates_fit_cache(settings) -> None:
    db = FakeDB()
    _seed_cv(db, skills=["Python"])
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    await ev.evaluate_fit(user_id=USER, job=_make_job())
    # Simulate a re-upload that parses to a different profile (new cv_hash).
    db.store.tables["cv_profiles"][0]["cv_hash"] = "different-hash"
    provider.fit_calls = 0

    resp = await ev.evaluate_fit(user_id=USER, job=_make_job())

    assert resp.cached is False
    assert provider.fit_calls == 1


async def test_filter_cache_is_independent(settings) -> None:
    """A fit result lives in its own table — nothing here touches `evaluations`."""
    db = FakeDB()
    _seed_cv(db, skills=["Python"])
    ev = _make_evaluator(db, FakeLLMProvider(), settings)

    await ev.evaluate_fit(user_id=USER, job=_make_job())

    assert "job_fit_evaluations" in db.store.tables
    assert "evaluations" not in db.store.tables


async def test_quota_exceeded_blocks_fit_on_cache_miss(settings) -> None:
    db = FakeDB()
    _seed_cv(db, skills=["Python"])
    db.store.seed("profiles", [{"id": USER, "plan": "free", "monthly_eval_limit": 3}])
    db.store.seed(
        "usage_counters",
        [{"user_id": USER, "year_month": current_period(), "evaluations_used": 3}],
    )
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    with pytest.raises(QuotaExceeded):
        await ev.evaluate_fit(user_id=USER, job=_make_job())
    assert provider.fit_calls == 0


async def test_cached_fit_served_even_when_over_quota(settings) -> None:
    """A cache hit never calls the LLM, so being over quota must not block it."""
    db = FakeDB()
    _seed_cv(db, skills=["Python"])
    provider = FakeLLMProvider()
    ev = _make_evaluator(db, provider, settings)

    # Populate the cache while under quota.
    await ev.evaluate_fit(user_id=USER, job=_make_job())

    # Now push the user over quota and confirm the cached fit still returns.
    db.store.seed("profiles", [{"id": USER, "plan": "free", "monthly_eval_limit": 3}])
    db.store.seed(
        "usage_counters",
        [{"user_id": USER, "year_month": current_period(), "evaluations_used": 3}],
    )
    provider.fit_calls = 0

    resp = await ev.evaluate_fit(user_id=USER, job=_make_job())

    assert resp.cached is True
    assert resp.fit is not None
    assert provider.fit_calls == 0
