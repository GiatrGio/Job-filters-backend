from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Plan = Literal["free", "pro"]
LLMCallRange = Literal["1h", "24h", "7d", "30d"]


class AdminUserOut(BaseModel):
    id: str
    email: str | None = None
    plan: Plan
    evaluations_used: int
    monthly_eval_limit: int
    cover_letters_used: int
    monthly_cover_letter_limit: int
    tracked_jobs_count: int
    tracked_jobs_limit: int
    usage_period: str
    created_at: str | None = None
    last_sign_in_at: str | None = None


class AdminUserPlanUpdate(BaseModel):
    plan: Plan


class AdminLLMCallOut(BaseModel):
    id: str
    user_email: str | None = None
    call_type: str
    provider: str
    model: str
    status: str
    source: str | None = None
    external_id: str | None = None
    summary: str | None = None
    tokens_input: int
    tokens_output: int
    cost_usd_micros: int | None = None
    duration_ms: int | None = None
    created_at: str


class AdminLLMCallDetailOut(AdminLLMCallOut):
    prompt: dict[str, Any]
    response: Any = None
    error: str | None = None


class AdminLLMPricingModelOut(BaseModel):
    provider: str
    model: str
    input_cost_usd_per_million: float
    output_cost_usd_per_million: float
    source: str


class AdminLLMPricingOut(BaseModel):
    active_provider: str
    active_model: str
    fetched_at: str
    models: list[AdminLLMPricingModelOut]


class AdminDeleteOut(BaseModel):
    deleted_count: int
