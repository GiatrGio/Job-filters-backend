"""POST /filters/validate — LLM-backed quality check on a user-supplied filter.

Used by the options page when the user hits Save on a new filter. Returns
one of three verdicts so the UI can either accept silently (good), warn
but allow (vague), or block (rejected).

Quota: counts toward `filter_validations_used` on the per-(user, month)
row, separately from /evaluate. Exceeding it returns 402 — same shape as
/evaluate's 402 so the extension reuses the existing handler.

Rate limit: shares the /evaluate token bucket. Validation calls are a
fraction of an evaluation's cost and the same per-user burst protection
is plenty for typing speed.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.deps import (
    CurrentUserDep,
    EvaluateLimiterDep,
    LLMProviderDep,
    QuotaDep,
)
from app.schemas.evaluate import UsageOut
from app.schemas.filter import (
    FilterValidationRequest,
    FilterValidationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["filters"])


@router.post(
    "/filters/validate",
    response_model=FilterValidationResponse,
    responses={
        402: {"description": "Filter validation quota exceeded"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream LLM provider failed"},
    },
)
async def validate_filter(
    body: FilterValidationRequest,
    user: CurrentUserDep,
    provider: LLMProviderDep,
    quota: QuotaDep,
    limiter: EvaluateLimiterDep,
) -> FilterValidationResponse | JSONResponse:
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
                ).model_dump(),
            },
        )

    try:
        result, _tokens = await provider.validate_filter(body.text)
    except Exception as exc:
        logger.exception("filter validation failed for user=%s", user.id)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "filter_validation_failed", "detail": str(exc)},
        )

    # Increment AFTER the successful LLM call so a transient upstream
    # failure doesn't burn a slot. Two concurrent typings of the same user
    # might both succeed and both increment — that's fine, the cap is loose.
    post_status = quota.increment_filter_validation(user.id)

    return FilterValidationResponse(
        verdict=result.verdict,
        reason=result.reason,
        suggestion=result.suggestion,
        usage=UsageOut(
            used=post_status.used,
            limit=post_status.limit,
            period=post_status.period,
        ),
    )
