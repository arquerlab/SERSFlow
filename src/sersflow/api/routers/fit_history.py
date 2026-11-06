"""Fit history (X1): STORE / RECALL / RESET of fitting-step model states. Per user and scope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from sersflow.api.deps import current_user_id
from sersflow.infra.fit_history_store import (
    add_snapshot,
    clear_unpinned,
    compare_snapshots,
    delete_snapshot,
    get_snapshot,
    list_snapshots,
    update_snapshot,
)

router = APIRouter(prefix="/fitting/history", tags=["fitting-history"])


class HistoryAddRequest(BaseModel):
    scope_key: str = Field(min_length=1, description="Identifies the fitting step, e.g. '<dataset>|<region>|<step>'.")
    params: dict[str, Any] = Field(description="The fitting step params (components, p0, bounds, vary, links, window).")
    summary: dict[str, Any] = Field(default_factory=dict, description="Fit stats: chi2, redchi, rmse, area_pct per component.")
    label: str = ""
    pinned: bool = False


class HistoryUpdateRequest(BaseModel):
    label: str | None = None
    pinned: bool | None = None


@router.get("")
def list_history(
    request: Request,
    scope_key: str = Query(..., min_length=1),
    include_params: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = list_snapshots(owner_user_id=current_user_id(request), scope_key=scope_key, limit=limit)
    return {"scope_key": scope_key, "count": len(items), "items": [s.public(include_params=include_params) for s in items]}


@router.post("")
def add_history(payload: HistoryAddRequest, request: Request) -> dict[str, Any]:
    try:
        snap, created = add_snapshot(
            owner_user_id=current_user_id(request),
            scope_key=payload.scope_key,
            params=payload.params,
            summary=payload.summary,
            label=payload.label,
            pinned=payload.pinned,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"created": created, **snap.public()}


@router.get("/compare")
def compare_history(a: str, b: str, request: Request) -> dict[str, Any]:
    uid = current_user_id(request)
    sa, sb = get_snapshot(a, owner_user_id=uid), get_snapshot(b, owner_user_id=uid)
    if sa is None or sb is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    try:
        return compare_snapshots(sa, sb)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{history_id}")
def get_history(history_id: str, request: Request) -> dict[str, Any]:
    snap = get_snapshot(history_id, owner_user_id=current_user_id(request))
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snap.public()


@router.patch("/{history_id}")
def patch_history(history_id: str, payload: HistoryUpdateRequest, request: Request) -> dict[str, Any]:
    snap = update_snapshot(history_id, owner_user_id=current_user_id(request), label=payload.label, pinned=payload.pinned)
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snap.public(include_params=False)


@router.delete("")
def clear_history(request: Request, scope_key: str = Query(..., min_length=1)) -> dict[str, Any]:
    """RESET: drop every unpinned snapshot of the scope (named snapshots stay)."""
    return {"deleted": clear_unpinned(owner_user_id=current_user_id(request), scope_key=scope_key)}


@router.delete("/{history_id}")
def delete_history(history_id: str, request: Request) -> dict[str, Any]:
    if not delete_snapshot(history_id, owner_user_id=current_user_id(request)):
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"deleted": True}
