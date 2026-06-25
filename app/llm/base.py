from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.cv import CvProfile
from app.schemas.diagnostics import DomDiagnosticsResult
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage
from app.schemas.filter import FilterValidationResult
from app.schemas.fit import JobFitResult


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

    @abstractmethod
    async def parse_cv(
        self,
        cv_text: str,
    ) -> tuple[CvProfile, TokenUsage]:
        """Parse raw CV text into a structured, NON-IDENTIFYING profile.

        Used by POST /cv (job-fit feature). The model is instructed to emit only
        professional signal (skills, years, seniority, titles, domains,
        education level, languages, a short summary) and never a name, contact
        detail, employer, or school — see app/llm/prompts.py. We persist only
        the returned CvProfile; the CV text is discarded and is redacted from
        the llm_calls log.
        """
        raise NotImplementedError

    @abstractmethod
    async def evaluate_fit(
        self,
        job: JobInput,
        cv: CvProfile,
    ) -> tuple[JobFitResult, TokenUsage]:
        """Judge how well a candidate profile fits a single job posting.

        Used by POST /evaluate-fit. Separate from `evaluate` (filters) so the
        two are cached and rendered independently. Returns an overall 1–5 score
        plus skills/experience/domain sub-scores and strengths/gaps.
        """
        raise NotImplementedError
