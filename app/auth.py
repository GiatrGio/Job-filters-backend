"""Supabase JWT verification via JWKS.

Supabase now signs user JWTs with asymmetric keys. The backend fetches the JWKS
from `SUPABASE_JWKS_URL`, caches it in memory, and uses PyJWT to verify the
signature + standard claims. No shared secret is stored.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient, PyJWKClientError

from app.config import Settings, get_settings
from app.schemas.user import CurrentUser

_JWKS_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
_jwks_client: PyJWKClient | None = None
_jwks_fetched_at: float = 0.0


def _get_jwks_client(settings: Settings) -> PyJWKClient:
    global _jwks_client, _jwks_fetched_at
    now = time.time()
    if _jwks_client is None or (now - _jwks_fetched_at) > _JWKS_CACHE_TTL_SECONDS:
        _jwks_client = PyJWKClient(settings.supabase_jwks_url, cache_keys=True)
        _jwks_fetched_at = now
    return _jwks_client


def _reset_jwks_cache() -> None:
    """Test hook — forces the next call to re-fetch the JWKS."""
    global _jwks_client, _jwks_fetched_at
    _jwks_client = None
    _jwks_fetched_at = 0.0


def _decode_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        signing_key = _get_jwks_client(settings).get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except (PyJWKClientError, jwt.PyJWTError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
        ) from exc


def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    claims = _decode_token(token, get_settings())
    user_id = claims.get("sub")
    email = claims.get("email") or claims.get("user_metadata", {}).get("email") or ""
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token missing sub claim",
        )
    return CurrentUser(id=user_id, email=email)
