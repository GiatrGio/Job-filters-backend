from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, Field


class _FilterKind(str, Enum):
    """Local mirror of app.schemas.filter.FilterKind.

    Defined here to avoid an import cycle with app.schemas.filter, which
    imports UsageOut from this module. Kept in sync manually — both enums
    must use the same string values.
    """

    criterion = "criterion"
    question = "question"


class FilterInput(BaseModel):
    id: str
    text: str
    kind: _FilterKind = _FilterKind.criterion


class JobInput(BaseModel):
    # validation_alias accepts the legacy `linkedin_job_id` field name from
    # older extension builds, so we can rename the canonical field without
    # breaking installed clients. The serialized name is `job_id`.
    job_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("job_id", "linkedin_job_id"),
    )
    source: str = Field(
        default="linkedin",
        min_length=1,
        max_length=32,
        description="Origin of the job, e.g. 'linkedin', 'indeed', 'manual'.",
    )
    job_title: str | None = None
    job_company: str | None = None
    job_location: str | None = None
    job_url: str | None = None
    job_description: str = Field(..., min_length=1)

    model_config = {"populate_by_name": True}


class EvaluationResult(BaseModel):
    filter: str
    pass_: bool | None = Field(..., alias="pass")
    evidence: str
    # Echoed by the LLM so the side panel can pick the right icon and copy
    # treatment per row without re-doing classification client-side.
    # Optional for backward compatibility: cached results from before
    # migration 0006 don't have this field.
    kind: _FilterKind = _FilterKind.criterion

    model_config = {"populate_by_name": True}


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class UsageOut(BaseModel):
    used: int
    limit: int
    period: str  # 'YYYY-MM'
    # Ratio at which clients should show an "approaching limit" warning.
    # Server-driven so the threshold can be tuned without rebuilding the
    # extension. Defaults match the backend default in config.py.
    warning_threshold: float = 0.8


class EvaluateRequest(JobInput):
    pass


class EvaluateResponse(BaseModel):
    cached: bool
    results: list[EvaluationResult]
    usage: UsageOut


class QuotaExceededResponse(BaseModel):
    error: str = "quota_exceeded"
    usage: UsageOut
