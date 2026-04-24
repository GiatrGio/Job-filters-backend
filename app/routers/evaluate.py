from __future__ import annotations

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.deps import CurrentUserDep, EvaluateLimiterDep, EvaluatorDep
from app.schemas.evaluate import EvaluateRequest, EvaluateResponse, UsageOut
from app.services.evaluator import QuotaExceeded

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evaluate"])


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    responses={
        402: {"description": "Quota exceeded"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Upstream LLM provider failed"},
    },
)
async def evaluate(
    body: EvaluateRequest,
    user: CurrentUserDep,
    evaluator: EvaluatorDep,
    limiter: EvaluateLimiterDep,
) -> EvaluateResponse | JSONResponse:
    if not limiter.try_acquire(user.id):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": "rate_limited"},
            headers={"Retry-After": "1"},
        )
    try:
        return await evaluator.evaluate(user_id=user.id, job=body)
    except QuotaExceeded as exc:
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": "quota_exceeded",
                "usage": UsageOut(
                    used=exc.status.used,
                    limit=exc.status.limit,
                    period=exc.status.period,
                ).model_dump(),
            },
        )
    except Exception as exc:
        # Upstream LLM failure (credits, rate limit, auth, network, …) or an
        # unexpected bug in our own code. We always return 502 with a readable
        # message so the extension can show the user something useful instead
        # of a generic 500 with no body.
        logger.exception("evaluation failed for user=%s job=%s", user.id, body.linkedin_job_id)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "evaluation_failed", "detail": str(exc)},
        )
