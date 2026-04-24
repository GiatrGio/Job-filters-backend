from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str
    supabase_secret_key: str
    supabase_jwks_url: str

    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    allowed_origins: str = ""
    free_tier_monthly_limit: int = Field(default=50, ge=0)

    # Rate limit for POST /evaluate, per authenticated user.
    # Defaults: burst of 20, sustained 20/min.
    rate_limit_evaluate_capacity: int = Field(default=20, ge=1)
    rate_limit_evaluate_per_minute: float = Field(default=20.0, gt=0)

    # Langfuse observability. Leave empty to disable — the SDK warns but does
    # not crash. The SDK also reads these as env vars directly, so we only
    # list them here for documentation and type-checking.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    log_level: str = "INFO"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
