"""Minimal in-memory stand-in for the Supabase query builder used in services.

Supports the subset of supabase-py's builder used by the evaluator/cache/quota/
filters router: `table(...).select(...).eq(...).order(...).limit(...).execute()`
plus `.insert(...)`, `.update(...)`, `.delete(...)`, `.upsert(..., on_conflict=...)`.

This is not a drop-in for supabase-py — it only implements what our code uses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class _Response:
    data: list[dict[str, Any]]


@dataclass
class _Query:
    store: FakeStore
    table_name: str
    filters: list[tuple[str, Any]] = field(default_factory=list)
    order_by: str | None = None
    limit_n: int | None = None
    op: str = "select"
    payload: Any = None
    on_conflict: str | None = None

    # --- builder methods -----------------------------------------------------
    def select(self, *_cols: str) -> _Query:
        self.op = "select"
        return self

    def insert(self, row: dict[str, Any]) -> _Query:
        self.op = "insert"
        self.payload = row
        return self

    def update(self, patch: dict[str, Any]) -> _Query:
        self.op = "update"
        self.payload = patch
        return self

    def delete(self) -> _Query:
        self.op = "delete"
        return self

    def upsert(self, row: dict[str, Any], on_conflict: str | None = None) -> _Query:
        self.op = "upsert"
        self.payload = row
        self.on_conflict = on_conflict
        return self

    def eq(self, column: str, value: Any) -> _Query:
        self.filters.append((column, value))
        return self

    def order(self, column: str) -> _Query:
        self.order_by = column
        return self

    def limit(self, n: int) -> _Query:
        self.limit_n = n
        return self

    # --- execution -----------------------------------------------------------
    def _matches(self, row: dict[str, Any]) -> bool:
        return all(row.get(c) == v for c, v in self.filters)

    def execute(self) -> _Response:
        rows = self.store.tables.setdefault(self.table_name, [])

        if self.op == "select":
            out = [r for r in rows if self._matches(r)]
            if self.order_by:
                out.sort(key=lambda r: r.get(self.order_by))
            if self.limit_n is not None:
                out = out[: self.limit_n]
            return _Response(data=out)

        if self.op == "insert":
            new_row = dict(self.payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            now = datetime.now(timezone.utc).isoformat()
            new_row.setdefault("created_at", now)
            new_row.setdefault("updated_at", now)
            rows.append(new_row)
            return _Response(data=[new_row])

        if self.op == "update":
            updated: list[dict[str, Any]] = []
            for r in rows:
                if self._matches(r):
                    r.update(self.payload)
                    r["updated_at"] = datetime.now(timezone.utc).isoformat()
                    updated.append(r)
            return _Response(data=updated)

        if self.op == "delete":
            kept: list[dict[str, Any]] = []
            removed: list[dict[str, Any]] = []
            for r in rows:
                (removed if self._matches(r) else kept).append(r)
            self.store.tables[self.table_name] = kept
            return _Response(data=removed)

        if self.op == "upsert":
            key_cols = [c.strip() for c in (self.on_conflict or "id").split(",")]
            for r in rows:
                if all(r.get(k) == self.payload.get(k) for k in key_cols):
                    r.update(self.payload)
                    return _Response(data=[r])
            new_row = dict(self.payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            rows.append(new_row)
            return _Response(data=[new_row])

        raise RuntimeError(f"unsupported op {self.op!r}")


class FakeStore:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def seed(self, table: str, rows: list[dict[str, Any]]) -> None:
        self.tables.setdefault(table, []).extend(rows)


@dataclass
class _Rpc:
    store: FakeStore
    name: str
    params: dict[str, Any]

    def execute(self) -> _Response:
        if self.name == "increment_usage":
            return self._increment_counter("evaluations_used")
        if self.name == "increment_filter_validation_usage":
            return self._increment_counter("filter_validations_used")
        raise RuntimeError(f"unknown rpc {self.name!r}")

    def _increment_counter(self, column: str) -> _Response:
        user_id = self.params["p_user_id"]
        period = self.params["p_year_month"]
        rows = self.store.tables.setdefault("usage_counters", [])
        for r in rows:
            if r.get("user_id") == user_id and r.get("year_month") == period:
                r[column] = int(r.get(column, 0)) + 1
                return _Response(data=r[column])
        rows.append({"user_id": user_id, "year_month": period, column: 1})
        return _Response(data=1)


class FakeDB:
    def __init__(self, store: FakeStore | None = None) -> None:
        self.store = store or FakeStore()

    def table(self, name: str) -> _Query:
        return _Query(store=self.store, table_name=name)

    def rpc(self, name: str, params: dict[str, Any]) -> _Rpc:
        return _Rpc(store=self.store, name=name, params=params)
