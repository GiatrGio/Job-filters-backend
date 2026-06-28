"""Cover-letter settings, instructions validation, and on-demand generation.

GET  /cover-letter/settings                       — instructions + identity block
PUT  /cover-letter/settings                       — upsert the above
POST /cover-letter/settings/validate-instructions — quality check (good/vague/
     rejected), mirrors /filters/validate and shares the filter-validation meter
POST /generate-cover-letter                       — generate a letter for a job

Generation consumes the monthly cover-letter quota (free 1 / pro 25) and returns
the letter prose; the extension renders the PDF and caches the text client-side.
The letter is never stored server-side.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.deps import (
    CoverLetterServiceDep,
    CurrentUserDep,
    DBDep,
    EvaluateLimiterDep,
    LLMProviderDep,
    QuotaDep,
    SettingsDep,
)
from app.schemas.cover_letter import (
    CoverLetterInstructionsValidationRequest,
    CoverLetterInstructionsValidationResponse,
    CoverLetterSettings,
    CoverLetterSettingsResponse,
    GenerateCoverLetterRequest,
    GenerateCoverLetterResponse,
)
from app.schemas.evaluate import UsageOut
from app.services.evaluator import QuotaExceeded
from app.services.llm_calls import LLMCallLogger, LLMCallTimer, build_prompt_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cover_letter"])


@router.get("/cover-letter/settings", response_model=CoverLetterSettingsResponse)
def get_cover_letter_settings(
    user: CurrentUserDep, svc: CoverLetterServiceDep
) -> CoverLetterSettingsResponse:
    return svc.get_settings(user.id)


@router.put("/cover-letter/settings", response_model=CoverLetterSettingsResponse)
def update_cover_letter_settings(
    body: CoverLetterSettings,
    user: CurrentUserDep,
    svc: CoverLetterServiceDep,
) -> CoverLetterSettingsResponse:
    return svc.upsert_settings(user_id=user.id, settings=body)


@router.post(
    "/cover-letter/settings/validate-instructions",
    response_model=CoverLetterInstructionsValidationResponse,
    responses={
        402: {"description": "Validation quota exceeded"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream LLM provider failed"},
    },
)
async def validate_cover_letter_instructions(
    body: CoverLetterInstructionsValidationRequest,
    user: CurrentUserDep,
    provider: LLMProviderDep,
    quota: QuotaDep,
    limiter: EvaluateLimiterDep,
    db: DBDep,
    settings: SettingsDep,
) -> CoverLetterInstructionsValidationResponse | JSONResponse:
    # Shares the filter-validation monthly meter — both are tiny one-shot checks
    # and the same per-user cap bounds abuse from either.
    if not limiter.try_acquire(user.id):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": "rate_limited"},
            headers={"Retry-After": "1"},
        )

    pre_status = quota.filter_validation_status(user.id)
    if pre_status.exceeded:
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": "filter_validation_quota_exceeded",
                "usage": UsageOut(
                    used=pre_status.used,
                    limit=pre_status.limit,
                    period=pre_status.period,
                    warning_threshold=pre_status.warning_threshold,
                ).model_dump(),
            },
        )

    prompt = build_prompt_payload(
        provider_name=provider.name,
        call_type="cover_letter_validation",
        instructions=body.text,
    )
    timer = LLMCallTimer.start()
    llm_logger = LLMCallLogger(db, settings)
    try:
        result, _tokens = await provider.validate_cover_letter_instructions(body.text)
    except Exception as exc:
        llm_logger.log(
            user_id=user.id,
            call_type="cover_letter_validation",
            provider=provider,
            status="error",
            prompt=prompt,
            error=str(exc),
            duration_ms=timer.elapsed_ms(),
            summary=body.text[:120],
        )
        logger.exception("cover-letter instructions validation failed user=%s", user.id)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "cover_letter_validation_failed", "detail": str(exc)},
        )

    llm_logger.log(
        user_id=user.id,
        call_type="cover_letter_validation",
        provider=provider,
        status="success",
        prompt=prompt,
        response=result.model_dump(mode="json"),
        token_usage=_tokens,
        duration_ms=timer.elapsed_ms(),
        summary=body.text[:120],
    )

    post_status = quota.increment_filter_validation(user.id)

    return CoverLetterInstructionsValidationResponse(
        verdict=result.verdict,
        reason=result.reason,
        suggestion=result.suggestion,
        usage=UsageOut(
            used=post_status.used,
            limit=post_status.limit,
            period=post_status.period,
            warning_threshold=post_status.warning_threshold,
        ),
    )


@router.post(
    "/generate-cover-letter",
    response_model=GenerateCoverLetterResponse,
    responses={
        402: {"description": "Cover-letter quota exceeded"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream LLM provider failed"},
    },
)
async def generate_cover_letter(
    body: GenerateCoverLetterRequest,
    user: CurrentUserDep,
    svc: CoverLetterServiceDep,
    limiter: EvaluateLimiterDep,
) -> GenerateCoverLetterResponse | JSONResponse:
    if not limiter.try_acquire(user.id):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": "rate_limited"},
            headers={"Retry-After": "1"},
        )
    try:
        return await svc.generate(user_id=user.id, job=body)
    except QuotaExceeded as exc:
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": "quota_exceeded",
                "plan": exc.status.plan,
                "usage": UsageOut(
                    used=exc.status.used,
                    limit=exc.status.limit,
                    period=exc.status.period,
                    warning_threshold=exc.status.warning_threshold,
                ).model_dump(),
            },
        )
    except Exception as exc:
        logger.exception(
            "cover-letter generation failed for user=%s source=%s job=%s",
            user.id, body.source, body.job_id,
        )
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "cover_letter_failed", "detail": str(exc)},
        )
