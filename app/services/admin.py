from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.db.client import SupabaseDB
from app.schemas.admin import LLMCallRange, Plan
from app.services.llm_calls import pricing_catalog
from app.services.quota import current_period

logger = logging.getLogger(__name__)

FREE_PLAN: Plan = "free"
PRO_PLAN: Plan = "pro"
LLM_CALL_RANGE_DELTAS: dict[LLMCallRange, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class AuthAdminGateway(Protocol):
    def list_users(self) -> list[dict[str, Any]]:
        ...

    def delete_user(self, user_id: str) -> None:
        ...


class SupabaseAuthAdminGateway:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.supabase_url.rstrip("/")
        self._secret_key = settings.supabase_secret_key

    def list_users(self) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        page = 1
        per_page = 1000

        while True:
            data = self._request(
                "GET",
                "/auth/v1/admin/users",
                params={"page": page, "per_page": per_page},
            )
            batch = data if isinstance(data, list) else data.get("users", [])
            if not isinstance(batch, list):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Supabase returned an unexpected users payload",
                )

            users.extend([user for user in batch if isinstance(user, dict)])
            if len(batch) < per_page:
                break
            page += 1

        return users

    def delete_user(self, user_id: str) -> None:
        self._request("DELETE", f"/auth/v1/admin/users/{user_id}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            with httpx.Client(
                base_url=self._url,
                headers={
                    "apikey": self._secret_key,
                    "Authorization": f"Bearer {self._secret_key}",
                },
                timeout=20.0,
            ) as client:
                response = client.request(method, path, params=params)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            try:
                body = exc.response.json()
                detail = body.get("msg") or body.get("message") or body.get("error") or detail
            except ValueError:
                pass
            logger.warning(
                "Supabase admin request failed method=%s path=%s status=%s detail=%s",
                method,
                path,
                exc.response.status_code,
                detail,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Supabase admin request failed: {detail}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Supabase admin request failed: {exc}",
            ) from exc

        if response.status_code == status.HTTP_204_NO_CONTENT:
            return {}
        if not response.content:
            return {}
        return response.json()


