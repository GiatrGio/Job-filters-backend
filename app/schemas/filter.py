from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.schemas.evaluate import UsageOut

# Caps mirror the DB check constraints; pydantic enforces them earlier so the
# user gets a 422 with a readable message instead of a 500 from a constraint
# violation.
FILTER_TEXT_MAX = 200


class FilterKind(str, Enum):
    """Two shapes of filter the system understands.

    - criterion: boolean question over the description (incl. yes/no
      questions like "Is the salary over €6,500?"). Evaluator produces
      pass ∈ {true,false,null} with a short quote.
    - question: open-ended info extraction ("What languages are required?",
      "List the main skills"). Evaluator produces pass=null with a
      concise answer in evidence.
    """

    criterion = "criterion"
    question = "question"


class FilterBase(BaseModel):
    text: str = Field(..., min_length=1, max_length=FILTER_TEXT_MAX)
    position: int = 0
    enabled: bool = True
    # Default at the schema level matches the DB default in migration 0006,
    # so older clients that don't send `kind` keep working as criterion.
    kind: FilterKind = FilterKind.criterion


class FilterCreate(FilterBase):
    pass


class FilterUpdate(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=FILTER_TEXT_MAX)
    position: int | None = None
    enabled: bool | None = None
    kind: FilterKind | None = None


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


MAX_SUGGESTED_FILTERS = 3


class SuggestedFilter(BaseModel):
    """A ready-to-save rewrite the validator offers for a vague filter.

    The UI adds it with one click and does NOT validate it again (the
    validator wrote it), so it has to be saveable as-is and carries its own
    kind.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(..., min_length=1, max_length=FILTER_TEXT_MAX)
    kind: FilterKind = FilterKind.criterion


class FilterValidationResult(BaseModel):
    verdict: FilterValidationVerdict
    reason: str
    # Short tip on how to make a vague filter specific. The concrete
    # rewrites live in `suggested_filters` so the UI can make them clickable.
    suggestion: str | None = None
    suggested_filters: list[SuggestedFilter] = Field(default_factory=list)
    # The validator classifies kind alongside verdict so the frontend can
    # store it on the filter row without a second round-trip. Always
    # populated, even when verdict is "vague" or "rejected" (handy for
    # save-anyway flows).
    kind: FilterKind = FilterKind.criterion

    @field_validator("suggested_filters", mode="before")
    @classmethod
    def _drop_unsaveable_suggestions(cls, value: object) -> list[SuggestedFilter]:
        # One malformed rewrite (too long, blank, bad kind) is dropped rather
        # than failing the whole check, which would 502 the user's save.
        if not isinstance(value, list):
            return []
        kept: list[SuggestedFilter] = []
        seen: set[str] = set()
        for item in value:
            try:
                suggestion = SuggestedFilter.model_validate(item)
            except ValidationError:
                continue
            if suggestion.text.lower() in seen:
                continue
            seen.add(suggestion.text.lower())
            kept.append(suggestion)
        return kept[:MAX_SUGGESTED_FILTERS]


class FilterValidationResponse(FilterValidationResult):
    # Echo the user's filter-validation usage so the UI can show "X/Y this
    # month" without a separate /me round-trip.
    usage: UsageOut
