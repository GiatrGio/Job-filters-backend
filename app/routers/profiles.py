"""Filter profiles + the filters they contain.

A user has up to 5 profiles, each with up to 10 filters. Exactly one profile
is active at a time; /evaluate uses that profile's filters. All ordering and
caps are enforced server-side so the future website client gets identical
behavior without re-implementing rules.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUserDep, DBDep
from app.schemas.filter import FilterCreate, FilterOut, FilterUpdate
from app.schemas.profile import (
    MAX_FILTERS_PER_PROFILE,
    MAX_PROFILES_PER_USER,
    FilterProfileCreate,
    FilterProfileOut,
    FilterProfileUpdate,
    FilterProfileWithFilters,
    ReorderRequest,
)

router = APIRouter(tags=["profiles"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_profile(db, user_id: str, profile_id: str) -> dict:
    resp = (
        db.table("filter_profiles")
        .select("*")
        .eq("id", profile_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="profile not found")
    return rows[0]


def _list_profiles(db, user_id: str) -> list[dict]:
    resp = (
        db.table("filter_profiles")
        .select("*")
        .eq("user_id", user_id)
        .order("position")
        .execute()
    )
    return resp.data or []


def _list_filters(db, profile_id: str) -> list[dict]:
    resp = (
        db.table("filters")
        .select("*")
        .eq("profile_id", profile_id)
        .order("position")
        .execute()
    )
    return resp.data or []


# ---------------------------------------------------------------------------
# /profiles — CRUD + activate + reorder
# ---------------------------------------------------------------------------

@router.get("/profiles", response_model=list[FilterProfileWithFilters])
def list_profiles(user: CurrentUserDep, db: DBDep) -> list[FilterProfileWithFilters]:
    """Returns every profile with its filters embedded.

    The options page consumes this in one round trip; the side panel only
    needs the profile metadata but pays the same cost since N is small (≤5).
    """
    profiles = _list_profiles(db, user.id)
    out: list[FilterProfileWithFilters] = []
    for p in profiles:
        filters = _list_filters(db, p["id"])
        out.append(
            FilterProfileWithFilters(
                **p,
                filters=[FilterOut.model_validate(f) for f in filters],
            )
        )
    return out


@router.post(
    "/profiles",
    response_model=FilterProfileOut,
    status_code=status.HTTP_201_CREATED,
)
def create_profile(
    body: FilterProfileCreate,
    user: CurrentUserDep,
    db: DBDep,
) -> FilterProfileOut:
    existing = _list_profiles(db, user.id)
    if len(existing) >= MAX_PROFILES_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"profile limit reached ({MAX_PROFILES_PER_USER})",
        )
    next_position = max((p["position"] for p in existing), default=-1) + 1
    is_active = len(existing) == 0  # first profile is auto-active
    resp = (
        db.table("filter_profiles")
        .insert(
            {
                "user_id": user.id,
                "name": body.name,
                "position": next_position,
                "is_active": is_active,
            }
        )
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="insert returned no row")
    return FilterProfileOut.model_validate(rows[0])


@router.patch("/profiles/reorder", response_model=list[FilterProfileOut])
def reorder_profiles(
    body: ReorderRequest,
    user: CurrentUserDep,
    db: DBDep,
) -> list[FilterProfileOut]:
    existing = _list_profiles(db, user.id)
    existing_ids = {p["id"] for p in existing}
    if set(body.ids) != existing_ids:
        raise HTTPException(
            status_code=400,
            detail="reorder ids must match the user's profile set exactly",
        )
    for i, pid in enumerate(body.ids):
        db.table("filter_profiles").update({"position": i}).eq("id", pid).eq(
            "user_id", user.id
        ).execute()
    return [FilterProfileOut.model_validate(p) for p in _list_profiles(db, user.id)]


@router.patch("/profiles/{profile_id}", response_model=FilterProfileOut)
def update_profile(
    profile_id: str,
    body: FilterProfileUpdate,
    user: CurrentUserDep,
    db: DBDep,
) -> FilterProfileOut:
    patch = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not patch:
        raise HTTPException(status_code=400, detail="no fields to update")
    _load_profile(db, user.id, profile_id)  # 404 if not owned
    resp = (
        db.table("filter_profiles")
        .update(patch)
        .eq("id", profile_id)
        .eq("user_id", user.id)
        .execute()
    )
    rows = resp.data or []
    return FilterProfileOut.model_validate(rows[0])


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: str, user: CurrentUserDep, db: DBDep) -> None:
    profiles = _list_profiles(db, user.id)
    if len(profiles) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot delete the last profile",
        )
    target = next((p for p in profiles if p["id"] == profile_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="profile not found")

    db.table("filter_profiles").delete().eq("id", profile_id).eq(
        "user_id", user.id
    ).execute()

    if target["is_active"]:
        # Promote the next profile (by position) to active so the user always
        # has one active profile after this call.
        remaining = [p for p in profiles if p["id"] != profile_id]
        remaining.sort(key=lambda p: p["position"])
        new_active_id = remaining[0]["id"]
        db.table("filter_profiles").update({"is_active": True}).eq(
            "id", new_active_id
        ).eq("user_id", user.id).execute()
    return None


@router.post("/profiles/{profile_id}/activate", response_model=FilterProfileOut)
def activate_profile(profile_id: str, user: CurrentUserDep, db: DBDep) -> FilterProfileOut:
    target = _load_profile(db, user.id, profile_id)
    if target["is_active"]:
        return FilterProfileOut.model_validate(target)
    # Two-step: clear all is_active for this user, then set the target. Safe
    # under the "one active per user" partial unique index because we never
    # have two rows with is_active=true at once.
    db.table("filter_profiles").update({"is_active": False}).eq(
        "user_id", user.id
    ).execute()
    resp = (
        db.table("filter_profiles")
        .update({"is_active": True})
        .eq("id", profile_id)
        .eq("user_id", user.id)
        .execute()
    )
    rows = resp.data or []
    return FilterProfileOut.model_validate(rows[0])


# ---------------------------------------------------------------------------
# /profiles/{profile_id}/filters — list / create / reorder
# ---------------------------------------------------------------------------

@router.get(
    "/profiles/{profile_id}/filters",
    response_model=list[FilterOut],
)
def list_profile_filters(
    profile_id: str, user: CurrentUserDep, db: DBDep
) -> list[FilterOut]:
    _load_profile(db, user.id, profile_id)
    return [FilterOut.model_validate(r) for r in _list_filters(db, profile_id)]


@router.post(
    "/profiles/{profile_id}/filters",
    response_model=FilterOut,
    status_code=status.HTTP_201_CREATED,
)
def create_profile_filter(
    profile_id: str,
    body: FilterCreate,
    user: CurrentUserDep,
    db: DBDep,
) -> FilterOut:
    _load_profile(db, user.id, profile_id)
    existing = _list_filters(db, profile_id)
    if len(existing) >= MAX_FILTERS_PER_PROFILE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"filter limit reached ({MAX_FILTERS_PER_PROFILE})",
        )
    next_position = max((f["position"] for f in existing), default=-1) + 1
    resp = (
        db.table("filters")
        .insert(
            {
                "user_id": user.id,
                "profile_id": profile_id,
                "text": body.text,
                "position": next_position,
                "enabled": body.enabled,
            }
        )
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="insert returned no row")
    return FilterOut.model_validate(rows[0])


@router.patch(
    "/profiles/{profile_id}/filters/reorder",
    response_model=list[FilterOut],
)
def reorder_profile_filters(
    profile_id: str,
    body: ReorderRequest,
    user: CurrentUserDep,
    db: DBDep,
) -> list[FilterOut]:
    _load_profile(db, user.id, profile_id)
    existing = _list_filters(db, profile_id)
    existing_ids = {f["id"] for f in existing}
    if set(body.ids) != existing_ids:
        raise HTTPException(
            status_code=400,
            detail="reorder ids must match the profile's filter set exactly",
        )
    for i, fid in enumerate(body.ids):
        db.table("filters").update({"position": i}).eq("id", fid).eq(
            "profile_id", profile_id
        ).execute()
    return [FilterOut.model_validate(f) for f in _list_filters(db, profile_id)]


# ---------------------------------------------------------------------------
# /filters/{filter_id} — update / delete (profile-agnostic; scoped by user)
# ---------------------------------------------------------------------------

@router.patch("/filters/{filter_id}", response_model=FilterOut)
def update_filter(
    filter_id: str,
    body: FilterUpdate,
    user: CurrentUserDep,
    db: DBDep,
) -> FilterOut:
    patch = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not patch:
        raise HTTPException(status_code=400, detail="no fields to update")
    resp = (
        db.table("filters")
        .update(patch)
        .eq("id", filter_id)
        .eq("user_id", user.id)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="filter not found")
    return FilterOut.model_validate(rows[0])


@router.delete("/filters/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_filter(filter_id: str, user: CurrentUserDep, db: DBDep) -> None:
    resp = (
        db.table("filters")
        .delete()
        .eq("id", filter_id)
        .eq("user_id", user.id)
        .execute()
    )
    if not (resp.data or []):
        raise HTTPException(status_code=404, detail="filter not found")
    return None
