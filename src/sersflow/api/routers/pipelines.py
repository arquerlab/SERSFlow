from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from sersflow.api.schemas.pipelines import (
    PipelineCreateRequest,
    PipelineCreateResponse,
    PipelineExportPackage,
    PipelineGetResponse,
    PipelineImportRequest,
    PipelineImportResponse,
    PipelineLibraryItem,
    PipelineListResponse,
    PipelineUpdateRequest,
    PipelineUpdateResponse,
)
from sersflow.api.services.pipeline_export import export_pipeline_package, import_pipeline_package
from sersflow.infra.pipelines_store import (
    create_pipeline,
    delete_pipeline,
    get_pipeline,
    list_pipelines,
    update_pipeline,
)


router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


def _to_item(rec) -> PipelineLibraryItem:
    return PipelineLibraryItem(
        pipeline_id=rec.pipeline_id,
        name=rec.name,
        pipeline=rec.pipeline,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.post("", response_model=PipelineCreateResponse)
def create_pipeline_endpoint(
    payload: PipelineCreateRequest,
    overwrite: bool = Query(False, description="If true, replace pipeline JSON for an existing entry with the same name"),
) -> dict[str, Any]:
    try:
        rec = create_pipeline(name=payload.name, pipeline=payload.pipeline, overwrite=overwrite)
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


@router.get("/{pipeline_id}/export", response_model=PipelineExportPackage)
def export_pipeline_endpoint(pipeline_id: str) -> Response:
    rec = get_pipeline(pipeline_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    pkg = export_pipeline_package(rec)
    filename = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in rec.name)
    if not filename:
        filename = pipeline_id
    return Response(
        content=json.dumps(pkg.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}.sersflow-pipeline.json"'},
    )


@router.post("/import", response_model=PipelineImportResponse)
def import_pipeline_endpoint(payload: PipelineImportRequest) -> dict[str, Any]:
    if payload.schema_version != "sersflow.pipeline.v1":
        raise HTTPException(status_code=400, detail=f"Unsupported pipeline package schema: {payload.schema_version}")
    try:
        rec = import_pipeline_package(name=payload.name, pipeline=payload.pipeline)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"item": _to_item(rec)}


@router.put("/{pipeline_id}", response_model=PipelineUpdateResponse)
def update_pipeline_endpoint(pipeline_id: str, payload: PipelineUpdateRequest) -> dict[str, Any]:
    try:
        rec = update_pipeline(pipeline_id=pipeline_id, name=payload.name, pipeline=payload.pipeline)
    except ValueError as e:
        msg = str(e)
        if "already exists" in msg.lower():
            raise HTTPException(status_code=409, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
    if rec is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"item": _to_item(rec)}


@router.delete("/{pipeline_id}")
def delete_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    ok = delete_pipeline(pipeline_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"deleted": True}
