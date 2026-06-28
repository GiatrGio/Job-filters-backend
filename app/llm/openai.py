from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.llm.base import LLMProvider
from app.llm.prompts import (
    COVER_LETTER_SYSTEM_PROMPT,
    COVER_LETTER_TOOL_DESCRIPTION,
    COVER_LETTER_TOOL_NAME,
    COVER_LETTER_TOOL_SCHEMA,
    COVER_LETTER_VALIDATION_SYSTEM_PROMPT,
    COVER_LETTER_VALIDATION_TOOL_DESCRIPTION,
    COVER_LETTER_VALIDATION_TOOL_NAME,
    COVER_LETTER_VALIDATION_TOOL_SCHEMA,
    CV_CONTACT_SYSTEM_PROMPT,
    CV_CONTACT_TOOL_DESCRIPTION,
    CV_CONTACT_TOOL_NAME,
    CV_CONTACT_TOOL_SCHEMA,
    CV_PARSE_SYSTEM_PROMPT,
    CV_PARSE_TOOL_DESCRIPTION,
    CV_PARSE_TOOL_NAME,
    CV_PARSE_TOOL_SCHEMA,
    DOM_DIAGNOSTICS_SYSTEM_PROMPT,
    DOM_DIAGNOSTICS_TOOL_DESCRIPTION,
    DOM_DIAGNOSTICS_TOOL_NAME,
    DOM_DIAGNOSTICS_TOOL_SCHEMA,
    EVALUATION_TOOL_SCHEMA,
    FILTER_VALIDATION_SYSTEM_PROMPT,
    FILTER_VALIDATION_TOOL_DESCRIPTION,
    FILTER_VALIDATION_TOOL_NAME,
    FILTER_VALIDATION_TOOL_SCHEMA,
    JOB_FIT_SYSTEM_PROMPT,
    JOB_FIT_TOOL_DESCRIPTION,
    JOB_FIT_TOOL_NAME,
    JOB_FIT_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    build_cover_letter_user_message,
    build_cover_letter_validation_user_message,
    build_cv_contact_user_message,
    build_cv_parse_user_message,
    build_dom_diagnostics_user_message,
    build_filter_validation_user_message,
    build_job_fit_user_message,
    build_user_message,
)
from app.schemas.cover_letter import (
    CoverLetterContent,
    CoverLetterInstructionsValidationResult,
)
from app.schemas.cv import CvContact, CvProfile
from app.schemas.diagnostics import DomDiagnosticsResult
from app.schemas.evaluate import EvaluationResult, FilterInput, JobInput, TokenUsage
from app.schemas.filter import FilterValidationResult
from app.schemas.fit import JobFitResult


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
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(job, filters)},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "parameters": EVALUATION_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
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

    async def validate_filter(
        self,
        text: str,
    ) -> tuple[FilterValidationResult, TokenUsage]:
        messages = [
            {"role": "system", "content": FILTER_VALIDATION_SYSTEM_PROMPT},
            {"role": "user", "content": build_filter_validation_user_message(text)},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": FILTER_VALIDATION_TOOL_NAME,
                    "description": FILTER_VALIDATION_TOOL_DESCRIPTION,
                    "parameters": FILTER_VALIDATION_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice={
                "type": "function",
                "function": {"name": FILTER_VALIDATION_TOOL_NAME},
            },
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        result = FilterValidationResult.model_validate(payload)

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

        return result, usage

    async def diagnose_extraction(
        self,
        telemetry: dict[str, Any],
    ) -> tuple[DomDiagnosticsResult, TokenUsage]:
        messages = [
            {"role": "system", "content": DOM_DIAGNOSTICS_SYSTEM_PROMPT},
            {"role": "user", "content": build_dom_diagnostics_user_message(telemetry)},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": DOM_DIAGNOSTICS_TOOL_NAME,
                    "description": DOM_DIAGNOSTICS_TOOL_DESCRIPTION,
                    "parameters": DOM_DIAGNOSTICS_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": DOM_DIAGNOSTICS_TOOL_NAME}},
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        result = DomDiagnosticsResult.model_validate(payload)

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

        return result, usage

    async def parse_cv(
        self,
        cv_text: str,
    ) -> tuple[CvProfile, TokenUsage]:
        messages = [
            {"role": "system", "content": CV_PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": build_cv_parse_user_message(cv_text)},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": CV_PARSE_TOOL_NAME,
                    "description": CV_PARSE_TOOL_DESCRIPTION,
                    "parameters": CV_PARSE_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": CV_PARSE_TOOL_NAME}},
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        result = CvProfile.model_validate(payload)

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

        return result, usage

    async def evaluate_fit(
        self,
        job: JobInput,
        cv: CvProfile,
    ) -> tuple[JobFitResult, TokenUsage]:
        messages = [
            {"role": "system", "content": JOB_FIT_SYSTEM_PROMPT},
            {"role": "user", "content": build_job_fit_user_message(job, cv)},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": JOB_FIT_TOOL_NAME,
                    "description": JOB_FIT_TOOL_DESCRIPTION,
                    "parameters": JOB_FIT_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": JOB_FIT_TOOL_NAME}},
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        result = JobFitResult.model_validate(payload)

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

        return result, usage

    async def generate_cover_letter(
        self,
        job: JobInput,
        cv: CvProfile,
        instructions: str,
    ) -> tuple[CoverLetterContent, TokenUsage]:
        messages = [
            {"role": "system", "content": COVER_LETTER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_cover_letter_user_message(job, cv, instructions),
            },
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": COVER_LETTER_TOOL_NAME,
                    "description": COVER_LETTER_TOOL_DESCRIPTION,
                    "parameters": COVER_LETTER_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": COVER_LETTER_TOOL_NAME}},
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        result = CoverLetterContent.model_validate(payload)

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

        return result, usage

    async def validate_cover_letter_instructions(
        self,
        text: str,
    ) -> tuple[CoverLetterInstructionsValidationResult, TokenUsage]:
        messages = [
            {"role": "system", "content": COVER_LETTER_VALIDATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_cover_letter_validation_user_message(text),
            },
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": COVER_LETTER_VALIDATION_TOOL_NAME,
                    "description": COVER_LETTER_VALIDATION_TOOL_DESCRIPTION,
                    "parameters": COVER_LETTER_VALIDATION_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice={
                "type": "function",
                "function": {"name": COVER_LETTER_VALIDATION_TOOL_NAME},
            },
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        result = CoverLetterInstructionsValidationResult.model_validate(payload)

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

        return result, usage

    async def extract_cv_contact(
        self,
        cv_text: str,
    ) -> tuple[CvContact, TokenUsage]:
        messages = [
            {"role": "system", "content": CV_CONTACT_SYSTEM_PROMPT},
            {"role": "user", "content": build_cv_contact_user_message(cv_text)},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": CV_CONTACT_TOOL_NAME,
                    "description": CV_CONTACT_TOOL_DESCRIPTION,
                    "parameters": CV_CONTACT_TOOL_SCHEMA,
                },
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": CV_CONTACT_TOOL_NAME}},
        )

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            raise RuntimeError("OpenAI response did not include the expected tool call.")
        payload = json.loads(tool_calls[0].function.arguments)

        result = CvContact.model_validate(payload)

        usage_obj = response.usage
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        )

        return result, usage
