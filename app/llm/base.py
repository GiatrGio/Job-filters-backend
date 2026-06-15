from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.diagnostics import DomDiagnosticsResult
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage
from app.schemas.filter import FilterValidationResult


class LLMProvider(ABC):
    """Abstract interface for any LLM used for job evaluation.

    All providers take the same (job, filters) pair and must return:
      - one EvaluationResult per input filter, in the same order
      - a TokenUsage record (zeros are acceptable if not reported)
    """

    name: str
    model: str

    @abstractmethod
    async def evaluate(
        self,
        job: JobInput,
        filters: list[FilterInput],
    ) -> tuple[list[EvaluationResult], TokenUsage]:
        raise NotImplementedError

    @abstractmethod
    async def validate_filter(
        self,
        text: str,
    ) -> tuple[FilterValidationResult, TokenUsage]:
        """Classify a single user-supplied filter as good / vague / rejected.

        Used by POST /filters/validate to give users immediate feedback
        when they add a new filter — see app/llm/prompts.py for the exact
        bucket definitions. Cheap call: one filter text in, no job
        description, no other filters. TokenUsage helps observability but
        is not used by the quota service (which counts calls, not tokens).
        """
        raise NotImplementedError

    @abstractmethod
    async def diagnose_extraction(
        self,
        telemetry: dict[str, Any],
    ) -> tuple[DomDiagnosticsResult, TokenUsage]:
        """Diagnose a failed/partial LinkedIn DOM extraction from telemetry.

        Used by POST /diagnostics/dom (Measure 3). The input is the extension's
        telemetry payload (which selectors matched/missed, extractor version,
        URL, page <title>) — NOT page HTML and no personal data. Returns a
        structured triage that surfaces in /admin so we can ship a selector fix
        fast. Does not touch the user's evaluation quota.
        """
        raise NotImplementedError
