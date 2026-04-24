from __future__ import annotations

from anthropic import AsyncAnthropic

from app.llm.base import LLMProvider
from app.llm.prompts import (
    EVALUATION_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    build_user_message,
)
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def evaluate(
        self,
        job: JobInput,
        filters: list[FilterInput],
    ) -> tuple[list[EvaluationResult], TokenUsage]:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "input_schema": EVALUATION_TOOL_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": build_user_message(job, filters)}],
        )

        tool_payload: dict | None = None
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
                tool_payload = block.input  # type: ignore[assignment]
                break
        if tool_payload is None:
            raise RuntimeError("Anthropic response did not include the expected tool call.")

        raw_results = tool_payload.get("results", [])
        results = [EvaluationResult.model_validate(r) for r in raw_results]

        usage = TokenUsage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        )
        return results, usage
