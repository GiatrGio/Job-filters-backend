"""Server-side job-fit cache.

Keyed by (user_id, source, job_id, cv_hash). A new CV (different cv_hash)
invalidates fit results without touching the filter-evaluation cache, and a
filter edit never invalidates fit. Mirrors app/services/cache.py.
"""

from __future__ import annotations

from app.db.client import SupabaseDB
from app.schemas.fit import JobFitResult


class JobFitCache:
    def __init__(self, db: SupabaseDB) -> None:
        self._db = db

    def get(
        self,
        *,
        user_id: str,
        source: str,
        job_id: str,
        cv_hash: str,
    ) -> JobFitResult | None:
        resp = (
            self._db.table("job_fit_evaluations")
            .select("score, dimensions, strengths, gaps, summary")
            .eq("user_id", user_id)
            .eq("source", source)
            .eq("job_id", job_id)
            .eq("cv_hash", cv_hash)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        if not data:
            return None
        row = data[0]
        return JobFitResult.model_validate(
            {
                "score": row["score"],
                "dimensions": row["dimensions"],
                "strengths": row.get("strengths") or [],
                "gaps": row.get("gaps") or [],
                "summary": row.get("summary") or "",
            }
        )

    def put(
        self,
        *,
        user_id: str,
        source: str,
        job_id: str,
        cv_hash: str,
        job_title: str | None,
        job_company: str | None,
        job_url: str | None,
        fit: JobFitResult,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._db.table("job_fit_evaluations").insert(
            {
                "user_id": user_id,
                "source": source,
                "job_id": job_id,
                "cv_hash": cv_hash,
                "job_title": job_title,
                "job_company": job_company,
                "job_url": job_url,
                "score": fit.score,
                "dimensions": fit.dimensions.model_dump(),
                "strengths": [p.model_dump() for p in fit.strengths],
                "gaps": [p.model_dump() for p in fit.gaps],
                "summary": fit.summary,
                "provider": provider,
                "model": model,
                "tokens_input": input_tokens,
                "tokens_output": output_tokens,
            }
        ).execute()
