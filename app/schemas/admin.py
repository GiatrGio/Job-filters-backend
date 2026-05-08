from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Plan = Literal["free", "pro"]


class AdminUserOut(BaseModel):
    id: str
    email: str | None = None
    plan: Plan
    evaluations_used: int
    monthly_eval_limit: int
    cv_tailorings_used: int
    monthly_cv_tailoring_limit: int
    usage_period: str
    created_at: str | None = None
    last_sign_in_at: str | None = None


class AdminUserPlanUpdate(BaseModel):
    plan: Plan
