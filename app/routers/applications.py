"""Application tracker endpoints.

Used by both the extension ("Track this job" button) and the website
(dashboard, manual add, status changes). The extension's flow is
idempotent: POST /applications with the same (source, external_id) twice
returns the existing row instead of creating a duplicate.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.deps import CurrentUserDep, DBDep
from app.schemas.application import (
    ApplicationCreate,
    ApplicationListItem,
    ApplicationOut,
    ApplicationUpdate,
)
from app.services.applications import ApplicationsService

router = APIRouter(prefix="/applications", tags=["applications"])


def get_applications_service(db: DBDep) -> ApplicationsService:
    return ApplicationsService(db)


ApplicationsServiceDep = Annotated[
    ApplicationsService, Depends(get_applications_service)
]


@router.get("", response_model=list[ApplicationListItem])
def list_applications(
    user: CurrentUserDep,
    svc: ApplicationsServiceDep,
) -> list[ApplicationListItem]:
    rows = svc.list_for_user(user.id)
    return [ApplicationListItem.model_validate(r) for r in rows]


@router.post("", response_model=ApplicationOut)
def create_application(
    body: ApplicationCreate,
    user: CurrentUserDep,
    svc: ApplicationsServiceDep,
    response: Response,
) -> ApplicationOut:
    row, created = svc.create_or_get(user.id, body)
    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return ApplicationOut.model_validate(row)


@router.get("/by-job/{source}/{external_id}", response_model=ApplicationOut)
def get_application_by_job(
    source: str,
    external_id: str,
    user: CurrentUserDep,
    svc: ApplicationsServiceDep,
) -> ApplicationOut:
    row = svc.get_by_job(user.id, source, external_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not tracked")
    return ApplicationOut.model_validate(row)


@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: str,
    user: CurrentUserDep,
    svc: ApplicationsServiceDep,
) -> ApplicationOut:
    row = svc.get(user.id, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return ApplicationOut.model_validate(row)


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: str,
    body: ApplicationUpdate,
    user: CurrentUserDep,
    svc: ApplicationsServiceDep,
) -> ApplicationOut:
    row = svc.update(user.id, application_id, body)
    if row is None:
        raise HTTPException(status_code=404, detail="application not found")
    return ApplicationOut.model_validate(row)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: str,
    user: CurrentUserDep,
    svc: ApplicationsServiceDep,
) -> None:
    deleted = svc.delete(user.id, application_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="application not found")
    return None
