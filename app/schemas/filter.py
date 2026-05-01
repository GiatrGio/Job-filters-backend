from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.evaluate import UsageOut

# Caps mirror the DB check constraints; pydantic enforces them earlier so the
# user gets a 422 with a readable message instead of a 500 from a constraint
# violation.
FILTER_TEXT_MAX = 200


class FilterBase(BaseModel):
    text: str = Field(..., min_length=1, max_length=FILTER_TEXT_MAX)
    position: int = 0
    enabled: bool = True


class FilterCreate(FilterBase):
    pass


class FilterUpdate(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=FILTER_TEXT_MAX)
    position: int | None = None
    enabled: bool | None = None


class FilterOut(FilterBase):
    id: str
    user_id: str
    profile_id: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Filter-quality validation (POST /filters/validate)
# ---------------------------------------------------------------------------

class FilterValidationVerdict(str, Enum):
    good = "good"
    vague = "vague"
    rejected = "rejected"


class FilterValidationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=FILTER_TEXT_MAX)


class FilterValidationResult(BaseModel):
    verdict: FilterValidationVerdict
    reason: str
    suggestion: str | None = None


class FilterValidationResponse(FilterValidationResult):
    # Echo the user's filter-validation usage so the UI can show "X/Y this
    # month" without a separate /me round-trip.
    usage: UsageOut
