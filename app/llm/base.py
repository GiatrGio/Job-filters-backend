from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage


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
