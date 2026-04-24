from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentUserDep, DBDep, QuotaDep
from app.schemas.evaluate import UsageOut
from app.schemas.user import MeResponse

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUserDep, db: DBDep, quota: QuotaDep) -> MeResponse:
    plan_resp = (
        db.table("profiles").select("plan").eq("id", user.id).limit(1).execute()
    )
    plan_rows = plan_resp.data or []
    plan = plan_rows[0]["plan"] if plan_rows else "free"

    status = quota.status(user.id)
    return MeResponse(
        email=user.email,
        plan=plan,
        usage=UsageOut(used=status.used, limit=status.limit, period=status.period),
    )
