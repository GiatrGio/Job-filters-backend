from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.deps import CurrentUserDep, DBDep, OptionalCurrentUserDep, SettingsDep
from app.schemas.auth_handoff import (
    WebHandoffCreate,
    WebHandoffCreateOut,
    WebHandoffExchange,
    WebHandoffExchangeOut,
)
from app.services.auth_handoff import (
    AuthHandoffAccountMismatch,
    AuthHandoffInvalid,
    AuthHandoffService,
    AuthHandoffSessionError,
    SupabaseAuthSessionGateway,
)

router = APIRouter(prefix="/auth/web-handoffs", tags=["auth"])
NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def get_auth_handoff_service(db: DBDep, settings: SettingsDep) -> AuthHandoffService:
    return AuthHandoffService(db, settings, SupabaseAuthSessionGateway(db))


AuthHandoffServiceDep = Annotated[AuthHandoffService, Depends(get_auth_handoff_service)]


@router.post("", response_model=WebHandoffCreateOut, status_code=status.HTTP_201_CREATED)
def create_web_handoff(
    body: WebHandoffCreate,
    user: CurrentUserDep,
    service: AuthHandoffServiceDep,
    response: Response,
) -> WebHandoffCreateOut:
    response.headers["Cache-Control"] = "no-store"
    created = service.create(user_id=user.id, destination=body.destination)
    return WebHandoffCreateOut(url=created.url, expires_in=created.expires_in)


@router.post("/exchange", response_model=WebHandoffExchangeOut)
def exchange_web_handoff(
    body: WebHandoffExchange,
    website_user: OptionalCurrentUserDep,
    service: AuthHandoffServiceDep,
    response: Response,
) -> WebHandoffExchangeOut:
    response.headers["Cache-Control"] = "no-store"
    try:
        exchanged = service.exchange(
            ticket=body.ticket,
            website_user_id=website_user.id if website_user else None,
        )
    except AuthHandoffAccountMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "auth_handoff_account_mismatch"},
            headers=NO_STORE_HEADERS,
        ) from exc
    except AuthHandoffInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error": "auth_handoff_invalid"},
            headers=NO_STORE_HEADERS,
        ) from exc
    except AuthHandoffSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "auth_handoff_session_failed"},
            headers=NO_STORE_HEADERS,
        ) from exc

    return WebHandoffExchangeOut(
        user_id=exchanged.user_id,
        destination=exchanged.destination,
        token_hash=exchanged.token_hash,
    )
