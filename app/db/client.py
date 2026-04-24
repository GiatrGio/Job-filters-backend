"""Thin wrapper around supabase-py.

The backend uses the Supabase *secret* key (replaces the legacy `service_role`),
which bypasses RLS. All per-user filtering happens in application code using
the verified `user_id` from the JWT — never trust a user_id from the request
body.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


class SupabaseDB:
    def __init__(self, client: Client) -> None:
        self.client = client

    @property
    def table(self):  # noqa: ANN201 — supabase-py's returned types are dynamic
        return self.client.table

    def rpc(self, fn_name: str, params: dict):  # noqa: ANN201
        return self.client.rpc(fn_name, params)


@lru_cache
def _build_client(url: str, key: str) -> Client:
    return create_client(url, key)


def get_db() -> SupabaseDB:
    settings = get_settings()
    return SupabaseDB(_build_client(settings.supabase_url, settings.supabase_secret_key))
