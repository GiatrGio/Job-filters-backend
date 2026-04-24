from __future__ import annotations

from pydantic import BaseModel, Field


class FilterInput(BaseModel):
    id: str
    text: str


class JobInput(BaseModel):
    linkedin_job_id: str = Field(..., min_length=1, max_length=64)
    job_title: str | None = None
    job_company: str | None = None
    job_location: str | None = None
    job_url: str | None = None
    job_description: str = Field(..., min_length=1)


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
