from __future__ import annotations

from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, Field, field_validator


def validate_internal_destination(value: str) -> str:
    """Allow only same-origin paths, never protocol-relative/absolute URLs."""
    decoded = value
    # Reject encoded and double-encoded slash/backslash/control tricks before
    # this value is ever concatenated with the website origin.
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    parsed = urlsplit(decoded)
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or parsed.scheme
        or parsed.netloc
        or any(ord(char) < 32 for char in decoded)
    ):
        raise ValueError("destination must be a safe internal path")
    return value


class WebHandoffCreate(BaseModel):
    destination: str = Field(default="/app", min_length=1, max_length=500)

    @field_validator("destination")
    @classmethod
    def destination_is_internal(cls, value: str) -> str:
        return validate_internal_destination(value)


class WebHandoffCreateOut(BaseModel):
    url: str
    expires_in: int


class WebHandoffExchange(BaseModel):
    ticket: str = Field(min_length=32, max_length=256)


class WebHandoffExchangeOut(BaseModel):
    user_id: str
    destination: str
    # Null when the website already has a verified session for this user.
    token_hash: str | None = None
