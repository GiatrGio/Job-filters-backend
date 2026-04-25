from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.filter import FilterOut

# Caps mirror the DB check constraints; see app/schemas/filter.py for the same
# pattern around filter text length.
PROFILE_NAME_MAX = 50
MAX_PROFILES_PER_USER = 5
MAX_FILTERS_PER_PROFILE = 10


class FilterProfileBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=PROFILE_NAME_MAX)


class FilterProfileCreate(FilterProfileBase):
    pass


class FilterProfileUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=PROFILE_NAME_MAX)


class FilterProfileOut(FilterProfileBase):
    id: str
    user_id: str
    position: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FilterProfileWithFilters(FilterProfileOut):
    filters: list[FilterOut] = Field(default_factory=list)


class ReorderRequest(BaseModel):
    """Bulk reorder for either profiles or filters within a profile."""

    ids: list[str] = Field(..., min_length=1)
