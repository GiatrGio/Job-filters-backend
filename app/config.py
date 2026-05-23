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
    # Optional estimated model pricing overrides, in USD per 1M tokens. When
    # left at 0, the LLM logging/admin UI falls back to a tiny built-in catalog
    # for the default Anthropic/OpenAI models canvasjob uses.
    anthropic_input_cost_usd_per_million: float = Field(default=0.0, ge=0.0)
    anthropic_output_cost_usd_per_million: float = Field(default=0.0, ge=0.0)
    openai_input_cost_usd_per_million: float = Field(default=0.0, ge=0.0)
    openai_output_cost_usd_per_million: float = Field(default=0.0, ge=0.0)

    allowed_origins: str = ""
    # Fallback when a profile row is missing or has NULL `monthly_eval_limit`.
    # The DB default is also 50 (migration 0012); they're kept in sync.
    free_tier_monthly_limit: int = Field(default=50, ge=0)
    free_tracked_jobs_limit: int = Field(default=5, ge=0)
    # Marketed as unlimited. The cap is an internal abuse ceiling and should
    # only be shown in admin tooling.
    pro_tracked_jobs_limit: int = Field(default=1000, ge=0)
    # Ratio at which the side panel shows the "approaching your monthly
    # limit" banner. Kept as a ratio so it stays correct if the underlying
    # eval limit changes per-user or globally. Exposed in UsageOut so
    # clients pick up server-side tuning without a rebuild.
    free_tier_warning_threshold: float = Field(default=0.8, ge=0.0, le=1.0)

    # Rate limit for POST /evaluate, per authenticated user.
    # Defaults: burst of 20, sustained 20/min.
    rate_limit_evaluate_capacity: int = Field(default=20, ge=1)
    rate_limit_evaluate_per_minute: float = Field(default=20.0, gt=0)

    # Comma-separated list of authenticated user emails allowed to access
    # production admin endpoints. Localhost remains allowed for local admin QA.
    admin_emails: str = ""

    # Stripe billing. Prices are created in Stripe Dashboard; the Pro price
    # should be EUR 4.99/month with tax behavior set to inclusive.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = ""
    stripe_automatic_tax_enabled: bool = True
    website_url: str = "http://localhost:3000"
    pro_monthly_eval_limit: int = Field(default=5000, ge=0)

    log_level: str = "INFO"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
