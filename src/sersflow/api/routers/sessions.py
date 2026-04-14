from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionGetResponse,
    SessionPipelineUpdateRequest,
    SessionPipelineUpdateResponse,
    SessionRunRequest,
    SessionRunReturnFinal,
    SessionRunReturnIntermediates,
    SessionRunReturnMetricsOnly,
    SessionSubsetUpdateResponse,
    SubsetStrategy,
)
from sersflow.api.services.sessions_service import pipeline_hash, resolve_subset_indices, subset_hash
from sersflow.core.metrics.compute import compute_metrics
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import (
    EngineConfig,
    run_pipeline,
    run_pipeline_parallel_no_cache,
    run_pipeline_with_intermediates,
)
from sersflow.infra.datasets_store import get_dataset
from sersflow.infra.sessions_store import (
    create_session,
    get_session,
    to_schema,
    update_session_pipeline,
    update_session_subset,
)


router = APIRouter(prefix="/sessions", tags=["sessions"])
_cache = InProcessLRUCache(max_items=4096)


@router.post("", response_model=SessionCreateResponse)
def create_session_endpoint(payload: SessionCreateRequest) -> dict[str, Any]:
    ds = get_dataset(payload.dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    pipeline = payload.pipeline or Pipeline(steps=[])
    subset = payload.subset or SubsetStrategy(kind="all")
    rec = create_session(dataset_id=payload.dataset_id, pipeline=pipeline, subset=subset)
    return {"session": to_schema(rec)}


@router.get("/{session_id}", response_model=SessionGetResponse)
def get_session_endpoint(session_id: str) -> dict[str, Any]:
    rec = get_session(session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": to_schema(rec)}


@router.put("/{session_id}/pipeline", response_model=SessionPipelineUpdateResponse)
def update_pipeline_endpoint(session_id: str, payload: SessionPipelineUpdateRequest) -> dict[str, Any]:
    rec = update_session_pipeline(session_id, payload.pipeline)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"pipeline": rec.pipeline, "pipeline_hash": pipeline_hash(rec.pipeline)}


@router.post("/{session_id}/subset", response_model=SessionSubsetUpdateResponse)
def update_subset_endpoint(session_id: str, payload: SubsetStrategy) -> dict[str, Any]:
    rec = update_session_subset(session_id, payload)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ds = get_dataset(rec.dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    indices = resolve_subset_indices(dataset=ds, subset=rec.subset, pipeline=rec.pipeline)
    return {
        "subset": rec.subset,
        "resolved": {"count": len(indices), "dataset_indices": indices},
        "subset_hash": subset_hash(rec.subset),
    }


@router.post("/{session_id}/run")
def run_session_endpoint(session_id: str, payload: SessionRunRequest) -> dict[str, Any]:
    rec = get_session(session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ds = get_dataset(rec.dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if payload.scope == "all":
        refs = ds.spectra
    else:
        indices = resolve_subset_indices(dataset=ds, subset=rec.subset, pipeline=rec.pipeline)
        refs = [ds.spectra[i] for i in indices]

    cfg = EngineConfig(cache_namespace=(rec.cache.cache_namespace if rec.cache else rec.session_id))

    if isinstance(payload.return_, SessionRunReturnFinal):
        final = run_pipeline(inputs=refs, pipeline=rec.pipeline, cache=_cache, config=cfg, up_to_step=payload.up_to_step)
        items = [
            {"spectrum_id": sid, "x": xy.x.astype(float).tolist(), "y": xy.y.astype(float).tolist()}
            for sid, xy in final.items()
        ]
        return {"items": items}

    if isinstance(payload.return_, SessionRunReturnIntermediates):
        # Protect interactive mode: intermediates can be heavy.
        if len(refs) > 50:
            raise HTTPException(status_code=400, detail="Too many spectra for intermediates; select a smaller subset")
        _, inter = run_pipeline_with_intermediates(
            inputs=refs,
            pipeline=rec.pipeline,
            collect_steps=set(payload.return_.steps),
            cache=_cache,
            config=cfg,
            up_to_step=payload.up_to_step,
        )
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
    # Batch performance: for full-dataset metrics runs, parallelize without shared cache.
    # Cache is in-process only and not shared across processes.
    if payload.scope == "all":
        inputs = [
            {"spectrum_id": r.spectrum_id, "relative_path": r.relative_path, "record_index": r.record_index}
            for r in refs
        ]
        steps = [
            {"name": s.name, "params": s.params, "enabled": s.enabled, "impl_version": s.impl_version}
            for s in rec.pipeline.steps
        ]
        final = run_pipeline_parallel_no_cache(inputs=inputs, pipeline_steps=steps, config=cfg, up_to_step=payload.up_to_step)
    else:
        final = run_pipeline(inputs=refs, pipeline=rec.pipeline, cache=_cache, config=cfg, up_to_step=payload.up_to_step)
    items = []
    for sid, xy in final.items():
        ms = compute_metrics(xy, retm.metrics)
        items.append({"spectrum_id": sid, "metrics": [{"name": r.name, "value": r.value, "unit": r.unit} for r in ms]})
    return {"items": items}

