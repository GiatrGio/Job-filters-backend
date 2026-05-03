from __future__ import annotations

from pydantic import BaseModel, HttpUrl


class BillingSessionOut(BaseModel):
    url: HttpUrl


class BillingProfileOut(BaseModel):
    plan: str
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_subscription_status: str | None = None
    stripe_cancel_at_period_end: bool = False
