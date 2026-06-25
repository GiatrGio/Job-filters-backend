"""Schemas for per-job fit evaluation (candidate CV profile vs a job posting).

Fit is evaluated in a separate LLM call from filter evaluation, with its own
cache (keyed by cv_hash, see app/services/fit_cache.py) and its own endpoint
(POST /evaluate-fit), so the side panel can render filters and fit independently
(progressive rendering) and so a filter edit never re-runs fit and vice versa.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.evaluate import JobInput, UsageOut


class FitPoint(BaseModel):
    """A single strength or gap, with a short justification."""

    point: str = Field(..., max_length=160)
    # Why we think so — grounded in the CV profile and/or the job text.
    evidence: str = Field(default="", max_length=240)


class FitDimensions(BaseModel):
    """Sub-scores behind the overall match, each on the same 1–5 scale."""

    skills: int = Field(..., ge=1, le=5)
    experience: int = Field(..., ge=1, le=5)
    domain: int = Field(..., ge=1, le=5)


class JobFitResult(BaseModel):
    # Overall match, 1 (poor fit) … 5 (strong match).
    score: int = Field(..., ge=1, le=5)
    dimensions: FitDimensions
    strengths: list[FitPoint] = Field(default_factory=list, max_length=8)
    gaps: list[FitPoint] = Field(default_factory=list, max_length=8)
    # One short, encouraging-but-honest line summarising the match.
    summary: str = Field(default="", max_length=400)


class EvaluateFitRequest(JobInput):
    pass


class EvaluateFitResponse(BaseModel):
    cached: bool
    # False when the user has not uploaded a CV yet → the side panel shows the
    # "upload your CV to see your match" empty state and `fit` is null.
    has_cv: bool
    fit: JobFitResult | None
    usage: UsageOut
