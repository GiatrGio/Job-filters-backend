from __future__ import annotations

from app.llm.base import LLMProvider
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage
from app.schemas.filter import FilterKind, FilterValidationResult, FilterValidationVerdict


def _classify_kind(text: str) -> FilterKind:
    """Heuristic mirror of the validator's kind classification.

    Real Anthropic / OpenAI providers ask the LLM for a verdict; in tests
    we lean on shape: open-ended starters and questions that don't begin
    with a yes/no form ("Is", "Does", "Can", "Are", "Will", "Has") map to
    "question"; everything else stays "criterion". Stable enough for
    tests to assert on the kind without hitting a real model.
    """
    stripped = text.strip().lower()
    yes_no_starters = ("is ", "does ", "do ", "can ", "are ", "was ", "were ", "will ", "has ", "have ", "should ", "must ")
    if any(stripped.startswith(s) for s in yes_no_starters):
        return FilterKind.criterion
    open_starters = ("what", "which", "who", "whom", "when", "where", "why", "how", "list", "tell", "describe", "name", "extract", "find", "show", "give", "enumerate")
    first_word = stripped.split(" ", 1)[0] if stripped else ""
    if first_word in open_starters:
        return FilterKind.question
    if stripped.endswith("?"):
        # A question that didn't match a yes/no starter — assume open-ended.
        return FilterKind.question
    return FilterKind.criterion


class FakeLLMProvider(LLMProvider):
    """Deterministic provider for tests.

    Returns `pass=True` for every filter whose lowercased text appears in the
    job description, `False` for every filter whose text starts with "must not",
    and `None` otherwise. Records how many times `evaluate` was called.

    For "question" kind filters, evaluate returns pass=null and synthesises
    a short answer from the description (echoing the criterion behavior
    that the live providers have to learn from the prompt).

    `validate_filter` keys off prefixes in the filter text so each verdict
    has a stable trigger:
      - text contains "[vague]"     → vague
      - text contains "[rejected]"  → rejected
      - anything else               → good
    Kind is derived from text shape via `_classify_kind`.
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
            if f.kind == FilterKind.question:
                pass_val: bool | None = None
                evidence = "stub answer based on description"
            elif text_lc.startswith("must not") and text_lc[9:].strip() in description_lc:
                pass_val = False
                evidence = "mentioned in description"
            elif text_lc in description_lc:
                pass_val = True
                evidence = "matched literal substring"
            else:
                pass_val = None
                evidence = "not mentioned"
            results.append(
                EvaluationResult.model_validate(
                    {
                        "filter": f.text,
                        "pass": pass_val,
                        "evidence": evidence,
                        "kind": f.kind.value,
                    }
                )
            )
        return results, TokenUsage(input_tokens=1, output_tokens=1)

    async def validate_filter(
        self,
        text: str,
    ) -> tuple[FilterValidationResult, TokenUsage]:
        self.validation_calls += 1
        lower = text.lower()
        kind = _classify_kind(text)
        if "[rejected]" in lower:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.rejected,
                reason="not a job-posting filter",
                suggestion=None,
                kind=kind,
            )
        elif "[vague]" in lower:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.vague,
                reason="too subjective to evaluate",
                suggestion="Try a measurable criterion instead.",
                kind=kind,
            )
        else:
            result = FilterValidationResult(
                verdict=FilterValidationVerdict.good,
                reason="clear and decidable",
                suggestion=None,
                kind=kind,
            )
        return result, TokenUsage(input_tokens=1, output_tokens=1)
