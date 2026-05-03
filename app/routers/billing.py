from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.deps import CurrentUserDep, DBDep, SettingsDep
from app.schemas.billing import BillingSessionOut
from app.services.billing import BillingService, StripeGateway, verify_stripe_signature

router = APIRouter(prefix="/billing", tags=["billing"])


def get_billing_service(db: DBDep, settings: SettingsDep) -> BillingService:
    return BillingService(
        db=db,
        settings=settings,
        gateway=StripeGateway(settings.stripe_secret_key),
    )


BillingServiceDep = Annotated[BillingService, Depends(get_billing_service)]


@router.post("/checkout-session", response_model=BillingSessionOut)
def create_checkout_session(user: CurrentUserDep, svc: BillingServiceDep) -> BillingSessionOut:
    return BillingSessionOut(url=svc.create_checkout_session(user_id=user.id, email=user.email))


@router.post("/portal-session", response_model=BillingSessionOut)
def create_portal_session(user: CurrentUserDep, svc: BillingServiceDep) -> BillingSessionOut:
    return BillingSessionOut(url=svc.create_portal_session(user_id=user.id))


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    svc: BillingServiceDep,
    settings: SettingsDep,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, bool]:
    payload = await request.body()
    event = verify_stripe_signature(
        payload=payload,
        signature_header=stripe_signature,
        webhook_secret=settings.stripe_webhook_secret,
    )
    svc.handle_event(event)
    return {"received": True}
