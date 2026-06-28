"""Schemas for on-demand cover-letter generation.

PRIVACY: `CoverLetterSettings` stores the candidate's identity block on purpose
(the user's choice — see migration 0015 and the privacy policy's "Cover-letter
details" section), so we can render a complete header/signature. Two guardrails
hold:
  - The generated letter text is NEVER stored server-side — it is returned to the
    extension and cached client-side only.
  - The name/email/phone/location are NOT sent to the LLM (the header is composed
    client-side); only `instructions` reaches the prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.evaluate import JobInput, UsageOut
from app.schemas.filter import FilterValidationVerdict

# Caps bound prompt size / abuse and mirror the extension's input limits.
# Instructions absorb the old "achievements" field, so the cap is generous.
INSTRUCTIONS_MAX = 2000
FULL_NAME_MAX = 120
EMAIL_MAX = 160
PHONE_MAX = 40
LOCATION_MAX = 160


class CoverLetterSettings(BaseModel):
    """Per-user default generation instructions + identity block."""

    # Single global free-text block: how the letter should read (tone, length,
    # paragraphs) AND any concrete achievements / things to emphasize. Validated
    # on save like a filter; this is the only settings field sent to the LLM.
    instructions: str = Field(default="", max_length=INSTRUCTIONS_MAX)
    # Identity — used to compose the letter header/signature client-side. Never
    # sent to the LLM. Can be pre-filled from the user's CV on upload.
    full_name: str = Field(default="", max_length=FULL_NAME_MAX)
    email: str = Field(default="", max_length=EMAIL_MAX)
    phone: str = Field(default="", max_length=PHONE_MAX)
    location: str = Field(default="", max_length=LOCATION_MAX)

    @property
    def has_identity(self) -> bool:
        # A name is the minimum needed to produce a real letter header/signature.
        return bool(self.full_name.strip())


class CoverLetterSettingsResponse(BaseModel):
    settings: CoverLetterSettings
    updated_at: str | None = None


class CoverLetterContent(BaseModel):
    """The generated letter prose. The header (name/contact), date and signature
    are composed client-side from the identity block, so the model returns only
    the body."""

    greeting: str = Field(default="", max_length=200)  # e.g. "Dear Hiring Manager,"
    body_paragraphs: list[str] = Field(default_factory=list, max_length=8)
    closing: str = Field(default="", max_length=80)  # e.g. "Sincerely,"


class GenerateCoverLetterRequest(JobInput):
    pass


class GenerateCoverLetterResponse(BaseModel):
    # has_cv / has_identity drive the side panel's empty states (mirrors
    # EvaluateFitResponse.has_cv). `letter` is null when either is missing — in
    # which case no quota is spent and no LLM call is made.
    has_cv: bool
    has_identity: bool
    letter: CoverLetterContent | None
    usage: UsageOut


# ---------------------------------------------------------------------------
# Default-instructions validation — mirrors filter validation (good/vague/
# rejected), and counts against the same filter-validation monthly meter.
# ---------------------------------------------------------------------------


class CoverLetterInstructionsValidationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=INSTRUCTIONS_MAX)


class CoverLetterInstructionsValidationResult(BaseModel):
    verdict: FilterValidationVerdict
    reason: str
    suggestion: str | None = None


class CoverLetterInstructionsValidationResponse(CoverLetterInstructionsValidationResult):
    usage: UsageOut
