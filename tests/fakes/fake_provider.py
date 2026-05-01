from __future__ import annotations

from app.llm.base import LLMProvider
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage
from app.schemas.filter import FilterValidationResult, FilterValidationVerdict


class FakeLLMProvider(LLMProvider):
    """Deterministic provider for tests.

    Returns `pass=True` for every filter whose lowercased text appears in the
    job description, `False` for every filter whose text starts with "must not",
    and `None` otherwise. Records how many times `evaluate` was called.

    `validate_filter` keys off prefixes in the filter text so each verdict
    has a stable trigger:
      - text contains "[vague]"     → vague
      - text contains "[rejected]"  → rejected
      - anything else               → good
    """

    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0
        self.validation_calls = 0

    async def evaluate(
        self,
        job: JobInput,
        filters: list[FilterInput],
    ) -> tuple[list[EvaluationResult], TokenUsage]:
        self.calls += 1
        description_lc = job.job_description.lower()
        results: list[EvaluationResult] = []
        for f in filters:
            text_lc = f.text.lower()
            if text_lc.startswith("must not") and text_lc[9:].strip() in description_lc:
                pass_val: bool | None = False
                evidence = "mentioned in description"
            elif text_lc in description_lc:
                pass_val = True
                evidence = "matched literal substring"
            else:
                pass_val = None
                evidence = "not mentioned"
            results.append(
                EvaluationResult.model_validate(
                    {"filter": f.text, "pass": pass_val, "evidence": evidence}
                )
            )
        return results, TokenUsage(input_tokens=1, output_tokens=1)

    async def validate_filter(
        self,
        text: str,
    ) -> tuple[FilterValidationResult, TokenUsage]:
        self.validation_calls += 1
        lower = text.lower()
        if "[rejected]" in lower:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.rejected,
                reason="not a job-posting filter",
                suggestion=None,
            )
        elif "[vague]" in lower:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.vague,
                reason="too subjective to evaluate",
                suggestion="Try a measurable criterion instead.",
            )
        else:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.good,
                reason="clear and decidable",
                suggestion=None,
            )
        return result, TokenUsage(input_tokens=1, output_tokens=1)
