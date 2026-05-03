"""Stripe billing integration.

The backend is the only service that talks to Stripe with a secret key. Clients
ask for hosted Checkout/Portal URLs, and Stripe webhooks are the source of
truth for plan upgrades/downgrades.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.db.client import SupabaseDB

logger = logging.getLogger(__name__)

PRO_PLAN = "pro"
FREE_PLAN = "free"
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
FREE_EVAL_LIMIT = 200
FREE_CV_TAILORING_LIMIT = 0


@dataclass(frozen=True)
class StripeCustomer:
    id: str


@dataclass(frozen=True)
class StripeSession:
    id: str
    url: str


class BillingGateway(Protocol):
    def create_customer(self, *, email: str, user_id: str) -> StripeCustomer:
        ...

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        user_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax_enabled: bool,
    ) -> StripeSession:
        ...

    def create_portal_session(self, *, customer_id: str, return_url: str) -> StripeSession:
        ...


class StripeGateway:
    def __init__(self, secret_key: str) -> None:
        self._secret_key = secret_key

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._secret_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe is not configured",
            )
        try:
            with httpx.Client(
                base_url="https://api.stripe.com",
                headers={"Authorization": f"Bearer {self._secret_key}"},
                timeout=20.0,
            ) as client:
                response = client.post(path, data=data)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            with suppress(ValueError):
                detail = exc.response.json().get("error", {}).get("message", detail)
            logger.warning(
                "Stripe request failed path=%s status=%s detail=%s",
                path,
                exc.response.status_code,
                detail,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe request failed: {detail}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe request failed: {exc}",
            ) from exc

    def create_customer(self, *, email: str, user_id: str) -> StripeCustomer:
        data = self._post(
            "/v1/customers",
            {
                "email": email,
                "metadata[user_id]": user_id,
            },
        )
        return StripeCustomer(id=str(data["id"]))

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        user_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        automatic_tax_enabled: bool,
    ) -> StripeSession:
        data = self._post(
            "/v1/checkout/sessions",
            {
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": user_id,
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "billing_address_collection": "auto",
                "automatic_tax[enabled]": str(automatic_tax_enabled).lower(),
                "metadata[user_id]": user_id,
                "subscription_data[metadata][user_id]": user_id,
            },
        )
        return StripeSession(id=str(data["id"]), url=str(data["url"]))

    def create_portal_session(self, *, customer_id: str, return_url: str) -> StripeSession:
        data = self._post(
            "/v1/billing_portal/sessions",
            {
                "customer": customer_id,
                "return_url": return_url,
            },
        )
        return StripeSession(id=str(data["id"]), url=str(data["url"]))


class BillingService:
    def __init__(self, db: SupabaseDB, settings: Settings, gateway: BillingGateway) -> None:
        self._db = db
        self._settings = settings
        self._gateway = gateway

    def create_checkout_session(self, *, user_id: str, email: str) -> str:
        if not self._settings.stripe_pro_price_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe Pro price is not configured",
            )
        profile = self._get_profile(user_id)
        customer_id = profile.get("stripe_customer_id") if profile else None
        if not customer_id:
            customer = self._gateway.create_customer(email=email, user_id=user_id)
            customer_id = customer.id
            self._update_profile(user_id, {"stripe_customer_id": customer_id})

        session = self._gateway.create_checkout_session(
            customer_id=customer_id,
            user_id=user_id,
            price_id=self._settings.stripe_pro_price_id,
            success_url=f"{self._settings.website_url}/pricing?checkout=success",
            cancel_url=f"{self._settings.website_url}/pricing?checkout=cancelled",
            automatic_tax_enabled=self._settings.stripe_automatic_tax_enabled,
        )
        return session.url

    def create_portal_session(self, *, user_id: str) -> str:
        profile = self._get_profile(user_id)
        customer_id = profile.get("stripe_customer_id") if profile else None
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Stripe customer exists for this user",
            )
        session = self._gateway.create_portal_session(
            customer_id=customer_id,
            return_url=f"{self._settings.website_url}/pricing",
        )
        return session.url

    def handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        data_object = event.get("data", {}).get("object", {})
        if not isinstance(data_object, dict):
            return

        if event_type == "checkout.session.completed":
            self._handle_checkout_completed(data_object)
            return

        if event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            self._handle_subscription(data_object)

    def _handle_checkout_completed(self, session: dict[str, Any]) -> None:
        if session.get("mode") != "subscription":
            return
        user_id = (
            session.get("client_reference_id")
            or session.get("metadata", {}).get("user_id")
        )
        if not user_id:
            return
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        patch: dict[str, Any] = {
            "plan": PRO_PLAN,
            "monthly_eval_limit": self._settings.pro_monthly_eval_limit,
            "monthly_cv_tailoring_limit": self._settings.pro_monthly_cv_tailoring_limit,
        }
        if customer_id:
            patch["stripe_customer_id"] = customer_id
        if subscription_id:
            patch["stripe_subscription_id"] = subscription_id
            patch["stripe_subscription_status"] = "active"
            patch["stripe_price_id"] = self._settings.stripe_pro_price_id
        self._update_profile(str(user_id), patch)

    def _handle_subscription(self, subscription: dict[str, Any]) -> None:
        user_id = self._resolve_user_id(subscription)
        if not user_id:
            return

        status_value = str(subscription.get("status") or "")
        cancel_at_period_end = bool(subscription.get("cancel_at_period_end") or False)
        current_period_end = _timestamp_to_iso(subscription.get("current_period_end"))
        price_id = _subscription_price_id(subscription)
        customer_id = subscription.get("customer")
        subscription_id = subscription.get("id")

        if subscription_id:
            self._upsert_subscription(
                {
                    "user_id": user_id,
                    "stripe_customer_id": customer_id,
                    "stripe_subscription_id": subscription_id,
                    "stripe_price_id": price_id,
                    "status": status_value,
                    "current_period_end": current_period_end,
                    "cancel_at_period_end": cancel_at_period_end,
                }
            )

        pro_active = status_value in ACTIVE_SUBSCRIPTION_STATUSES
        patch: dict[str, Any] = {
            "plan": PRO_PLAN if pro_active else FREE_PLAN,
            "monthly_eval_limit": (
                self._settings.pro_monthly_eval_limit if pro_active else FREE_EVAL_LIMIT
            ),
            "monthly_cv_tailoring_limit": (
                self._settings.pro_monthly_cv_tailoring_limit
                if pro_active
                else FREE_CV_TAILORING_LIMIT
            ),
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription_id,
            "stripe_subscription_status": status_value,
            "stripe_price_id": price_id,
            "stripe_current_period_end": current_period_end,
            "stripe_cancel_at_period_end": cancel_at_period_end,
        }
        self._update_profile(user_id, patch)

    def _resolve_user_id(self, subscription: dict[str, Any]) -> str | None:
        metadata_user = subscription.get("metadata", {}).get("user_id")
        if metadata_user:
            return str(metadata_user)

        subscription_id = subscription.get("id")
        if subscription_id:
            row = self._find_profile("stripe_subscription_id", subscription_id)
            if row:
                return str(row["id"])

        customer_id = subscription.get("customer")
        if customer_id:
            row = self._find_profile("stripe_customer_id", customer_id)
            if row:
                return str(row["id"])
        return None

    def _get_profile(self, user_id: str) -> dict[str, Any]:
        resp = self._db.table("profiles").select("*").eq("id", user_id).limit(1).execute()
        rows = resp.data or []
        if rows:
            return rows[0]
        resp = self._db.table("profiles").insert({"id": user_id}).execute()
        rows = resp.data or []
        return rows[0] if rows else {}

    def _find_profile(self, column: str, value: Any) -> dict[str, Any] | None:
        resp = self._db.table("profiles").select("*").eq(column, value).limit(1).execute()
        rows = resp.data or []
        return rows[0] if rows else None

    def _update_profile(self, user_id: str, patch: dict[str, Any]) -> None:
        self._db.table("profiles").update(patch).eq("id", user_id).execute()

    def _upsert_subscription(self, row: dict[str, Any]) -> None:
        self._db.table("subscriptions").upsert(
            row,
            on_conflict="stripe_subscription_id",
        ).execute()


def verify_stripe_signature(
    *,
    payload: bytes,
    signature_header: str | None,
    webhook_secret: str,
    tolerance_seconds: int = 300,
) -> dict[str, Any]:
    if not webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret is not configured",
        )
    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe signature",
        )

    values: dict[str, list[str]] = {}
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values.setdefault(key, []).append(value)

    timestamps = values.get("t") or []
    signatures = values.get("v1") or []
    if not timestamps or not signatures:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        )

    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        ) from exc

    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expired Stripe signature",
        )

    signed_payload = f"{timestamp}.{payload.decode()}".encode()
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        )

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc
    if not isinstance(event, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe event",
        )
    return event


def _timestamp_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _subscription_price_id(subscription: dict[str, Any]) -> str | None:
    items = subscription.get("items", {}).get("data", [])
    if not items:
        return None
    price = items[0].get("price") or {}
    price_id = price.get("id")
    return str(price_id) if price_id else None
