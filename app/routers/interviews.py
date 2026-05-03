"""Per-application interview rounds endpoints.

Nested under /applications/{application_id}/interviews for list+create. The
future `/interviews/upcoming` endpoint will sit alongside the per-row routes
to power the Calendar view; not implemented yet.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUserDep, DBDep
from app.schemas.interview import (
    ApplicationInterviewCreate,
    ApplicationInterviewOut,
    ApplicationInterviewUpdate,
)
from app.services.applications import ApplicationsService
from app.services.interviews import InterviewsService

router = APIRouter(tags=["interviews"])


def get_interviews_service(db: DBDep) -> InterviewsService:
    return InterviewsService(db)


def get_applications_service(db: DBDep) -> ApplicationsService:
    return ApplicationsService(db)


InterviewsServiceDep = Annotated[InterviewsService, Depends(get_interviews_service)]
ApplicationsServiceDep = Annotated[
    ApplicationsService, Depends(get_applications_service)
]


def _ensure_application(svc: ApplicationsService, user_id: str, application_id: str) -> None:
    if svc.get(user_id, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")


@router.get(
    "/applications/{application_id}/interviews",
    response_model=list[ApplicationInterviewOut],
)
def list_interviews(
    application_id: str,
    user: CurrentUserDep,
    interviews: InterviewsServiceDep,
    apps: ApplicationsServiceDep,
) -> list[ApplicationInterviewOut]:
    _ensure_application(apps, user.id, application_id)
    rows = interviews.list_for_application(user.id, application_id)
    return [ApplicationInterviewOut.model_validate(r) for r in rows]


@router.post(
    "/applications/{application_id}/interviews",
    response_model=ApplicationInterviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_interview(
    application_id: str,
    body: ApplicationInterviewCreate,
    user: CurrentUserDep,
    interviews: InterviewsServiceDep,
    apps: ApplicationsServiceDep,
) -> ApplicationInterviewOut:
    _ensure_application(apps, user.id, application_id)
    row = interviews.create(user.id, application_id, body)
    return ApplicationInterviewOut.model_validate(row)


@router.patch("/interviews/{interview_id}", response_model=ApplicationInterviewOut)
def update_interview(
    interview_id: str,
    body: ApplicationInterviewUpdate,
    user: CurrentUserDep,
    interviews: InterviewsServiceDep,
) -> ApplicationInterviewOut:
    row = interviews.update(user.id, interview_id, body)
    if row is None:
        raise HTTPException(status_code=404, detail="interview not found")
    return ApplicationInterviewOut.model_validate(row)


@router.delete("/interviews/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview(
    interview_id: str,
    user: CurrentUserDep,
    interviews: InterviewsServiceDep,
) -> None:
    deleted = interviews.delete(user.id, interview_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="interview not found")
    return None
