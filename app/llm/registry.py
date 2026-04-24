from __future__ import annotations

from app.config import Settings
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.openai import OpenAIProvider


def build_provider(name: str, settings: Settings) -> LLMProvider:
    name = name.lower()
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    if name == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {name!r}. Expected 'anthropic' or 'openai'.")
