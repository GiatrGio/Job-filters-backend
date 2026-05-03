"""Application contact schemas.

Lightweight per-job contacts (recruiter, hiring manager, etc.). Not reusable
across jobs in the MVP — see migrations/0008_application_contacts.sql for the
rationale.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

NAME_MAX = 200
ROLE_MAX = 100
EMAIL_MAX = 320
URL_MAX = 500
NOTES_MAX = 2_000


class ApplicationContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=NAME_MAX)
    role: str | None = Field(None, max_length=ROLE_MAX)
    email: str | None = Field(None, max_length=EMAIL_MAX)
    linkedin_url: str | None = Field(None, max_length=URL_MAX)
    notes: str | None = Field(None, max_length=NOTES_MAX)


class ApplicationContactUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=NAME_MAX)
    role: str | None = Field(None, max_length=ROLE_MAX)
    email: str | None = Field(None, max_length=EMAIL_MAX)
    linkedin_url: str | None = Field(None, max_length=URL_MAX)
    notes: str | None = Field(None, max_length=NOTES_MAX)


class ApplicationContactOut(BaseModel):
    id: str
    application_id: str
    user_id: str
    name: str
    role: str | None
    email: str | None
    linkedin_url: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
