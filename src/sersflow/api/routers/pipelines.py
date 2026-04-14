from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from sersflow.api.schemas.pipelines import (
    PipelineCreateRequest,
    PipelineCreateResponse,
    PipelineGetResponse,
    PipelineLibraryItem,
    PipelineListResponse,
)
from sersflow.infra.pipelines_store import create_pipeline, delete_pipeline, get_pipeline, list_pipelines


router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _to_item(rec) -> PipelineLibraryItem:
    return PipelineLibraryItem(
        pipeline_id=rec.pipeline_id,
        name=rec.name,
        pipeline=rec.pipeline,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.post("", response_model=PipelineCreateResponse)
def create_pipeline_endpoint(payload: PipelineCreateRequest) -> dict[str, Any]:
    try:
        rec = create_pipeline(name=payload.name, pipeline=payload.pipeline)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"item": _to_item(rec)}


@router.get("", response_model=PipelineListResponse)
def list_pipelines_endpoint(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Optional substring filter on name"),
) -> dict[str, Any]:
    rows = list_pipelines(limit=limit, offset=offset, q=q)
    items = [_to_item(r) for r in rows]
    return {"items": items, "count": len(items)}


@router.get("/{pipeline_id}", response_model=PipelineGetResponse)
def get_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    rec = get_pipeline(pipeline_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"item": _to_item(rec)}


@router.delete("/{pipeline_id}")
def delete_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    ok = delete_pipeline(pipeline_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"deleted": True}
