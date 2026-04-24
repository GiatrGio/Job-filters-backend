from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db.client import SupabaseDB, get_db
from app.llm.base import LLMProvider
from app.llm.registry import build_provider
from app.schemas.user import CurrentUser
from app.services.cache import EvaluationCache
from app.services.evaluator import Evaluator
from app.services.quota import QuotaService
from app.services.rate_limit import TokenBucketLimiter

SettingsDep = Annotated[Settings, Depends(get_settings)]
DBDep = Annotated[SupabaseDB, Depends(get_db)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


@lru_cache
def _cached_provider(provider_name: str) -> LLMProvider:
    return build_provider(provider_name, get_settings())


def get_llm_provider(settings: SettingsDep) -> LLMProvider:
    return _cached_provider(settings.llm_provider)


def get_cache(db: DBDep) -> EvaluationCache:
    return EvaluationCache(db)


def get_quota(db: DBDep, settings: SettingsDep) -> QuotaService:
    return QuotaService(db, default_limit=settings.free_tier_monthly_limit)


def get_evaluator(
    db: DBDep,
    settings: SettingsDep,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    cache: Annotated[EvaluationCache, Depends(get_cache)],
    quota: Annotated[QuotaService, Depends(get_quota)],
) -> Evaluator:
    return Evaluator(db=db, provider=provider, cache=cache, quota=quota, settings=settings)


LLMProviderDep = Annotated[LLMProvider, Depends(get_llm_provider)]
CacheDep = Annotated[EvaluationCache, Depends(get_cache)]
QuotaDep = Annotated[QuotaService, Depends(get_quota)]
EvaluatorDep = Annotated[Evaluator, Depends(get_evaluator)]


@lru_cache
def _cached_evaluate_limiter(capacity: int, per_minute: float) -> TokenBucketLimiter:
    return TokenBucketLimiter(capacity=capacity, refill_per_second=per_minute / 60.0)


def get_evaluate_limiter(settings: SettingsDep) -> TokenBucketLimiter:
    return _cached_evaluate_limiter(
        settings.rate_limit_evaluate_capacity,
        settings.rate_limit_evaluate_per_minute,
    )


EvaluateLimiterDep = Annotated[TokenBucketLimiter, Depends(get_evaluate_limiter)]
