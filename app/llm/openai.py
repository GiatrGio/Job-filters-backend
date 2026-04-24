from __future__ import annotations

import json

from openai import AsyncOpenAI

from app.llm.base import LLMProvider
from app.llm.prompts import (
    EVALUATION_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    build_user_message,
)
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def evaluate(
        self,
        job: JobInput,
        filters: list[FilterInput],
    ) -> tuple[list[EvaluationResult], TokenUsage]:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(job, filters)},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "description": TOOL_DESCRIPTION,
                        "parameters": EVALUATION_TOOL_SCHEMA,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        raw_results = payload.get("results", [])
        results = [EvaluationResult.model_validate(r) for r in raw_results]

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )
        return results, usage
