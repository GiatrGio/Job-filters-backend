"""Self-service account deletion.

Erasure leans on the schema: every user-owned table declares
`references auth.users on delete cascade`, so removing the Supabase auth user
removes the rows in profiles, filters, filter_profiles, evaluations,
usage_counters, applications, application_contacts, application_interviews,
cv_profiles, job_fit_evaluations, cover_letter_settings, subscriptions and
auth_handoffs in one step. llm_calls deliberately survives with user_id set to
null (migration 0018) — it is cost telemetry, not user content.

Nothing of the user's lives outside Postgres: uploaded CVs are parsed and
discarded, and generated cover letters are returned to the client but never
persisted. Stripe is the one external system holding anything, which is why it
is torn down here first.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.db.client import SupabaseDB
from app.services.billing import ACTIVE_SUBSCRIPTION_STATUSES

logger = logging.getLogger(__name__)


class AuthAdminGateway(Protocol):
    def delete_user(self, user_id: str) -> None:
        ...


class BillingTeardownGateway(Protocol):
    def cancel_subscription(self, subscription_id: str) -> None:
        ...

    def delete_customer(self, customer_id: str) -> None:
        ...


class AccountService:
    def __init__(
        self,
        *,
        db: SupabaseDB,
        auth_admin: AuthAdminGateway,
        # None when Stripe isn't configured (no secret key) — the local and
        # pre-launch case. Deletion still works, there is just nothing to bill.
        billing: BillingTeardownGateway | None = None,
    ) -> None:
        self._db = db
        self._auth_admin = auth_admin
        self._billing = billing

    def delete_account(self, user_id: str) -> None:
        """Tear down billing, then delete the auth user and cascade the data.

        Ordering matters. Stripe comes first because a failure there must abort
        the whole thing: deleting the account while a subscription is live would
        keep charging a customer who no longer exists and can no longer reach
        the billing portal. Subscription cancellation therefore raises, and the
        user can retry. Only cancelling subscriptions that are still active
        keeps that retry safe.
        """
        profile = self._profile(user_id)
        if self._billing is not None:
            self._cancel_subscriptions(user_id, profile)
            self._delete_customer(profile)

        self._auth_admin.delete_user(user_id)
        logger.info("Deleted account and cascaded user data user_id=%s", user_id)

    def _profile(self, user_id: str) -> dict[str, Any]:
        resp = (
            self._db.table("profiles")
            .select("stripe_customer_id,stripe_subscription_id,stripe_subscription_status")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else {}

    def _cancel_subscriptions(self, user_id: str, profile: dict[str, Any]) -> None:
        assert self._billing is not None
        for subscription_id in self._active_subscription_ids(user_id, profile):
            self._billing.cancel_subscription(subscription_id)
            logger.info(
                "Cancelled subscription before account deletion user_id=%s subscription=%s",
                user_id,
                subscription_id,
            )

    def _active_subscription_ids(self, user_id: str, profile: dict[str, Any]) -> list[str]:
        """Every still-billable subscription id, deduplicated.

        The profile carries the current one; the subscriptions table is scanned
        too so an older row the profile no longer points at can't be left
        running.
        """
        ids: list[str] = []

        profile_status = profile.get("stripe_subscription_status")
        profile_subscription = profile.get("stripe_subscription_id")
        if profile_subscription and profile_status in ACTIVE_SUBSCRIPTION_STATUSES:
            ids.append(str(profile_subscription))

        resp = (
            self._db.table("subscriptions")
            .select("stripe_subscription_id,status")
            .eq("user_id", user_id)
            .execute()
        )
        for row in resp.data or []:
            subscription_id = row.get("stripe_subscription_id")
            if subscription_id and row.get("status") in ACTIVE_SUBSCRIPTION_STATUSES:
                ids.append(str(subscription_id))

        return list(dict.fromkeys(ids))

    def _delete_customer(self, profile: dict[str, Any]) -> None:
        """Best-effort, unlike cancellation.

        By this point nothing can bill the user again, so a Stripe hiccup here
        shouldn't trap them in an account they asked to delete. It is logged
        loudly instead so the leftover customer can be removed by hand.
        """
        assert self._billing is not None
        customer_id = profile.get("stripe_customer_id")
        if not customer_id:
            return
        try:
            self._billing.delete_customer(str(customer_id))
        except Exception:
            logger.warning(
                "Account deleted but Stripe customer %s remains — remove it manually",
                customer_id,
                exc_info=True,
            )
