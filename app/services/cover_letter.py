"""Cover-letter settings + on-demand generation.

Settings (the single default-instructions block + the identity block) live in
`cover_letter_settings`, one row per user. Generation loads the user's CV
profile and settings, gates on the monthly cover-letter quota, calls the LLM,
increments the meter on success, and returns the letter prose.

PRIVACY guardrails (see migration 0015):
  - The generated letter is NEVER persisted server-side — it is returned to the
    extension and cached client-side only. We log only that a generation
    succeeded, not the text.
  - The candidate's name/email/phone/location never enter the LLM prompt (the
    header is composed client-side); only `achievements` does, and it is
    redacted from the llm_calls log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import Settings
from app.db.client import SupabaseDB
from app.llm.base import LLMProvider
from app.schemas.cover_letter import (
    CoverLetterSettings,
    CoverLetterSettingsResponse,
    GenerateCoverLetterResponse,
)
from app.schemas.cv import CvContact
from app.schemas.evaluate import JobInput, UsageOut
from app.services.cv import CvService
from app.services.evaluator import QuotaExceeded
from app.services.llm_calls import (
    LLMCallLogger,
    LLMCallTimer,
    build_prompt_payload,
    summarize_job,
)
from app.services.quota import QuotaService, QuotaStatus

_SETTINGS_COLUMNS = "instructions, full_name, email, phone, location, updated_at"


@dataclass
class CoverLetterService:
    db: SupabaseDB
    provider: LLMProvider
    cv_service: CvService
    quota: QuotaService
    settings: Settings

    # -- settings ---------------------------------------------------------
    def get_settings(self, user_id: str) -> CoverLetterSettingsResponse:
        # Always returns a settings object (defaults when the user has none yet)
        # so the extension's settings form can render empty fields directly.
        resp = (
            self.db.table("cover_letter_settings")
            .select(_SETTINGS_COLUMNS)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        if not data:
            return CoverLetterSettingsResponse(
                settings=CoverLetterSettings(), updated_at=None
            )
        row = data[0]
        return CoverLetterSettingsResponse(
            settings=CoverLetterSettings.model_validate(row),
            updated_at=row.get("updated_at"),
        )

    def upsert_settings(
        self, *, user_id: str, settings: CoverLetterSettings
    ) -> CoverLetterSettingsResponse:
        now = datetime.now(UTC).isoformat()
        self.db.table("cover_letter_settings").upsert(
            {
                "user_id": user_id,
                **settings.model_dump(mode="json"),
                "updated_at": now,
            },
            on_conflict="user_id",
        ).execute()
        return CoverLetterSettingsResponse(settings=settings, updated_at=now)

    def prefill_identity_from_contact(
        self, *, user_id: str, contact: CvContact
    ) -> None:
        """Fill ONLY empty identity fields from CV-extracted contact.

        Never overwrites values the user already entered, and never touches
        `instructions`. Called best-effort after a CV upload.
        """
        current = self.get_settings(user_id).settings
        patch: dict[str, str] = {}
        if not current.full_name.strip() and contact.full_name.strip():
            patch["full_name"] = contact.full_name.strip()
        if not current.email.strip() and contact.email.strip():
            patch["email"] = contact.email.strip()
        if not current.phone.strip() and contact.phone.strip():
            patch["phone"] = contact.phone.strip()
        if not current.location.strip() and contact.location.strip():
            patch["location"] = contact.location.strip()
        if not patch:
            return
        self.upsert_settings(user_id=user_id, settings=current.model_copy(update=patch))

    # -- generation -------------------------------------------------------
    def _usage(self, status: QuotaStatus) -> UsageOut:
        return UsageOut(
            used=status.used,
            limit=status.limit,
            period=status.period,
            warning_threshold=status.warning_threshold,
        )

    async def generate(
        self, *, user_id: str, job: JobInput
    ) -> GenerateCoverLetterResponse:
        status = self.quota.cover_letter_status(user_id)

        stored_cv = self.cv_service.get(user_id)
        settings = self.get_settings(user_id).settings

        # Empty states — never spend a unit or call the LLM when we can't
        # produce a real letter (mirrors fit's has_cv short-circuit).
        if stored_cv is None:
            return GenerateCoverLetterResponse(
                has_cv=False,
                has_identity=settings.has_identity,
                letter=None,
                usage=self._usage(status),
            )
        if not settings.has_identity:
            return GenerateCoverLetterResponse(
                has_cv=True, has_identity=False, letter=None, usage=self._usage(status)
            )

        # Real work → gate on the monthly quota BEFORE calling the LLM.
        if status.exceeded:
            raise QuotaExceeded(status)

        prompt = build_prompt_payload(
            provider_name=self.provider.name,
            call_type="cover_letter",
            job=job,
            cv=stored_cv.profile,
            instructions=settings.instructions,
        )
        timer = LLMCallTimer.start()
        llm_logger = LLMCallLogger(self.db, self.settings)
        try:
            letter, token_usage = await self.provider.generate_cover_letter(
                job, stored_cv.profile, settings.instructions
            )
        except Exception as exc:
            llm_logger.log(
                user_id=user_id,
                call_type="cover_letter",
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

        # PRIVACY: log success WITHOUT the letter text — only a small,
        # non-identifying note. The letter is returned to the client, not stored.
        llm_logger.log(
            user_id=user_id,
            call_type="cover_letter",
            provider=self.provider,
            status="success",
            prompt=prompt,
            response={
                "paragraphs": len(letter.body_paragraphs),
                "note": "letter text not stored",
            },
            token_usage=token_usage,
            duration_ms=timer.elapsed_ms(),
            source=job.source,
            external_id=job.job_id,
            summary=f"{summarize_job(job)} — cover letter",
        )

        # Consume a unit only after a successful generation.
        new_status = self.quota.increment_cover_letter(user_id)

        return GenerateCoverLetterResponse(
            has_cv=True,
            has_identity=True,
            letter=letter,
            usage=self._usage(new_status),
        )
