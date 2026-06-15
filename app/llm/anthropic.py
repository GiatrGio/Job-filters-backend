from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from app.llm.base import LLMProvider
from app.llm.prompts import (
    DOM_DIAGNOSTICS_SYSTEM_PROMPT,
    DOM_DIAGNOSTICS_TOOL_DESCRIPTION,
    DOM_DIAGNOSTICS_TOOL_NAME,
    DOM_DIAGNOSTICS_TOOL_SCHEMA,
    EVALUATION_TOOL_SCHEMA,
    FILTER_VALIDATION_SYSTEM_PROMPT,
    FILTER_VALIDATION_TOOL_DESCRIPTION,
    FILTER_VALIDATION_TOOL_NAME,
    FILTER_VALIDATION_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    build_dom_diagnostics_user_message,
    build_filter_validation_user_message,
    build_user_message,
)
from app.schemas.diagnostics import DomDiagnosticsResult
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage
from app.schemas.filter import FilterValidationResult


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
        user_message = build_user_message(job, filters)

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
            messages=[{"role": "user", "content": user_message}],
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

    async def validate_filter(
        self,
        text: str,
    ) -> tuple[FilterValidationResult, TokenUsage]:
        user_message = build_filter_validation_user_message(text)

        # max_tokens is small on purpose — the structured output is tiny
        # (verdict + short reason + optional suggestion). Caps the worst-case
        # cost of a single validation call.
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=256,
            system=FILTER_VALIDATION_SYSTEM_PROMPT,
            tools=[
                {
                    "name": FILTER_VALIDATION_TOOL_NAME,
                    "description": FILTER_VALIDATION_TOOL_DESCRIPTION,
                    "input_schema": FILTER_VALIDATION_TOOL_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": FILTER_VALIDATION_TOOL_NAME},
            messages=[{"role": "user", "content": user_message}],
        )

        tool_payload: dict | None = None
        for block in response.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and block.name == FILTER_VALIDATION_TOOL_NAME
            ):
                tool_payload = block.input  # type: ignore[assignment]
                break
        if tool_payload is None:
            raise RuntimeError(
                "Anthropic response did not include the expected tool call."
            )

        result = FilterValidationResult.model_validate(tool_payload)

        usage = TokenUsage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        )

        return result, usage

    async def diagnose_extraction(
        self,
        telemetry: dict[str, Any],
    ) -> tuple[DomDiagnosticsResult, TokenUsage]:
        user_message = build_dom_diagnostics_user_message(telemetry)

        response = await self._client.messages.create(
            model=self.model,
            # Larger than the other structured calls: the model reasons over a
            # job-HTML snapshot and returns selectors + a fix.
            max_tokens=900,
            system=DOM_DIAGNOSTICS_SYSTEM_PROMPT,
            tools=[
                {
                    "name": DOM_DIAGNOSTICS_TOOL_NAME,
                    "description": DOM_DIAGNOSTICS_TOOL_DESCRIPTION,
                    "input_schema": DOM_DIAGNOSTICS_TOOL_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": DOM_DIAGNOSTICS_TOOL_NAME},
            messages=[{"role": "user", "content": user_message}],
        )

        tool_payload: dict | None = None
        for block in response.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and block.name == DOM_DIAGNOSTICS_TOOL_NAME
            ):
                tool_payload = block.input  # type: ignore[assignment]
                break
        if tool_payload is None:
            raise RuntimeError("Anthropic response did not include the expected tool call.")

        result = DomDiagnosticsResult.model_validate(tool_payload)

        usage = TokenUsage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        )

        return result, usage
