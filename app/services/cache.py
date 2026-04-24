"""Server-side evaluation cache.

Keyed by (user_id, linkedin_job_id, filters_hash). Any edit to the filter set
produces a new filters_hash, which automatically invalidates prior results
without requiring an explicit delete. Old rows stay for history/debug.
"""

from __future__ import annotations

import hashlib

from app.db.client import SupabaseDB
from app.schemas.evaluate import EvaluationResult, FilterInput


def compute_filters_hash(filters: list[FilterInput]) -> str:
    """Stable hash over the ordered (id, text) pairs.

    Uses id+text so that renaming a filter OR reordering filters invalidates
    the cache — because both can change what the LLM returns.
    """
    h = hashlib.sha256()
    for f in filters:
        h.update(f.id.encode("utf-8"))
        h.update(b"\x1f")
        h.update(f.text.encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


class EvaluationCache:
    def __init__(self, db: SupabaseDB) -> None:
        self._db = db

    def get(
        self,
        *,
        user_id: str,
        linkedin_job_id: str,
        filters_hash: str,
    ) -> list[EvaluationResult] | None:
        resp = (
            self._db.table("evaluations")
            .select("results")
            .eq("user_id", user_id)
            .eq("linkedin_job_id", linkedin_job_id)
            .eq("filters_hash", filters_hash)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        if not data:
            return None
        raw = data[0].get("results") or []
        return [EvaluationResult.model_validate(r) for r in raw]

    def put(
        self,
        *,
        user_id: str,
        job_id: str,
        job_title: str | None,
        job_company: str | None,
        job_url: str | None,
        filters_hash: str,
        results: list[EvaluationResult],
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._db.table("evaluations").insert(
            {
                "user_id": user_id,
                "linkedin_job_id": job_id,
                "job_title": job_title,
                "job_company": job_company,
                "job_url": job_url,
                "filters_hash": filters_hash,
                "results": [r.model_dump(by_alias=True) for r in results],
                "provider": provider,
                "model": model,
                "tokens_input": input_tokens,
                "tokens_output": output_tokens,
            }
        ).execute()
