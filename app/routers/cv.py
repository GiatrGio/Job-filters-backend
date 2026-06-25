"""CV upload / fetch / delete for the job-fit feature.

POST /cv     — multipart file upload (PDF / DOCX / TXT). Extracts text in memory,
               runs the CV-parse LLM call, stores ONLY the non-PII profile.
GET  /cv     — the current parsed profile, or null (200) when none uploaded.
DELETE /cv   — remove the profile and any fit results derived from it.

The raw file/text is never persisted and is redacted from the llm_calls log.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.deps import CurrentUserDep, CvServiceDep, EvaluateLimiterDep
from app.schemas.cv import CvProfile, CvProfileResponse
from app.services.cv_extract import (
    CvExtractionError,
    CvFileTooLarge,
    extract_cv_text,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cv"])


@router.post(
    "/cv",
    response_model=CvProfileResponse,
    responses={
        400: {"description": "Unreadable or unsupported CV file"},
        413: {"description": "CV file too large"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream LLM provider failed"},
    },
)
async def upload_cv(
    user: CurrentUserDep,
    svc: CvServiceDep,
    limiter: EvaluateLimiterDep,
    file: Annotated[UploadFile, File()],
) -> CvProfileResponse | JSONResponse:
    if not limiter.try_acquire(user.id):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": "rate_limited"},
            headers={"Retry-After": "1"},
        )

    data = await file.read()
    try:
        text = extract_cv_text(
            data=data, filename=file.filename, content_type=file.content_type
        )
    except CvFileTooLarge as exc:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"error": "cv_too_large", "detail": str(exc)},
        )
    except CvExtractionError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "cv_unreadable", "detail": str(exc)},
        )

    try:
        return await svc.parse_and_store(user_id=user.id, cv_text=text)
    except Exception as exc:
        logger.exception("CV parse failed for user=%s", user.id)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "cv_parse_failed", "detail": str(exc)},
        )


@router.get("/cv", response_model=CvProfileResponse | None)
async def get_cv(user: CurrentUserDep, svc: CvServiceDep) -> CvProfileResponse | None:
    # 200 + null when the user has no CV yet — mirrors GET /applications/by-job.
    return svc.get_response(user.id)


@router.put("/cv", response_model=CvProfileResponse)
async def update_cv(
    body: CvProfile,
    user: CurrentUserDep,
    svc: CvServiceDep,
) -> CvProfileResponse:
    # User-edited profile (e.g. added a skill, fixed seniority). No LLM call;
    # changing the profile re-hashes it, which invalidates cached fit results.
    return svc.update_profile(user_id=user.id, profile=body)


@router.delete("/cv", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cv(user: CurrentUserDep, svc: CvServiceDep) -> Response:
    svc.delete(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
