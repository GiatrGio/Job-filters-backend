"""CV parse-and-store service (job-fit feature).

Takes already-extracted CV text, runs the CV-parse LLM call, and stores ONLY the
structured non-PII profile in `cv_profiles` (one row per user). The raw text is
never persisted, and it is redacted from the llm_calls observability log (see
app/services/llm_calls.build_prompt_payload, call_type="cv_parse").
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import Settings
from app.db.client import SupabaseDB
from app.llm.base import LLMProvider
from app.schemas.cv import CvProfile, CvProfileResponse
from app.services.llm_calls import LLMCallLogger, LLMCallTimer, build_prompt_payload


def compute_cv_hash(profile: CvProfile) -> str:
    """Stable hash over the canonical profile JSON. Drives the fit cache key:
    re-uploading a CV that parses identically keeps the hash (and cached fit
    results); any change invalidates fit without touching the filter cache."""
    canonical = json.dumps(profile.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class StoredCv:
    profile: CvProfile
    cv_hash: str
    updated_at: str | None


@dataclass
class CvService:
    db: SupabaseDB
    provider: LLMProvider
    settings: Settings

    async def parse_and_store(self, *, user_id: str, cv_text: str) -> CvProfileResponse:
        prompt = build_prompt_payload(
            provider_name=self.provider.name,
            call_type="cv_parse",
            cv_text_len=len(cv_text),
        )
        timer = LLMCallTimer.start()
        llm_logger = LLMCallLogger(self.db, self.settings)

        try:
            profile, token_usage = await self.provider.parse_cv(cv_text)
        except Exception as exc:
            llm_logger.log(
                user_id=user_id,
                call_type="cv_parse",
                provider=self.provider,
                status="error",
                prompt=prompt,
                error=str(exc),
                duration_ms=timer.elapsed_ms(),
                summary="CV parse failed",
            )
            raise

        llm_logger.log(
            user_id=user_id,
            call_type="cv_parse",
            provider=self.provider,
            status="success",
            prompt=prompt,
            response=profile.model_dump(mode="json"),
            token_usage=token_usage,
            duration_ms=timer.elapsed_ms(),
            summary=f"CV parsed: {len(profile.skills)} skills, {profile.seniority}",
        )

        now = datetime.now(UTC).isoformat()
        cv_hash = compute_cv_hash(profile)
        self.db.table("cv_profiles").upsert(
            {
                "user_id": user_id,
                "profile": profile.model_dump(mode="json"),
                "cv_hash": cv_hash,
                "provider": self.provider.name,
                "model": self.provider.model,
                "updated_at": now,
            },
            on_conflict="user_id",
        ).execute()

        return CvProfileResponse(profile=profile, updated_at=now)

    def update_profile(self, *, user_id: str, profile: CvProfile) -> CvProfileResponse:
        """Replace the stored profile with a user-edited one (no LLM call).

        Recomputes cv_hash so the new profile automatically invalidates any
        cached fit results (keyed by cv_hash) — the next job view re-evaluates
        fit against the edited profile. The original parse's provider/model are
        preserved on update so /admin still shows what produced the first draft.
        """
        now = datetime.now(UTC).isoformat()
        payload = {
            "profile": profile.model_dump(mode="json"),
            "cv_hash": compute_cv_hash(profile),
            "updated_at": now,
        }
        existing = (
            self.db.table("cv_profiles")
            .select("user_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            self.db.table("cv_profiles").update(payload).eq("user_id", user_id).execute()
        else:
            # No prior upload (e.g. a fully manual profile) — record it as such.
            self.db.table("cv_profiles").insert(
                {**payload, "user_id": user_id, "provider": "manual", "model": "manual"}
            ).execute()
        return CvProfileResponse(profile=profile, updated_at=now)

    def get(self, user_id: str) -> StoredCv | None:
        resp = (
            self.db.table("cv_profiles")
            .select("profile, cv_hash, updated_at")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        if not data:
            return None
        row = data[0]
        return StoredCv(
            profile=CvProfile.model_validate(row["profile"]),
            cv_hash=str(row["cv_hash"]),
            updated_at=row.get("updated_at"),
        )

    def get_response(self, user_id: str) -> CvProfileResponse | None:
        stored = self.get(user_id)
        if stored is None:
            return None
        return CvProfileResponse(profile=stored.profile, updated_at=stored.updated_at)

    def delete(self, user_id: str) -> None:
        # Remove the profile and any fit results derived from it. The fit rows
        # carry no PII, but deleting them keeps "remove my CV" clean and stops
        # stale fit cache from lingering under a dead cv_hash.
        self.db.table("cv_profiles").delete().eq("user_id", user_id).execute()
        self.db.table("job_fit_evaluations").delete().eq("user_id", user_id).execute()
