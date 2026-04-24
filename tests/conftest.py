from __future__ import annotations

import os

import pytest

# Tests must never hit Supabase or a real LLM. Populate the minimum env that
# pydantic-settings requires so `get_settings()` succeeds at import time.
os.environ.setdefault("SUPABASE_URL", "http://fake.supabase")
os.environ.setdefault("SUPABASE_SECRET_KEY", "sb_secret_fake")
os.environ.setdefault("SUPABASE_JWKS_URL", "http://fake.supabase/jwks")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake")
os.environ.setdefault("ALLOWED_ORIGINS", "chrome-extension://fake")
os.environ.setdefault("FREE_TIER_MONTHLY_LIMIT", "3")


@pytest.fixture
def settings():
    from app.config import get_settings

    get_settings.cache_clear()
    return get_settings()
