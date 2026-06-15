"""DOM-extraction diagnostics (Measure 3).

Receives telemetry from the extension when its LinkedIn scraper fails or comes
back partial, runs a diagnostic LLM analysis, and logs both to `llm_calls` so we
can triage breakage in /admin and ship a selector fix fast.

Cost control:
  - The extension sends at most one diagnostic per browser session.
  - This service adds a server-side backstop: a per-user rolling-24h cap.
  - It never touches the user's evaluation quota.

Best-effort: any LLM failure is logged as an error row and swallowed. The router
always returns 204 — the client doesn't use the analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db.client import SupabaseDB
from app.llm.base import LLMProvider
from app.schemas.diagnostics import DomDiagnosticsRequest
from app.services.llm_calls import LLMCallLogger, LLMCallTimer, build_prompt_payload

logger = logging.getLogger(__name__)

# LinkedIn is the only scraped source today. Stored on the log row so the admin
# UI can group diagnostics by source alongside evaluations.
_DIAGNOSTICS_SOURCE = "linkedin"


@dataclass
class DiagnosticsService:
    db: SupabaseDB
    provider: LLMProvider
    settings: Settings

    async def record(self, *, user_id: str, request: DomDiagnosticsRequest) -> None:
        if self._over_daily_cap(user_id):
            # Silently drop — we already have plenty of signal for this user
            # today, and diagnostics must never cost more than they're worth.
            logger.info("dom diagnostics daily cap hit for user=%s — dropping", user_id)
            return

        telemetry = request.model_dump()
        prompt = build_prompt_payload(
            provider_name=self.provider.name,
            call_type="dom_diagnostics",
            diagnostics=telemetry,
        )
        timer = LLMCallTimer.start()
        llm_logger = LLMCallLogger(self.db, self.settings)
        summary = _summarize(request)

        try:
            result, token_usage = await self.provider.diagnose_extraction(telemetry)
        except Exception as exc:  # best-effort — log and move on
            llm_logger.log(
                user_id=user_id,
                call_type="dom_diagnostics",
                provider=self.provider,
                status="error",
                prompt=prompt,
                error=str(exc),
                duration_ms=timer.elapsed_ms(),
                source=_DIAGNOSTICS_SOURCE,
                external_id=request.job_id,
                summary=summary,
            )
            logger.exception("dom diagnostics LLM call failed for user=%s", user_id)
            return

        llm_logger.log(
            user_id=user_id,
            call_type="dom_diagnostics",
            provider=self.provider,
            status="success",
            prompt=prompt,
            response=result.model_dump(mode="json"),
            token_usage=token_usage,
            duration_ms=timer.elapsed_ms(),
            source=_DIAGNOSTICS_SOURCE,
            external_id=request.job_id,
            summary=summary,
        )

    def _over_daily_cap(self, user_id: str) -> bool:
        cap = self.settings.dom_diagnostics_daily_cap_per_user
        if cap <= 0:
            return False
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        resp = (
            self.db.table("llm_calls")
            .select("id")
            .eq("user_id", user_id)
            .eq("call_type", "dom_diagnostics")
            .gte("created_at", cutoff)
            .execute()
        )
        return len(resp.data or []) >= cap


def _summarize(request: DomDiagnosticsRequest) -> str:
    missing = ", ".join(request.missing) if request.missing else "none"
    return f"DOM {request.outcome}: {missing} missing ({request.extractor})"
