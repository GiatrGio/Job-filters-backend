from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.deps import CurrentUserDep, DBDep, SettingsDep
from app.schemas.admin import AdminUserOut, AdminUserPlanUpdate
from app.services.admin import AdminService, SupabaseAuthAdminGateway

router = APIRouter(prefix="/admin", tags=["admin"])


def require_local_admin_access(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if not _is_loopback(client_host):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def get_admin_service(db: DBDep, settings: SettingsDep) -> AdminService:
    return AdminService(
        db=db,
        settings=settings,
        auth_admin=SupabaseAuthAdminGateway(settings),
    )


LocalAdminAccessDep = Annotated[None, Depends(require_local_admin_access)]
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    _local_access: LocalAdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> list[AdminUserOut]:
    return [AdminUserOut(**row) for row in svc.list_users()]


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user_plan(
    user_id: str,
    body: AdminUserPlanUpdate,
    _local_access: LocalAdminAccessDep,
    _user: CurrentUserDep,
    svc: AdminServiceDep,
) -> AdminUserOut:
    return AdminUserOut(**svc.update_plan(user_id, body.plan))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    _local_access: LocalAdminAccessDep,
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


def _is_loopback(host: str) -> bool:
    if host in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
