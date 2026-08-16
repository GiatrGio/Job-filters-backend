"""Short-lived, one-time authentication grants from the extension to the web app."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from app.config import Settings
from app.db.client import SupabaseDB
from app.schemas.auth_handoff import validate_internal_destination


class AuthHandoffInvalid(Exception):
    """The ticket is unknown, expired, or was already consumed."""


class AuthHandoffAccountMismatch(Exception):
    """The browser website session belongs to a different user."""


class AuthHandoffSessionError(Exception):
    """Supabase could not mint a fresh website session token."""


class AuthSessionGateway(Protocol):
    def create_email_token_hash(self, user_id: str) -> str: ...


class SupabaseAuthSessionGateway:
    """Creates a fresh session grant without exposing the secret key to Next.js."""

    def __init__(self, db: SupabaseDB) -> None:
        self._admin = db.client.auth.admin

    def create_email_token_hash(self, user_id: str) -> str:
        try:
            user_response = self._admin.get_user_by_id(user_id)
            email = user_response.user.email
            if not email:
                raise AuthHandoffSessionError("user has no email address")
            link = self._admin.generate_link({"type": "magiclink", "email": email})
            token_hash = link.properties.hashed_token
        except AuthHandoffSessionError:
            raise
        except Exception as exc:
            raise AuthHandoffSessionError("could not create website session") from exc

        if not token_hash:
            raise AuthHandoffSessionError("Supabase returned an empty token hash")
        return token_hash


@dataclass(frozen=True)
class CreatedWebHandoff:
    url: str
    expires_in: int


@dataclass(frozen=True)
class ExchangedWebHandoff:
    user_id: str
    destination: str
    token_hash: str | None


class AuthHandoffService:
    def __init__(
        self,
        db: SupabaseDB,
        settings: Settings,
        auth_gateway: AuthSessionGateway,
        *,
        clock: Callable[[], datetime] | None = None,
        ticket_factory: Callable[[], str] | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._auth_gateway = auth_gateway
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ticket_factory = ticket_factory or (lambda: secrets.token_urlsafe(32))

    def create(self, *, user_id: str, destination: str) -> CreatedWebHandoff:
        destination = validate_internal_destination(destination)
        now = self._clock()
        ttl = self._settings.auth_handoff_ttl_seconds
        expires_at = now + timedelta(seconds=ttl)

        # Opportunistic cleanup keeps abandoned tickets bounded without a
        # scheduler. Live tickets are never removed here.
        self._db.table("auth_handoffs").delete().lt("expires_at", now.isoformat()).execute()

        ticket = self._ticket_factory()
        if len(ticket) < 32:
            raise RuntimeError("auth handoff ticket factory returned insufficient entropy")
        self._db.table("auth_handoffs").insert(
            {
                "token_hash": _ticket_hash(ticket),
                "user_id": user_id,
                "destination": destination,
                "expires_at": expires_at.isoformat(),
            }
        ).execute()

        website_url = self._validated_website_url()
        query = urlencode({"ticket": ticket})
        return CreatedWebHandoff(
            url=f"{website_url}/auth/extension?{query}",
            expires_in=ttl,
        )

    def exchange(
        self,
        *,
        ticket: str,
        website_user_id: str | None,
    ) -> ExchangedWebHandoff:
        token_hash = _ticket_hash(ticket)
        now = self._clock().isoformat()

        # Inspect before consuming so a different signed-in website account can
        # be given an explicit choice. A matching/anonymous exchange is still
        # consumed atomically by the RPC immediately afterwards.
        inspect_response = (
            self._db.table("auth_handoffs")
            .select("user_id,destination")
            .eq("token_hash", token_hash)
            .gte("expires_at", now)
            .limit(1)
            .execute()
        )
        inspected = inspect_response.data or []
        if not inspected:
            raise AuthHandoffInvalid
        if website_user_id and website_user_id != inspected[0]["user_id"]:
            raise AuthHandoffAccountMismatch

        consumed_response = self._db.rpc(
            "consume_auth_handoff",
            {"p_token_hash": token_hash},
        ).execute()
        consumed = consumed_response.data or []
        if not consumed:
            raise AuthHandoffInvalid

        row = consumed[0]
        user_id = str(row["user_id"])
        destination = validate_internal_destination(str(row["destination"]))
        if website_user_id == user_id:
            return ExchangedWebHandoff(
                user_id=user_id,
                destination=destination,
                token_hash=None,
            )

        session_token_hash = self._auth_gateway.create_email_token_hash(user_id)
        return ExchangedWebHandoff(
            user_id=user_id,
            destination=destination,
            token_hash=session_token_hash,
        )

    def _validated_website_url(self) -> str:
        value = self._settings.website_url.rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("WEBSITE_URL must be an HTTP(S) origin without a path")
        return value


def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()
