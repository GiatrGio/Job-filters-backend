"""POST /diagnostics/dom — DOM-extraction telemetry sink (Measure 3).

The extension calls this when its LinkedIn scraper fails or comes back partial.
The body is telemetry only (no page content, no personal data — see
app/schemas/diagnostics.py). We run a diagnostic LLM analysis and log both to
`llm_calls` so we can triage breakage in /admin.

Always returns 204: diagnostics are best-effort and the client doesn't use the
analysis. Rate-limited per user (shares the /evaluate bucket) and capped per
user/day in the service. Never touches the user's evaluation quota.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.deps import CurrentUserDep, DiagnosticsServiceDep, EvaluateLimiterDep
from app.schemas.diagnostics import DomDiagnosticsRequest

router = APIRouter(tags=["diagnostics"])


@router.post(
    "/diagnostics/dom",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={429: {"description": "Rate limit exceeded"}},
)
async def submit_dom_diagnostics(
    body: DomDiagnosticsRequest,
    user: CurrentUserDep,
    svc: DiagnosticsServiceDep,
    limiter: EvaluateLimiterDep,
) -> Response:
    if not limiter.try_acquire(user.id):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": "rate_limited"},
            headers={"Retry-After": "1"},
        )
    await svc.record(user_id=user.id, request=body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
