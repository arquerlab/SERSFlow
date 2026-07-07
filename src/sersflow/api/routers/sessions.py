from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, Request

from sersflow.api.deps import current_user_id
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionGetResponse,
    SessionListItem,
    SessionListResponse,
    SessionPipelineUpdateRequest,
    SessionPipelineUpdateResponse,
    SessionRunRequest,
    SessionRunReturnFinal,
    SessionRunReturnIntermediates,
    SessionRunReturnMetricsOnly,
    SessionSubsetUpdateResponse,
    SubsetStrategy,
)
from sersflow.api.services.ownership import get_dataset_for_user, get_session_for_user
from sersflow.api.services.reference_runtime import filter_reference_spectra, hydrate_reference_transforms
from sersflow.api.services.sessions_service import pipeline_hash, resolve_subset_indices, subset_hash
from sersflow.core.metrics.compute import compute_metrics
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import (
    EngineConfig,
    run_pipeline,
    run_pipeline_parallel_no_cache,
    run_pipeline_with_intermediates,
)
from sersflow.infra.sessions_store import (
    create_session,
    list_sessions_for_dataset,
    to_schema,
    update_session_pipeline,
    update_session_subset,
)


router = APIRouter(prefix="/sessions", tags=["Sessions"])
_cache = InProcessLRUCache(max_items=4096)
SESSION_MAX_WORKERS = 8


@router.get("", response_model=SessionListResponse)
def list_sessions_for_dataset_endpoint(
    request: Request,
    dataset_id: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
) -> SessionListResponse:
    user_id = current_user_id(request)
    ds = get_dataset_for_user(dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    rows = list_sessions_for_dataset(dataset_id=dataset_id, limit=limit)
    items = [
        SessionListItem(
            session_id=r.session_id,
            dataset_id=r.dataset_id,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return SessionListResponse(items=items, count=len(items))


@router.post("", response_model=SessionCreateResponse)
def create_session_endpoint(payload: SessionCreateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    ds = get_dataset_for_user(payload.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    pipeline = payload.pipeline or Pipeline(steps=[])
    subset = payload.subset or SubsetStrategy(kind="all")
    rec = create_session(dataset_id=payload.dataset_id, pipeline=pipeline, subset=subset)
    return {"session": to_schema(rec)}


@router.get("/{session_id}", response_model=SessionGetResponse)
def get_session_endpoint(session_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    rec = get_session_for_user(session_id, user_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": to_schema(rec)}


@router.put("/{session_id}/pipeline", response_model=SessionPipelineUpdateResponse)
def update_pipeline_endpoint(
    session_id: str,
    payload: SessionPipelineUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    if get_session_for_user(session_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    rec = update_session_pipeline(session_id, payload.pipeline)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"pipeline": rec.pipeline, "pipeline_hash": pipeline_hash(rec.pipeline)}


@router.post("/{session_id}/subset", response_model=SessionSubsetUpdateResponse)
def update_subset_endpoint(session_id: str, payload: SubsetStrategy, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    if get_session_for_user(session_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    rec = update_session_subset(session_id, payload)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ds = get_dataset_for_user(rec.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    runtime_pipeline = hydrate_reference_transforms(
        rec.pipeline,
        ds,
        cache_namespace=(rec.cache.cache_namespace if rec.cache else rec.session_id),
    )
    indices = resolve_subset_indices(dataset=ds, subset=rec.subset, pipeline=runtime_pipeline)
    refs = filter_reference_spectra([ds.spectra[i] for i in indices], runtime_pipeline)
    filtered_indices = [ds.spectra.index(ref) for ref in refs]
    return {
        "subset": rec.subset,
        "resolved": {"count": len(filtered_indices), "dataset_indices": filtered_indices},
        "subset_hash": subset_hash(rec.subset),
    }


@router.post("/{session_id}/run")
def run_session_endpoint(session_id: str, payload: SessionRunRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    rec = get_session_for_user(session_id, user_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ds = get_dataset_for_user(rec.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    runtime_pipeline = hydrate_reference_transforms(
        rec.pipeline,
        ds,
        cache_namespace=(rec.cache.cache_namespace if rec.cache else rec.session_id),
    )

    if payload.scope == "all":
        refs = filter_reference_spectra(ds.spectra, runtime_pipeline)
    else:
        indices = resolve_subset_indices(dataset=ds, subset=rec.subset, pipeline=runtime_pipeline)
        refs = filter_reference_spectra([ds.spectra[i] for i in indices], runtime_pipeline)

    cfg = EngineConfig(cache_namespace=(rec.cache.cache_namespace if rec.cache else rec.session_id))

    if isinstance(payload.return_, SessionRunReturnFinal):
        try:
            final = run_pipeline(
                inputs=refs,
                pipeline=runtime_pipeline,
                cache=_cache,
                config=cfg,
                up_to_step=payload.up_to_step,
                strict=True,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"Uploaded file not found: {e}") from e
        items = [
            {"spectrum_id": sid, "x": xy.x.astype(float).tolist(), "y": xy.y.astype(float).tolist()}
            for sid, xy in final.items()
        ]
        return {"items": items}

    if isinstance(payload.return_, SessionRunReturnIntermediates):
        if len(refs) > 50:
            raise HTTPException(status_code=400, detail="Too many spectra for intermediates; select a smaller subset")
        try:
            _, inter = run_pipeline_with_intermediates(
                inputs=refs,
                pipeline=runtime_pipeline,
                collect_steps=set(payload.return_.steps),
                cache=_cache,
                config=cfg,
                up_to_step=payload.up_to_step,
                strict=True,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"Uploaded file not found: {e}") from e
        items = []
        for sid, steps in inter.items():
            items.append(
                {
                    "spectrum_id": sid,
                    "steps": {
                        name: {"x": xy.x.astype(float).tolist(), "y": xy.y.astype(float).tolist()}
                        for name, xy in steps.items()
                    },
                }
            )
        return {"items": items}

    retm = cast(SessionRunReturnMetricsOnly, payload.return_)
    if payload.scope == "all":
        inputs = [
            {
                "spectrum_id": r.spectrum_id,
                "relative_path": r.relative_path,
                "record_index": r.record_index,
                "blob_id": r.blob_id,
                "blob_relative_path": r.blob_relative_path,
                "original_relative_path": r.original_relative_path,
            }
            for r in refs
        ]
        steps = [
            {
                "name": s.name,
                "params": s.params,
                "enabled": s.enabled,
                "impl_version": s.impl_version,
                "step_id": s.step_id,
                "input_from": s.input_from,
                "after_step_id": s.after_step_id,
            }
            for s in runtime_pipeline.steps
        ]
        final = run_pipeline_parallel_no_cache(
            inputs=inputs,
            pipeline_steps=steps,
            config=cfg,
            up_to_step=payload.up_to_step,
            max_workers=SESSION_MAX_WORKERS,
        )
    else:
        try:
            final = run_pipeline(
                inputs=refs,
                pipeline=runtime_pipeline,
                cache=_cache,
                config=cfg,
                up_to_step=payload.up_to_step,
                strict=True,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"Uploaded file not found: {e}") from e
    items = []
    for sid, xy in final.items():
        ms = compute_metrics(xy, retm.metrics)
        items.append({"spectrum_id": sid, "metrics": [{"name": r.name, "value": r.value, "unit": r.unit} for r in ms]})
    return {"items": items}
