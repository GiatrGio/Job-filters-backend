"""Monthly quota tracking.

Only counts actual LLM calls — cache hits are free. The per-user limit is read
from the `profiles` row so we can bump individual users without a deploy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.db.client import SupabaseDB


@dataclass
class QuotaStatus:
    used: int
    limit: int
    period: str

    @property
    def exceeded(self) -> bool:
        return self.used >= self.limit


def current_period() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


class QuotaService:
    def __init__(self, db: SupabaseDB, default_limit: int) -> None:
        self._db = db
        self._default_limit = default_limit

    def _fetch_limit(self, user_id: str) -> int:
        resp = (
            self._db.table("profiles")
            .select("monthly_eval_limit")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        if data and data[0].get("monthly_eval_limit") is not None:
            return int(data[0]["monthly_eval_limit"])
        return self._default_limit

    def _fetch_used(self, user_id: str, period: str) -> int:
        resp = (
            self._db.table("usage_counters")
            .select("evaluations_used")
            .eq("user_id", user_id)
            .eq("year_month", period)
            .limit(1)
            .execute()
        )
        data = resp.data or []
        if not data:
            return 0
        return int(data[0].get("evaluations_used") or 0)

    def status(self, user_id: str) -> QuotaStatus:
        period = current_period()
        return QuotaStatus(
            used=self._fetch_used(user_id, period),
            limit=self._fetch_limit(user_id),
            period=period,
        )

    def increment(self, user_id: str) -> QuotaStatus:
        """Bump the counter for the current period by 1. Returns the new status.

        Delegates to the `increment_usage` Postgres function (migration 0002)
        so the read-modify-write is one atomic transaction — two concurrent
        requests for the same user can't collide into the same counter value.
        """
        period = current_period()
        resp = self._db.rpc(
            "increment_usage",
            {"p_user_id": user_id, "p_year_month": period},
        ).execute()
        new_used = int(resp.data) if resp.data is not None else 0
        limit = self._fetch_limit(user_id)
        return QuotaStatus(used=new_used, limit=limit, period=period)
