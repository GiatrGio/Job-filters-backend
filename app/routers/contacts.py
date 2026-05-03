"""Per-application contacts endpoints.

Nested under /applications/{application_id}/contacts for list+create. Per-row
update and delete live at /contacts/{id} so callers don't have to repeat the
application id (the contact is already scoped to the user via RLS / the
service-level `user_id` filter).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUserDep, DBDep
from app.schemas.contact import (
    ApplicationContactCreate,
    ApplicationContactOut,
    ApplicationContactUpdate,
)
from app.services.applications import ApplicationsService
from app.services.contacts import ContactsService

router = APIRouter(tags=["contacts"])


def get_contacts_service(db: DBDep) -> ContactsService:
    return ContactsService(db)


def get_applications_service(db: DBDep) -> ApplicationsService:
    return ApplicationsService(db)


ContactsServiceDep = Annotated[ContactsService, Depends(get_contacts_service)]
ApplicationsServiceDep = Annotated[
    ApplicationsService, Depends(get_applications_service)
]


def _ensure_application(svc: ApplicationsService, user_id: str, application_id: str) -> None:
    if svc.get(user_id, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")


@router.get(
    "/applications/{application_id}/contacts",
    response_model=list[ApplicationContactOut],
)
def list_contacts(
    application_id: str,
    user: CurrentUserDep,
    contacts: ContactsServiceDep,
    apps: ApplicationsServiceDep,
) -> list[ApplicationContactOut]:
    _ensure_application(apps, user.id, application_id)
    rows = contacts.list_for_application(user.id, application_id)
    return [ApplicationContactOut.model_validate(r) for r in rows]


@router.post(
    "/applications/{application_id}/contacts",
    response_model=ApplicationContactOut,
    status_code=status.HTTP_201_CREATED,
)
def create_contact(
    application_id: str,
    body: ApplicationContactCreate,
    user: CurrentUserDep,
    contacts: ContactsServiceDep,
    apps: ApplicationsServiceDep,
) -> ApplicationContactOut:
    _ensure_application(apps, user.id, application_id)
    row = contacts.create(user.id, application_id, body)
    return ApplicationContactOut.model_validate(row)


@router.patch("/contacts/{contact_id}", response_model=ApplicationContactOut)
def update_contact(
    contact_id: str,
    body: ApplicationContactUpdate,
    user: CurrentUserDep,
    contacts: ContactsServiceDep,
) -> ApplicationContactOut:
    row = contacts.update(user.id, contact_id, body)
    if row is None:
        raise HTTPException(status_code=404, detail="contact not found")
    return ApplicationContactOut.model_validate(row)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(
    contact_id: str,
    user: CurrentUserDep,
    contacts: ContactsServiceDep,
) -> None:
    deleted = contacts.delete(user.id, contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="contact not found")
    return None
