from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.deps import CurrentUserDep, DBDep, QuotaDep, SettingsDep
from app.schemas.evaluate import UsageOut
from app.schemas.user import MeResponse
from app.services.account import AccountService
from app.services.admin import SupabaseAuthAdminGateway
from app.services.billing import StripeGateway

router = APIRouter(tags=["me"])


def get_account_service(db: DBDep, settings: SettingsDep) -> AccountService:
    return AccountService(
        db=db,
        auth_admin=SupabaseAuthAdminGateway(settings),
        billing=(
            StripeGateway(settings.stripe_secret_key) if settings.stripe_secret_key else None
        ),
    )


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUserDep, db: DBDep, quota: QuotaDep) -> MeResponse:
    plan_resp = (
        db.table("profiles").select("plan").eq("id", user.id).limit(1).execute()
    )
    plan_rows = plan_resp.data or []
    plan = plan_rows[0]["plan"] if plan_rows else "free"

    status = quota.status(user.id)
    cover_letters = quota.cover_letter_status(user.id)
    return MeResponse(
        email=user.email,
        plan=plan,
        usage=UsageOut(
            used=status.used,
            limit=status.limit,
            period=status.period,
            warning_threshold=status.warning_threshold,
        ),
        cover_letters=UsageOut(
            used=cover_letters.used,
            limit=cover_letters.limit,
            period=cover_letters.period,
            warning_threshold=cover_letters.warning_threshold,
        ),
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: CurrentUserDep, svc: AccountServiceDep) -> Response:
    """Delete the caller's own account and every row that belongs to it.

    The id comes from the verified token, never the path, so this cannot be
    pointed at another account. Irreversible — the client is responsible for
    confirming intent before calling it.
    """
    svc.delete_account(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