class AdminService:
    def __init__(self, db: SupabaseDB, settings: Settings, auth_admin: AuthAdminGateway) -> None:
        self._db = db
        self._settings = settings
        self._auth_admin = auth_admin

    def list_users(self) -> list[dict[str, Any]]:
        profile_by_id = self._profiles_by_id()
        period = current_period()
        usage_by_user_id = self._usage_by_user_id(period)
        tracked_jobs_by_user_id = self._tracked_jobs_count_by_user_id()
        users = []
        for user in self._auth_admin.list_users():
            user_id = str(user.get("id") or "")
            if not user_id:
                continue
            users.append(
                self._serialize_user(
                    user,
                    profile_by_id.get(user_id),
                    usage_by_user_id.get(user_id),
                    tracked_jobs_by_user_id.get(user_id, 0),
                    period,
                )
            )

        return sorted(users, key=lambda row: (row["created_at"] or "", row["email"] or ""))

    def update_plan(self, user_id: str, plan: Plan) -> dict[str, Any]:
        patch = {"id": user_id, **self._plan_patch(plan)}
        resp = self._db.table("profiles").upsert(patch, on_conflict="id").execute()
        rows = resp.data or []
        profile = rows[0] if rows else patch

        auth_user = next(
            (user for user in self._auth_admin.list_users() if str(user.get("id")) == user_id),
            {"id": user_id},
        )
        period = current_period()
        usage = self._usage_by_user_id(period).get(user_id)
        tracked_jobs_count = self._tracked_jobs_count_by_user_id().get(user_id, 0)
        return self._serialize_user(auth_user, profile, usage, tracked_jobs_count, period)

    def delete_user(self, user_id: str) -> None:
        self._auth_admin.delete_user(user_id)

    def list_llm_calls(self, range_key: LLMCallRange) -> list[dict[str, Any]]:
        cutoff = _cutoff_iso(range_key)
        email_by_user_id = self._email_by_user_id()
        resp = (
            self._db.table("llm_calls")
            .select(
                "id,user_id,call_type,provider,model,status,source,external_id,"
                "summary,tokens_input,tokens_output,cost_usd_micros,duration_ms,created_at"
            )
            .gte("created_at", cutoff)
            .execute()
        )
        rows = [self._serialize_llm_call(row, email_by_user_id) for row in (resp.data or [])]
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def get_llm_call(self, call_id: str) -> dict[str, Any] | None:
        resp = self._db.table("llm_calls").select("*").eq("id", call_id).limit(1).execute()
        rows = resp.data or []
        if not rows:
            return None
        return self._serialize_llm_call(rows[0], self._email_by_user_id(), include_detail=True)

    def delete_llm_call(self, call_id: str) -> bool:
        resp = self._db.table("llm_calls").delete().eq("id", call_id).execute()
        return bool(resp.data)

    def delete_llm_calls_older_than(self, range_key: LLMCallRange) -> int:
        cutoff = _cutoff_iso(range_key)
        resp = self._db.table("llm_calls").delete().lt("created_at", cutoff).execute()
        return len(resp.data or [])

    def get_llm_pricing(self) -> dict[str, Any]:
        return {
            "active_provider": self._settings.llm_provider,
            "active_model": _active_model(self._settings),
            "fetched_at": datetime.now(UTC).isoformat(),
            "models": pricing_catalog(self._settings),
        }

    def _profiles_by_id(self) -> dict[str, dict[str, Any]]:
        resp = (
            self._db.table("profiles")
            .select("id,plan,monthly_eval_limit,created_at")
            .execute()
        )
        return {str(row["id"]): row for row in (resp.data or []) if row.get("id")}

    def _usage_by_user_id(self, period: str) -> dict[str, dict[str, Any]]:
        resp = (
            self._db.table("usage_counters")
            .select("user_id,evaluations_used")
            .eq("year_month", period)
            .execute()
        )
        return {str(row["user_id"]): row for row in (resp.data or []) if row.get("user_id")}

    def _tracked_jobs_count_by_user_id(self) -> dict[str, int]:
        resp = self._db.table("applications").select("user_id").execute()
        counts: dict[str, int] = {}
        for row in resp.data or []:
            user_id = row.get("user_id")
            if not user_id:
                continue
            key = str(user_id)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _email_by_user_id(self) -> dict[str, str]:
        return {
            str(user["id"]): str(user["email"])
            for user in self._auth_admin.list_users()
            if user.get("id") and user.get("email")
        }

    def _serialize_user(
        self,
        auth_user: dict[str, Any],
        profile: dict[str, Any] | None,
        usage: dict[str, Any] | None,
        tracked_jobs_count: int,
        period: str,
    ) -> dict[str, Any]:
        user_id = str(auth_user.get("id"))
        plan = _normalize_plan(profile.get("plan") if profile else None)
        return {
            "id": user_id,
            "email": auth_user.get("email"),
            "plan": plan,
            "evaluations_used": _int_or_default(
                usage.get("evaluations_used") if usage else None,
                0,
            ),
            "monthly_eval_limit": _int_or_default(
                profile.get("monthly_eval_limit") if profile else None,
                self._plan_patch(plan)["monthly_eval_limit"],
            ),
            "tracked_jobs_count": tracked_jobs_count,
            "usage_period": period,
            "created_at": auth_user.get("created_at") or (profile or {}).get("created_at"),
            "last_sign_in_at": auth_user.get("last_sign_in_at"),
        }

    def _serialize_llm_call(
        self,
        row: dict[str, Any],
        email_by_user_id: dict[str, str],
        *,
        include_detail: bool = False,
    ) -> dict[str, Any]:
        user_id = str(row["user_id"]) if row.get("user_id") else None
        out = {
            "id": str(row["id"]),
            "user_email": email_by_user_id.get(user_id or ""),
            "call_type": str(row["call_type"]),
            "provider": str(row["provider"]),
            "model": str(row["model"]),
            "status": str(row["status"]),
            "source": row.get("source"),
            "external_id": row.get("external_id"),
            "summary": row.get("summary"),
            "tokens_input": _int_or_default(row.get("tokens_input"), 0),
            "tokens_output": _int_or_default(row.get("tokens_output"), 0),
            "cost_usd_micros": (
                _int_or_default(row.get("cost_usd_micros"), 0)
                if row.get("cost_usd_micros") is not None
                else None
            ),
            "duration_ms": (
                _int_or_default(row.get("duration_ms"), 0)
                if row.get("duration_ms") is not None
                else None
            ),
            "created_at": str(row["created_at"]),
        }
        if include_detail:
            out["prompt"] = row.get("prompt") or {}
            out["response"] = row.get("response")
            out["error"] = row.get("error")
        return out

    def _plan_patch(self, plan: Plan) -> dict[str, Any]:
        if plan == PRO_PLAN:
            return {
                "plan": PRO_PLAN,
                "monthly_eval_limit": self._settings.pro_monthly_eval_limit,
            }
        return {
            "plan": FREE_PLAN,
            "monthly_eval_limit": self._settings.free_tier_monthly_limit,
        }


def _normalize_plan(value: Any) -> Plan:
    return PRO_PLAN if value == PRO_PLAN else FREE_PLAN


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cutoff_iso(range_key: LLMCallRange) -> str:
    return (datetime.now(UTC) - LLM_CALL_RANGE_DELTAS[range_key]).isoformat()


def _active_model(settings: Settings) -> str:
    if settings.llm_provider == "openai":
        return settings.openai_model
    return settings.anthropic_model
