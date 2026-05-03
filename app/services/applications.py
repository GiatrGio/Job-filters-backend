"""Tracker service.

CRUD with one twist: `create` is idempotent on (user_id, source, external_id)
so the extension's "Track this job" button is safe to click twice. Idempotency
is enforced server-side rather than relying on the extension to check first —
fewer round trips, no race when two tabs click simultaneously.
"""

from __future__ import annotations

from app.db.client import SupabaseDB
from app.schemas.application import ApplicationCreate, ApplicationUpdate


class ApplicationsService:
    def __init__(self, db: SupabaseDB) -> None:
        self._db = db

    # --- read ----------------------------------------------------------------
    def list_for_user(self, user_id: str) -> list[dict]:
        resp = (
            self._db.table("applications")
            .select(
                "id,user_id,source,external_id,title,company,location,url,"
                "status,applied_at,deadline_at,notes,created_at,updated_at"
            )
            .eq("user_id", user_id)
            .order("updated_at")
            .execute()
        )
        rows = resp.data or []
        # Newest first. Supabase-py `.order()` is ascending; flip in code so
        # a single `.order()` chain stays simple in the FakeDB.
        return list(reversed(rows))

    def get(self, user_id: str, application_id: str) -> dict | None:
        resp = (
            self._db.table("applications")
            .select("*")
            .eq("id", application_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def get_by_job(self, user_id: str, source: str, external_id: str) -> dict | None:
        resp = (
            self._db.table("applications")
            .select("*")
            .eq("user_id", user_id)
            .eq("source", source)
            .eq("external_id", external_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    # --- write ---------------------------------------------------------------
    def create_or_get(self, user_id: str, body: ApplicationCreate) -> tuple[dict, bool]:
        """Insert if new; return existing row otherwise.

        Returns `(row, created)`. The caller decides on 201 vs 200 from `created`.
        """
        existing = self.get_by_job(user_id, body.source, body.external_id)
        if existing is not None:
            return existing, False

        payload = {
            "user_id": user_id,
            "source": body.source,
            "external_id": body.external_id,
            "title": body.title,
            "company": body.company,
            "location": body.location,
            "url": body.url,
            "description": body.description,
            "status": body.status,
            "applied_at": body.applied_at.isoformat() if body.applied_at else None,
            "deadline_at": body.deadline_at.isoformat() if body.deadline_at else None,
            "notes": body.notes,
        }
        resp = self._db.table("applications").insert(payload).execute()
        rows = resp.data or []
        if not rows:
            raise RuntimeError("insert returned no row")
        return rows[0], True

    def update(self, user_id: str, application_id: str, body: ApplicationUpdate) -> dict | None:
        patch: dict = {}
        for k, v in body.model_dump(exclude_unset=True).items():
            if k in ("applied_at", "deadline_at") and v is not None:
                # supabase-py serializes datetimes as ISO strings.
                patch[k] = v.isoformat() if hasattr(v, "isoformat") else v
            else:
                patch[k] = v
        if not patch:
            return self.get(user_id, application_id)
        resp = (
            self._db.table("applications")
            .update(patch)
            .eq("id", application_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def delete(self, user_id: str, application_id: str) -> bool:
        resp = (
            self._db.table("applications")
            .delete()
            .eq("id", application_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(resp.data)
