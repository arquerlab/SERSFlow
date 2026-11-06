"""Survey region sets (X2): named lists of element-line windows. Export as JSON or CSV."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from sersflow.api.deps import current_user_id
from sersflow.infra.xps_region_set_store import (
    create_region_set,
    delete_region_set,
    get_region_set,
    list_region_sets,
    region_set_csv,
)

router = APIRouter(prefix="/xps/region-sets", tags=["XPS"])


class RegionSetCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    regions: list[dict[str, Any]] = Field(min_length=1)
    notes: str = ""
    source: dict[str, Any] = Field(default_factory=dict, description="dataset_id, spectrum_id, detection settings, ...")


@router.get("")
def list_sets(request: Request) -> dict[str, Any]:
    items = list_region_sets(owner_user_id=current_user_id(request))
    return {"count": len(items), "items": [s.public() for s in items]}


@router.post("")
def create_set(payload: RegionSetCreateRequest, request: Request) -> dict[str, Any]:
    try:
        rs = create_region_set(
            owner_user_id=current_user_id(request),
            name=payload.name,
            regions=payload.regions,
            source=payload.source,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return rs.public()


@router.get("/{set_id}", response_model=None)
def get_set(set_id: str, request: Request, format: str = Query(default="json", pattern="^(json|csv)$")):
    rs = get_region_set(set_id, owner_user_id=current_user_id(request))
    if rs is None:
        raise HTTPException(status_code=404, detail="Region set not found")
    if format == "csv":
        return PlainTextResponse(
            region_set_csv(rs),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="region_set_{set_id}.csv"'},
        )
    return rs.public()


@router.delete("/{set_id}")
def delete_set(set_id: str, request: Request) -> dict[str, Any]:
    if not delete_region_set(set_id, owner_user_id=current_user_id(request)):
        raise HTTPException(status_code=404, detail="Region set not found")
    return {"deleted": True}
