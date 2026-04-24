from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUserDep, DBDep
from app.schemas.filter import FilterCreate, FilterOut, FilterUpdate

router = APIRouter(prefix="/filters", tags=["filters"])


@router.get("", response_model=list[FilterOut])
def list_filters(user: CurrentUserDep, db: DBDep) -> list[FilterOut]:
    resp = (
        db.table("filters")
        .select("*")
        .eq("user_id", user.id)
        .order("position")
        .execute()
    )
    return [FilterOut.model_validate(r) for r in (resp.data or [])]


@router.post("", response_model=FilterOut, status_code=status.HTTP_201_CREATED)
def create_filter(
    body: FilterCreate,
    user: CurrentUserDep,
    db: DBDep,
) -> FilterOut:
    resp = (
        db.table("filters")
        .insert(
            {
                "user_id": user.id,
                "text": body.text,
                "position": body.position,
                "enabled": body.enabled,
            }
        )
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="insert returned no row")
    return FilterOut.model_validate(rows[0])


@router.patch("/{filter_id}", response_model=FilterOut)
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


@router.delete("/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_filter(
    filter_id: str,
    user: CurrentUserDep,
    db: DBDep,
) -> None:
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
