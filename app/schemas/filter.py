from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FilterBase(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    position: int = 0
    enabled: bool = True


class FilterCreate(FilterBase):
    pass


class FilterUpdate(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=500)
    position: int | None = None
    enabled: bool | None = None


class FilterOut(FilterBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
