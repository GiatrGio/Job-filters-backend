"""Per-application contacts service.

All operations are scoped to the caller via `user_id`. The router checks
parent-application ownership before invoking `list/create`; per-row updates
and deletes also include `user_id` in their `eq` clauses as defence in depth
in case a router ever forgets the parent check.
"""

from __future__ import annotations

from app.db.client import SupabaseDB
from app.schemas.contact import (
    ApplicationContactCreate,
    ApplicationContactUpdate,
)


class ContactsService:
    def __init__(self, db: SupabaseDB) -> None:
        self._db = db

    def list_for_application(self, user_id: str, application_id: str) -> list[dict]:
        resp = (
            self._db.table("application_contacts")
            .select("*")
            .eq("user_id", user_id)
            .eq("application_id", application_id)
            .order("created_at")
            .execute()
        )
        return resp.data or []

    def get(self, user_id: str, contact_id: str) -> dict | None:
        resp = (
            self._db.table("application_contacts")
            .select("*")
            .eq("id", contact_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def create(
        self,
        user_id: str,
        application_id: str,
        body: ApplicationContactCreate,
    ) -> dict:
        payload = {
            "application_id": application_id,
            "user_id": user_id,
            "name": body.name,
            "role": body.role,
            "email": body.email,
            "linkedin_url": body.linkedin_url,
            "notes": body.notes,
        }
        resp = self._db.table("application_contacts").insert(payload).execute()
        rows = resp.data or []
        if not rows:
            raise RuntimeError("insert returned no row")
        return rows[0]

    def update(
        self,
        user_id: str,
        contact_id: str,
        body: ApplicationContactUpdate,
    ) -> dict | None:
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            return self.get(user_id, contact_id)
        resp = (
            self._db.table("application_contacts")
            .update(patch)
            .eq("id", contact_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def delete(self, user_id: str, contact_id: str) -> bool:
        resp = (
            self._db.table("application_contacts")
            .delete()
            .eq("id", contact_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(resp.data)
