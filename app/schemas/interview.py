"""Application interview schemas.

Free-form interview rounds — see migrations/0009_application_interviews.sql.
The Calendar view will eventually fetch ranges via a yet-to-be-added
`/interviews/upcoming` endpoint that bypasses the per-application path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

InterviewOutcome = Literal["passed", "failed", "no_show", "cancelled"]

VALID_OUTCOMES: tuple[str, ...] = ("passed", "failed", "no_show", "cancelled")

TITLE_MAX = 200
LOCATION_MAX = 500
INTERVIEWER_MAX = 500
NOTES_MAX = 2_000
DURATION_MIN = 1
DURATION_MAX = 1_440


class ApplicationInterviewCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=TITLE_MAX)
    scheduled_at: datetime
    duration_minutes: int = Field(60, ge=DURATION_MIN, le=DURATION_MAX)
    location: str | None = Field(None, max_length=LOCATION_MAX)
    interviewer: str | None = Field(None, max_length=INTERVIEWER_MAX)
    notes: str | None = Field(None, max_length=NOTES_MAX)
    outcome: InterviewOutcome | None = None


class ApplicationInterviewUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=TITLE_MAX)
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(None, ge=DURATION_MIN, le=DURATION_MAX)
    location: str | None = Field(None, max_length=LOCATION_MAX)
    interviewer: str | None = Field(None, max_length=INTERVIEWER_MAX)
    notes: str | None = Field(None, max_length=NOTES_MAX)
    outcome: InterviewOutcome | None = None


class ApplicationInterviewOut(BaseModel):
    id: str
    application_id: str
    user_id: str
    title: str
    scheduled_at: datetime
    duration_minutes: int
    location: str | None
    interviewer: str | None
    notes: str | None
    outcome: InterviewOutcome | None
    created_at: datetime
    updated_at: datetime
