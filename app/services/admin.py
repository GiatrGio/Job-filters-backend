from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, status

from app.config import Settings
from app.db.client import SupabaseDB
from app.schemas.admin import Plan
from app.services.quota import current_period

logger = logging.getLogger(__name__)

FREE_PLAN: Plan = "free"
PRO_PLAN: Plan = "pro"


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
        return self._serialize_user(auth_user, profile, usage, period)

    def delete_user(self, user_id: str) -> None:
        self._auth_admin.delete_user(user_id)

    def _profiles_by_id(self) -> dict[str, dict[str, Any]]:
        resp = (
            self._db.table("profiles")
            .select("id,plan,monthly_eval_limit,monthly_cv_tailoring_limit,created_at")
            .execute()
        )
        return {str(row["id"]): row for row in (resp.data or []) if row.get("id")}

    def _usage_by_user_id(self, period: str) -> dict[str, dict[str, Any]]:
        resp = (
            self._db.table("usage_counters")
            .select("user_id,evaluations_used,cv_tailorings_used")
            .eq("year_month", period)
            .execute()
        )
        return {str(row["user_id"]): row for row in (resp.data or []) if row.get("user_id")}

    def _serialize_user(
        self,
        auth_user: dict[str, Any],
        profile: dict[str, Any] | None,
        usage: dict[str, Any] | None,
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
            "cv_tailorings_used": _int_or_default(
                usage.get("cv_tailorings_used") if usage else None,
                0,
            ),
            "monthly_cv_tailoring_limit": _int_or_default(
                profile.get("monthly_cv_tailoring_limit") if profile else None,
                self._plan_patch(plan)["monthly_cv_tailoring_limit"],
            ),
            "usage_period": period,
            "created_at": auth_user.get("created_at") or (profile or {}).get("created_at"),
            "last_sign_in_at": auth_user.get("last_sign_in_at"),
        }

    def _plan_patch(self, plan: Plan) -> dict[str, Any]:
        if plan == PRO_PLAN:
            return {
                "plan": PRO_PLAN,
                "monthly_eval_limit": self._settings.pro_monthly_eval_limit,
                "monthly_cv_tailoring_limit": self._settings.pro_monthly_cv_tailoring_limit,
            }
        return {
            "plan": FREE_PLAN,
            "monthly_eval_limit": self._settings.free_tier_monthly_limit,
            "monthly_cv_tailoring_limit": 0,
        }


def _normalize_plan(value: Any) -> Plan:
    return PRO_PLAN if value == PRO_PLAN else FREE_PLAN


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
