from __future__ import annotations

from pydantic import BaseModel

from app.schemas.evaluate import UsageOut


class MeResponse(BaseModel):
    email: str
    plan: str
    usage: UsageOut


class CurrentUser(BaseModel):
    """Decoded JWT claims for the authenticated caller."""

    id: str  # auth.users.id
    email: str
