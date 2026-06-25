"""Orchestrates per-job fit evaluation: CV → cache → quota gate → LLM → persist.

Separate from the filter Evaluator on purpose (see app/schemas/fit.py). Two
behavioural rules specific to fit:

  - It rides FREE: a cache miss is gated by the user's remaining quota (so a free
    user who is out of evaluations stops getting fit too), but it never
    increments the counter. The matching /evaluate call is what consumes a unit.
  - No CV → returns has_cv=False without calling the LLM, so the side panel can
    show the "upload your CV" empty state.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.db.client import SupabaseDB
from app.llm.base import LLMProvider
from app.schemas.evaluate import JobInput, UsageOut
from app.schemas.fit import EvaluateFitResponse
from app.services.cv import CvService
from app.services.evaluator import QuotaExceeded
from app.services.fit_cache import JobFitCache
from app.services.llm_calls import (
    LLMCallLogger,
    LLMCallTimer,
    build_prompt_payload,
    summarize_job,
)
from app.services.quota import QuotaService, QuotaStatus


@dataclass
class FitEvaluator:
    db: SupabaseDB
    provider: LLMProvider
    cv_service: CvService
    cache: JobFitCache
    quota: QuotaService
    settings: Settings

    def _usage(self, status: QuotaStatus) -> UsageOut:
        return UsageOut(
            used=status.used,
            limit=status.limit,
            period=status.period,
            warning_threshold=status.warning_threshold,
        )

    async def evaluate_fit(self, *, user_id: str, job: JobInput) -> EvaluateFitResponse:
        status = self.quota.status(user_id)

        stored = self.cv_service.get(user_id)
        if stored is None:
            return EvaluateFitResponse(
                cached=False, has_cv=False, fit=None, usage=self._usage(status)
            )

        cached = self.cache.get(
            user_id=user_id,
            source=job.source,
            job_id=job.job_id,
            cv_hash=stored.cv_hash,
        )
        if cached is not None:
            return EvaluateFitResponse(
                cached=True, has_cv=True, fit=cached, usage=self._usage(status)
            )

        # Cache miss → real LLM work. Gate on quota (but never increment it).
        if status.exceeded:
            raise QuotaExceeded(status)

        prompt = build_prompt_payload(
            provider_name=self.provider.name,
            call_type="job_fit",
            job=job,
            cv=stored.profile,
        )
        timer = LLMCallTimer.start()
        llm_logger = LLMCallLogger(self.db, self.settings)
        try:
            fit, token_usage = await self.provider.evaluate_fit(job, stored.profile)
        except Exception as exc:
            llm_logger.log(
                user_id=user_id,
                call_type="job_fit",
                provider=self.provider,
                status="error",
                prompt=prompt,
                error=str(exc),
                duration_ms=timer.elapsed_ms(),
                source=job.source,
                external_id=job.job_id,
                summary=summarize_job(job),
            )
            raise

        llm_logger.log(
            user_id=user_id,
            call_type="job_fit",
            provider=self.provider,
            status="success",
            prompt=prompt,
            response=fit.model_dump(mode="json"),
            token_usage=token_usage,
            duration_ms=timer.elapsed_ms(),
            source=job.source,
            external_id=job.job_id,
            summary=f"{summarize_job(job)} — fit {fit.score}/5",
        )
        self.cache.put(
            user_id=user_id,
            source=job.source,
            job_id=job.job_id,
            cv_hash=stored.cv_hash,
            job_title=job.job_title,
            job_company=job.job_company,
            job_url=job.job_url,
            fit=fit,
            provider=self.provider.name,
            model=self.provider.model,
            input_tokens=token_usage.input_tokens,
            output_tokens=token_usage.output_tokens,
        )

        # Intentionally NO quota increment — fit rides free alongside /evaluate.
        return EvaluateFitResponse(
            cached=False, has_cv=True, fit=fit, usage=self._usage(status)
        )
