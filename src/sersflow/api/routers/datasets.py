from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile

from sersflow.api.schemas.datasets import (
    DatasetCreateRequest,
    DatasetCreateResponse,
    DatasetGetResponse,
    DatasetImportResponse,
    DatasetListResponse,
    DatasetRestoreUploadsRequest,
    DatasetRestoreUploadsResponse,
    SkippedUpload,
)
from sersflow.api.schemas.metrics import DatasetMetricsRequest, DatasetMetricsResponse
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.services.dataset_export import export_dataset_package, import_dataset_package
from sersflow.api.services.dataset_restore import restore_dataset_uploads
from sersflow.api.services.datasets_service import create_dataset_from_uploads
from sersflow.core.metrics.compute import compute_metrics
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.infra.datasets_store import (
    delete_all_datasets,
    delete_dataset,
    get_dataset,
    iter_spectrum_axes_page,
    list_datasets,
    to_schema,
)
from sersflow.infra.sessions_store import delete_all_sessions, delete_sessions_for_dataset


router = APIRouter(prefix="/datasets", tags=["Datasets"])
_cache = InProcessLRUCache(max_items=4096)


@router.post("", response_model=DatasetCreateResponse)
def create_dataset(payload: DatasetCreateRequest) -> dict[str, Any]:
    try:
        rec, skipped = create_dataset_from_uploads(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "dataset": to_schema(rec),
        "skipped_files": [SkippedUpload(**s) for s in skipped],
    }


@router.get("", response_model=DatasetListResponse)
def list_datasets_endpoint(
    response: Response,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    items = list_datasets(limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


@router.get("/{dataset_id}", response_model=DatasetGetResponse)
def get_dataset_endpoint(dataset_id: str) -> dict[str, Any]:
    rec = get_dataset(dataset_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"dataset": to_schema(rec)}


@router.post("/{dataset_id}/restore-uploads", response_model=DatasetRestoreUploadsResponse)
def restore_dataset_uploads_endpoint(
    dataset_id: str,
    payload: DatasetRestoreUploadsRequest | None = None,
) -> DatasetRestoreUploadsResponse:
    rec = get_dataset(dataset_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return restore_dataset_uploads(rec, force_copy=bool(payload.force_copy) if payload else False)


@router.get("/{dataset_id}/export")
def export_dataset_endpoint(dataset_id: str) -> Response:
    try:
        payload, filename = export_dataset_package(dataset_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Dataset not found") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=DatasetImportResponse)
async def import_dataset_endpoint(file: UploadFile = File(...)) -> DatasetImportResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Dataset package file is required")
    try:
        data = await file.read()
        return import_dataset_package(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        try:
            await file.close()
        except Exception:
            pass


@router.get("/{dataset_id}/spectrum-axes")
def list_spectrum_axes(
    dataset_id: str,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """
    Paginated spectrum rows with spatial/temporal axes and per-file grid metadata (for maps/series).
    """
    if get_dataset(dataset_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    items, total = iter_spectrum_axes_page(dataset_id=dataset_id, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.delete("/{dataset_id}")
def delete_dataset_endpoint(dataset_id: str) -> dict[str, Any]:
    deleted = delete_dataset(dataset_id)
    # sessions table has no FK, so cleanup explicitly
    sessions_deleted = delete_sessions_for_dataset(dataset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"deleted": True, "sessions_deleted": sessions_deleted}


@router.delete("")
def clear_all_datasets_endpoint() -> dict[str, Any]:
    sessions_deleted = delete_all_sessions()
    datasets_deleted = delete_all_datasets()
    return {"deleted": True, "datasets_deleted": datasets_deleted, "sessions_deleted": sessions_deleted}


@router.post("/{dataset_id}/metrics", response_model=DatasetMetricsResponse)
def compute_dataset_metrics(dataset_id: str, payload: DatasetMetricsRequest) -> dict[str, Any]:
    rec = get_dataset(dataset_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    pipeline = payload.pipeline or Pipeline(steps=[])
    cfg = EngineConfig(cache_namespace=payload.cache_namespace or dataset_id)
    final = run_pipeline(inputs=rec.spectra, pipeline=pipeline, cache=_cache, config=cfg)

    rows = []
    for sid, xy in final.items():
        ms = compute_metrics(xy, payload.metrics)
        rows.append({"spectrum_id": sid, "values": [m.value for m in ms]})
    return {"metric_names": payload.metrics, "rows": rows}

