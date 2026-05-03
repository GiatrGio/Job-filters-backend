"""Per-application interview rounds service.

Stores `user_id` on every row so the future Calendar view can pull "all my
interviews this month" without joining through `applications`. See migration
0009 for the index that supports that path.
"""

from __future__ import annotations

from app.db.client import SupabaseDB
from app.schemas.interview import (
    ApplicationInterviewCreate,
    ApplicationInterviewUpdate,
)


def _isoformat(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class InterviewsService:
    def __init__(self, db: SupabaseDB) -> None:
        self._db = db

    def list_for_application(self, user_id: str, application_id: str) -> list[dict]:
        resp = (
            self._db.table("application_interviews")
            .select("*")
            .eq("user_id", user_id)
            .eq("application_id", application_id)
            .order("scheduled_at")
            .execute()
        )
        return resp.data or []

    def get(self, user_id: str, interview_id: str) -> dict | None:
        resp = (
            self._db.table("application_interviews")
            .select("*")
            .eq("id", interview_id)
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
        body: ApplicationInterviewCreate,
    ) -> dict:
        payload = {
            "application_id": application_id,
            "user_id": user_id,
            "title": body.title,
            "scheduled_at": _isoformat(body.scheduled_at),
            "duration_minutes": body.duration_minutes,
            "location": body.location,
            "interviewer": body.interviewer,
            "notes": body.notes,
            "outcome": body.outcome,
        }
        resp = self._db.table("application_interviews").insert(payload).execute()
        rows = resp.data or []
        if not rows:
            raise RuntimeError("insert returned no row")
        return rows[0]

    def update(
        self,
        user_id: str,
        interview_id: str,
        body: ApplicationInterviewUpdate,
    ) -> dict | None:
        patch: dict = {}
        for k, v in body.model_dump(exclude_unset=True).items():
            if k == "scheduled_at" and v is not None:
                patch[k] = _isoformat(v)
            else:
                patch[k] = v
        if not patch:
            return self.get(user_id, interview_id)
        resp = (
            self._db.table("application_interviews")
            .update(patch)
            .eq("id", interview_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def delete(self, user_id: str, interview_id: str) -> bool:
        resp = (
            self._db.table("application_interviews")
            .delete()
            .eq("id", interview_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(resp.data)
