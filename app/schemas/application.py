"""Application tracker schemas.

The tracker has a single shape (`Application`) with three views:
  - ApplicationCreate: what extension or website sends to POST /applications.
  - ApplicationOut: what list and detail endpoints return.
  - ApplicationListItem: a slimmer view without the description, used for the
    dashboard list to keep payloads small.
  - ApplicationUpdate: partial update over status / applied_at / notes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ApplicationStatus = Literal[
    "saved", "applied", "interviewing", "offer", "rejected", "withdrawn"
]

VALID_STATUSES: tuple[str, ...] = (
    "saved", "applied", "interviewing", "offer", "rejected", "withdrawn",
)

# Caps mirror the implicit DB column types. Keep these in sync if the schema
# tightens (e.g. with a check constraint on title length).
SOURCE_MAX = 32
EXTERNAL_ID_MAX = 128
TEXT_FIELD_MAX = 500
DESCRIPTION_MAX = 50_000
NOTES_MAX = 5_000


class ApplicationBase(BaseModel):
    source: str = Field(..., min_length=1, max_length=SOURCE_MAX)
    external_id: str = Field(..., min_length=1, max_length=EXTERNAL_ID_MAX)
    title: str | None = Field(None, max_length=TEXT_FIELD_MAX)
    company: str | None = Field(None, max_length=TEXT_FIELD_MAX)
    location: str | None = Field(None, max_length=TEXT_FIELD_MAX)
    url: str | None = Field(None, max_length=TEXT_FIELD_MAX)


class ApplicationCreate(ApplicationBase):
    description: str | None = Field(None, max_length=DESCRIPTION_MAX)
    status: ApplicationStatus = "saved"
    applied_at: datetime | None = None
    notes: str | None = Field(None, max_length=NOTES_MAX)


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    applied_at: datetime | None = None
    notes: str | None = Field(None, max_length=NOTES_MAX)
    title: str | None = Field(None, max_length=TEXT_FIELD_MAX)
    company: str | None = Field(None, max_length=TEXT_FIELD_MAX)
    location: str | None = Field(None, max_length=TEXT_FIELD_MAX)
    url: str | None = Field(None, max_length=TEXT_FIELD_MAX)


class ApplicationListItem(ApplicationBase):
    id: str
    user_id: str
    status: ApplicationStatus
    applied_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ApplicationOut(ApplicationListItem):
    description: str | None
