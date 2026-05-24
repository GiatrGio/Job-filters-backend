from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.deps import CurrentUserDep, DBDep, SettingsDep
from app.schemas.admin import (
    AdminDeleteOut,
    AdminLLMCallDetailOut,
    AdminLLMCallOut,
    AdminLLMPricingOut,
    AdminUserOut,
    AdminUserPlanUpdate,
    LLMCallRange,
)
from app.services.admin import (
    AdminService,
    StripeSubscriptionAdminGateway,
    SupabaseAuthAdminGateway,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_access(request: Request, user: CurrentUserDep, settings: SettingsDep) -> None:
    client_host = request.client.host if request.client else ""
    if _is_loopback(client_host):
        return

    if user.email.lower() in settings.admin_email_set:
        return

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def get_admin_service(db: DBDep, settings: SettingsDep) -> AdminService:
    return AdminService(
        db=db,
        settings=settings,
        auth_admin=SupabaseAuthAdminGateway(settings),
        stripe_subscriptions=(
            StripeSubscriptionAdminGateway(settings) if settings.stripe_secret_key else None
        ),
    )


AdminAccessDep = Annotated[None, Depends(require_admin_access)]
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]
LLMRangeQuery = Annotated[LLMCallRange, Query(alias="range")]
OlderThanQuery = Annotated[LLMCallRange, Query()]


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> list[AdminUserOut]:
    return [AdminUserOut(**row) for row in svc.list_users()]


@router.post("/users/refresh", response_model=list[AdminUserOut])
def refresh_users(
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> list[AdminUserOut]:
    return [AdminUserOut(**row) for row in svc.refresh_users()]


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user_plan(
    user_id: str,
    body: AdminUserPlanUpdate,
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> AdminUserOut:
    return AdminUserOut(**svc.update_plan(user_id, body.plan))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    _admin_access: AdminAccessDep,
    user: CurrentUserDep,
    svc: AdminServiceDep,
) -> Response:
    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the signed-in admin user",
        )
    svc.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/llm-calls", response_model=list[AdminLLMCallOut])
def list_llm_calls(
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
    range_key: LLMRangeQuery = "24h",
) -> list[AdminLLMCallOut]:
    return [AdminLLMCallOut(**row) for row in svc.list_llm_calls(range_key)]


@router.delete("/llm-calls", response_model=AdminDeleteOut)
def delete_old_llm_calls(
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
    older_than: OlderThanQuery,
) -> AdminDeleteOut:
    return AdminDeleteOut(deleted_count=svc.delete_llm_calls_older_than(older_than))


@router.get("/llm-pricing", response_model=AdminLLMPricingOut)
def get_llm_pricing(
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> AdminLLMPricingOut:
    return AdminLLMPricingOut(**svc.get_llm_pricing())


@router.get("/llm-calls/{call_id}", response_model=AdminLLMCallDetailOut)
def get_llm_call(
    call_id: str,
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> AdminLLMCallDetailOut:
    call = svc.get_llm_call(call_id)
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM call not found")
    return AdminLLMCallDetailOut(**call)


@router.delete("/llm-calls/{call_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_llm_call(
    call_id: str,
    _admin_access: AdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> Response:
    if not svc.delete_llm_call(call_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM call not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _is_loopback(host: str) -> bool:
    if host in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
