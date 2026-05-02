"""Orchestrates the full evaluation pipeline: cache → quota → LLM → persist.

Raises QuotaExceeded on a cache miss when the user is over their limit — the
router maps this to HTTP 402. Cache hits never touch the quota.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db.client import SupabaseDB
from app.llm.base import LLMProvider
from app.schemas.evaluate import (
    EvaluateResponse,
    EvaluationResult,
    FilterInput,
    JobInput,
    UsageOut,
)
from app.services.cache import EvaluationCache, compute_filters_hash
from app.services.quota import QuotaService, QuotaStatus


class QuotaExceeded(Exception):
    def __init__(self, status: QuotaStatus) -> None:
        super().__init__("quota exceeded")
        self.status = status


@dataclass
class Evaluator:
    db: SupabaseDB
    provider: LLMProvider
    cache: EvaluationCache
    quota: QuotaService
    settings: Settings

    def _load_filters(self, user_id: str) -> list[FilterInput]:
        # Filters are scoped to the user's currently active profile. If no
        # active profile exists (shouldn't happen — the signup trigger creates
        # one — but defensively), treat it as no filters.
        active = (
            self.db.table("filter_profiles")
            .select("id")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        active_rows = active.data or []
        if not active_rows:
            return []
        profile_id = active_rows[0]["id"]
        resp = (
            self.db.table("filters")
            .select("id, text, position, enabled, kind")
            .eq("profile_id", profile_id)
            .eq("enabled", True)
            .order("position")
            .execute()
        )
        rows = resp.data or []
        # `kind` defaults to "criterion" so any pre-migration row that
        # somehow lacks the column still produces a usable FilterInput.
        return [
            FilterInput(
                id=str(r["id"]),
                text=r["text"],
                kind=r.get("kind") or "criterion",
            )
            for r in rows
        ]

    async def evaluate(self, *, user_id: str, job: JobInput) -> EvaluateResponse:
        filters = self._load_filters(user_id)
        filters_hash = compute_filters_hash(filters)

        cached = self.cache.get(
            user_id=user_id,
            source=job.source,
            job_id=job.job_id,
            filters_hash=filters_hash,
        )
        if cached is not None:
            status = self.quota.status(user_id)
            return EvaluateResponse(
                cached=True,
                results=cached,
                usage=UsageOut(used=status.used, limit=status.limit, period=status.period),
            )

        pre_status = self.quota.status(user_id)
        if pre_status.exceeded:
            raise QuotaExceeded(pre_status)

        if not filters:
            # No filters configured → return an empty result set without calling the LLM.
            # This is a cache miss that didn't cost a token; don't bump the counter.
            results: list[EvaluationResult] = []
        else:
            results, token_usage = await self.provider.evaluate(job, filters)
            self.cache.put(
                user_id=user_id,
                source=job.source,
                job_id=job.job_id,
                job_title=job.job_title,
                job_company=job.job_company,
                job_url=job.job_url,
                filters_hash=filters_hash,
                results=results,
                provider=self.provider.name,
                model=self.provider.model,
                input_tokens=token_usage.input_tokens,
                output_tokens=token_usage.output_tokens,
            )
            pre_status = self.quota.increment(user_id)

        return EvaluateResponse(
            cached=False,
            results=results,
            usage=UsageOut(
                used=pre_status.used,
                limit=pre_status.limit,
                period=pre_status.period,
            ),
        )
