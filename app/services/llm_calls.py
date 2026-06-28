from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder

from app.config import Settings
from app.db.client import SupabaseDB
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
    build_dom_diagnostics_user_message,
    build_filter_validation_user_message,
    build_job_fit_user_message,
    build_user_message,
)
from app.schemas.cv import CvProfile
from app.schemas.evaluate import FilterInput, JobInput, TokenUsage

logger = logging.getLogger(__name__)

LLMCallType = Literal[
    "job_evaluation",
    "filter_validation",
    "dom_diagnostics",
    "cv_parse",
    "job_fit",
    "cover_letter",
    "cover_letter_validation",
    "cv_contact",
]
LLMCallStatus = Literal["success", "error"]
LLMPricingSource = Literal["env", "default", "unavailable"]

# Provider pricing pages do not expose a first-party machine-readable pricing
# API. Keep a tiny fallback catalog for the models canvasjob uses today, and
# let env vars override it when prices change.
DEFAULT_MODEL_PRICING_USD_PER_MILLION: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {
        "claude-haiku-4-5": (1.0, 5.0),
    },
    "openai": {
        "gpt-4o-mini": (0.15, 0.60),
    },
}


@dataclass
class LLMCallTimer:
    started_at: float

    @classmethod
    def start(cls) -> LLMCallTimer:
        return cls(started_at=perf_counter())

    def elapsed_ms(self) -> int:
        return max(0, round((perf_counter() - self.started_at) * 1000))


