"""Schemas for the CV / job-fit feature.

PRIVACY: `CvProfile` is the ONLY thing we persist from a user's uploaded CV.
It is deliberately limited to non-identifying professional signal. The parse
prompt (app/llm/prompts.py) is instructed never to emit a name, email, phone,
address, link or employer name, and these fields give it nowhere to put one.
The uploaded file and its extracted text are parsed in memory and discarded.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Seniority = Literal["junior", "mid", "senior", "lead", "principal", "unknown"]


class CvProfile(BaseModel):
    """Structured, non-PII summary of a candidate, used to judge job fit."""

    # Hard skills / technologies / tools (e.g. "Python", "AWS", "Kubernetes").
    skills: list[str] = Field(default_factory=list, max_length=60)
    # Total years of professional experience, best estimate. null when unclear.
    years_experience: float | None = Field(default=None, ge=0, le=70)
    seniority: Seniority = "unknown"
    # Generic role titles held (e.g. "Backend Engineer"). NEVER employer names.
    titles: list[str] = Field(default_factory=list, max_length=20)
    # Industries / domains worked in (e.g. "fintech", "healthcare").
    domains: list[str] = Field(default_factory=list, max_length=20)
    # Education as level + field only (e.g. "BSc Computer Science"). No school.
    education: list[str] = Field(default_factory=list, max_length=10)
    # Spoken/written languages (e.g. "English", "Greek").
    languages: list[str] = Field(default_factory=list, max_length=15)
    # One or two sentences of non-identifying professional summary. No name.
    summary: str = Field(default="", max_length=600)


class CvProfileResponse(BaseModel):
    """What GET/POST /cv returns: the stored profile plus when it was parsed."""

    profile: CvProfile
    updated_at: str | None = None
