from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field


class FilterInput(BaseModel):
    id: str
    text: str


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

    model_config = {"populate_by_name": True}


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class UsageOut(BaseModel):
    used: int
    limit: int
    period: str  # 'YYYY-MM'


class EvaluateRequest(JobInput):
    pass


class EvaluateResponse(BaseModel):
    cached: bool
    results: list[EvaluationResult]
    usage: UsageOut


class QuotaExceededResponse(BaseModel):
    error: str = "quota_exceeded"
    usage: UsageOut