class LLMCallLogger:
    def __init__(self, db: SupabaseDB, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def log(
        self,
        *,
        user_id: str,
        call_type: LLMCallType,
        provider: LLMProvider,
        status: LLMCallStatus,
        prompt: dict[str, Any],
        response: Any = None,
        error: str | None = None,
        token_usage: TokenUsage | None = None,
        duration_ms: int | None = None,
        source: str | None = None,
        external_id: str | None = None,
        summary: str | None = None,
    ) -> None:
        token_usage = token_usage or TokenUsage()
        try:
            self._db.table("llm_calls").insert(
                {
                    "user_id": user_id,
                    "call_type": call_type,
                    "provider": provider.name,
                    "model": provider.model,
                    "status": status,
                    "source": source,
                    "external_id": external_id,
                    "summary": summary,
                    "prompt": jsonable_encoder(prompt),
                    "response": jsonable_encoder(response),
                    "error": error,
                    "tokens_input": token_usage.input_tokens,
                    "tokens_output": token_usage.output_tokens,
                    "cost_usd_micros": estimate_cost_usd_micros(
                        settings=self._settings,
                        provider_name=provider.name,
                        model=provider.model,
                        input_tokens=token_usage.input_tokens,
                        output_tokens=token_usage.output_tokens,
                    ),
                    "duration_ms": duration_ms,
                }
            ).execute()
        except Exception:
            logger.exception("failed to persist LLM call log")


def build_prompt_payload(
    *,
    provider_name: str,
    call_type: LLMCallType,
    job: JobInput | None = None,
    filters: list[FilterInput] | None = None,
    filter_text: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    cv: CvProfile | None = None,
    cv_text_len: int | None = None,
    instructions: str | None = None,
) -> dict[str, Any]:
    if call_type == "cv_parse":
        # PRIVACY: never write the raw CV (which contains the member's name and
        # contact details) to the observability log. Log the system prompt and
        # tool schema for debuggability, but redact the CV body itself.
        redacted = f"[CV text redacted for privacy — {cv_text_len or 0} chars]"
        if provider_name == "openai":
            return {
                "messages": [
                    {"role": "system", "content": CV_PARSE_SYSTEM_PROMPT},
                    {"role": "user", "content": redacted},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": CV_PARSE_TOOL_NAME,
                            "description": CV_PARSE_TOOL_DESCRIPTION,
                            "parameters": CV_PARSE_TOOL_SCHEMA,
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": CV_PARSE_TOOL_NAME},
                },
            }
        return {
            "system": CV_PARSE_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": redacted}],
            "tools": [
                {
                    "name": CV_PARSE_TOOL_NAME,
                    "description": CV_PARSE_TOOL_DESCRIPTION,
                    "input_schema": CV_PARSE_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": CV_PARSE_TOOL_NAME},
        }

    if call_type == "cv_contact":
        # PRIVACY: same as cv_parse — the CV text (full PII) is redacted from the
        # log. The extracted contact is redacted from the response by the caller.
        redacted = f"[CV text redacted for privacy — {cv_text_len or 0} chars]"
        if provider_name == "openai":
            return {
                "messages": [
                    {"role": "system", "content": CV_CONTACT_SYSTEM_PROMPT},
                    {"role": "user", "content": redacted},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": CV_CONTACT_TOOL_NAME,
                            "description": CV_CONTACT_TOOL_DESCRIPTION,
                            "parameters": CV_CONTACT_TOOL_SCHEMA,
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": CV_CONTACT_TOOL_NAME},
                },
            }
        return {
            "system": CV_CONTACT_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": redacted}],
            "tools": [
                {
                    "name": CV_CONTACT_TOOL_NAME,
                    "description": CV_CONTACT_TOOL_DESCRIPTION,
                    "input_schema": CV_CONTACT_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": CV_CONTACT_TOOL_NAME},
        }

    if call_type == "job_fit":
        if job is None or cv is None:
            raise ValueError("job and cv are required for job_fit")
        # The candidate profile is already non-PII and the job description is the
        # same public listing text logged for job_evaluation, so this prompt is
        # safe to log in full.
        user_message = build_job_fit_user_message(job, cv)
        if provider_name == "openai":
            return {
                "messages": [
                    {"role": "system", "content": JOB_FIT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": JOB_FIT_TOOL_NAME,
                            "description": JOB_FIT_TOOL_DESCRIPTION,
                            "parameters": JOB_FIT_TOOL_SCHEMA,
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": JOB_FIT_TOOL_NAME},
                },
            }
        return {
            "system": JOB_FIT_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
            "tools": [
                {
                    "name": JOB_FIT_TOOL_NAME,
                    "description": JOB_FIT_TOOL_DESCRIPTION,
                    "input_schema": JOB_FIT_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": JOB_FIT_TOOL_NAME},
        }

    if call_type == "dom_diagnostics":
        if diagnostics is None:
            raise ValueError("diagnostics is required for dom_diagnostics")
        user_message = build_dom_diagnostics_user_message(diagnostics)
        if provider_name == "openai":
            return {
                "messages": [
                    {"role": "system", "content": DOM_DIAGNOSTICS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": DOM_DIAGNOSTICS_TOOL_NAME,
                            "description": DOM_DIAGNOSTICS_TOOL_DESCRIPTION,
                            "parameters": DOM_DIAGNOSTICS_TOOL_SCHEMA,
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": DOM_DIAGNOSTICS_TOOL_NAME},
                },
            }
        return {
            "system": DOM_DIAGNOSTICS_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
            "tools": [
                {
                    "name": DOM_DIAGNOSTICS_TOOL_NAME,
                    "description": DOM_DIAGNOSTICS_TOOL_DESCRIPTION,
                    "input_schema": DOM_DIAGNOSTICS_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": DOM_DIAGNOSTICS_TOOL_NAME},
        }

    if call_type == "job_evaluation":
        if job is None or filters is None:
            raise ValueError("job and filters are required for job_evaluation")
        user_message = build_user_message(job, filters)
        if provider_name == "openai":
            return {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": TOOL_NAME,
                            "description": TOOL_DESCRIPTION,
                            "parameters": EVALUATION_TOOL_SCHEMA,
                        },
                    }
                ],
                "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
            }
        return {
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": TOOL_DESCRIPTION,
                    "input_schema": EVALUATION_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }

    if call_type == "cover_letter":
        if job is None or cv is None:
            raise ValueError("job and cv are required for cover_letter")
        # The candidate's name/email/phone/location never enter the prompt (the
        # header is composed client-side). What remains — the non-PII CV profile,
        # the public job text, and the user's own instructions — is safe to log,
        # same stance as job_fit / job_evaluation.
        user_message = build_cover_letter_user_message(job, cv, instructions or "")
        if provider_name == "openai":
            return {
                "messages": [
                    {"role": "system", "content": COVER_LETTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": COVER_LETTER_TOOL_NAME,
                            "description": COVER_LETTER_TOOL_DESCRIPTION,
                            "parameters": COVER_LETTER_TOOL_SCHEMA,
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": COVER_LETTER_TOOL_NAME},
                },
            }
        return {
            "system": COVER_LETTER_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
            "tools": [
                {
                    "name": COVER_LETTER_TOOL_NAME,
                    "description": COVER_LETTER_TOOL_DESCRIPTION,
                    "input_schema": COVER_LETTER_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": COVER_LETTER_TOOL_NAME},
        }

    if call_type == "cover_letter_validation":
        if instructions is None:
            raise ValueError("instructions is required for cover_letter_validation")
        user_message = build_cover_letter_validation_user_message(instructions)
        if provider_name == "openai":
            return {
                "messages": [
                    {"role": "system", "content": COVER_LETTER_VALIDATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": COVER_LETTER_VALIDATION_TOOL_NAME,
                            "description": COVER_LETTER_VALIDATION_TOOL_DESCRIPTION,
                            "parameters": COVER_LETTER_VALIDATION_TOOL_SCHEMA,
                        },
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": COVER_LETTER_VALIDATION_TOOL_NAME},
                },
            }
        return {
            "system": COVER_LETTER_VALIDATION_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
            "tools": [
                {
                    "name": COVER_LETTER_VALIDATION_TOOL_NAME,
                    "description": COVER_LETTER_VALIDATION_TOOL_DESCRIPTION,
                    "input_schema": COVER_LETTER_VALIDATION_TOOL_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": COVER_LETTER_VALIDATION_TOOL_NAME},
        }

    if filter_text is None:
        raise ValueError("filter_text is required for filter_validation")
    user_message = build_filter_validation_user_message(filter_text)
    if provider_name == "openai":
        return {
            "messages": [
                {"role": "system", "content": FILTER_VALIDATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": FILTER_VALIDATION_TOOL_NAME,
                        "description": FILTER_VALIDATION_TOOL_DESCRIPTION,
                        "parameters": FILTER_VALIDATION_TOOL_SCHEMA,
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": FILTER_VALIDATION_TOOL_NAME},
            },
        }
    return {
        "system": FILTER_VALIDATION_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
        "tools": [
            {
                "name": FILTER_VALIDATION_TOOL_NAME,
                "description": FILTER_VALIDATION_TOOL_DESCRIPTION,
                "input_schema": FILTER_VALIDATION_TOOL_SCHEMA,
            }
        ],
        "tool_choice": {"type": "tool", "name": FILTER_VALIDATION_TOOL_NAME},
    }


def estimate_cost_usd_micros(
    *,
    settings: Settings,
    provider_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int | None:
    input_rate, output_rate, source = rates_for_model(settings, provider_name, model)
    if source == "unavailable":
        return None
    if input_rate == 0 and output_rate == 0:
        return None
    cost_usd = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return round(cost_usd * 1_000_000)


def pricing_catalog(settings: Settings) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for provider_name, model in [
        ("anthropic", settings.anthropic_model),
        ("openai", settings.openai_model),
    ]:
        _append_pricing_row(rows, seen, settings, provider_name, model)

    for provider_name, models in DEFAULT_MODEL_PRICING_USD_PER_MILLION.items():
        for model in models:
            _append_pricing_row(rows, seen, settings, provider_name, model)

    return rows


def summarize_job(job: JobInput) -> str:
    title = job.job_title or "Untitled job"
    company = job.job_company or "unknown company"
    return f"{title} at {company}"


def rates_for_model(
    settings: Settings,
    provider_name: str,
    model: str,
) -> tuple[float, float, LLMPricingSource]:
    input_rate, output_rate = _env_rates_for_provider(settings, provider_name)
    if input_rate > 0 or output_rate > 0:
        return (input_rate, output_rate, "env")

    default_rates = _default_rates_for_model(provider_name, model)
    if default_rates is None:
        return (0.0, 0.0, "unavailable")
    return (*default_rates, "default")


def _env_rates_for_provider(settings: Settings, provider_name: str) -> tuple[float, float]:
    if provider_name == "openai":
        return (
            settings.openai_input_cost_usd_per_million,
            settings.openai_output_cost_usd_per_million,
        )
    if provider_name == "anthropic":
        return (
            settings.anthropic_input_cost_usd_per_million,
            settings.anthropic_output_cost_usd_per_million,
        )
    return (0.0, 0.0)


def _default_rates_for_model(provider_name: str, model: str) -> tuple[float, float] | None:
    provider_catalog = DEFAULT_MODEL_PRICING_USD_PER_MILLION.get(provider_name, {})
    normalized_model = model.lower()
    for catalog_model, rates in provider_catalog.items():
        if catalog_model == normalized_model or catalog_model in normalized_model:
            return rates
    return None


def _append_pricing_row(
    rows: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    settings: Settings,
    provider_name: str,
    model: str,
) -> None:
    key = (provider_name, model)
    if key in seen:
        return
    seen.add(key)
    input_rate, output_rate, source = rates_for_model(settings, provider_name, model)
    rows.append(
        {
            "provider": provider_name,
            "model": model,
            "input_cost_usd_per_million": input_rate,
            "output_cost_usd_per_million": output_rate,
            "source": source,
        }
    )
