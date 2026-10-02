from __future__ import annotations

from typing import Any, cast

import numpy as np
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
from sersflow.api.schemas.sessions_qc import SessionQcPreviewRequest, SessionQcPreviewResponse
from sersflow.api.services.ownership import get_dataset_for_user, get_session_for_user
from sersflow.api.services.reference_runtime import filter_reference_spectra, hydrate_reference_transforms
from sersflow.api.services.pipeline_qc import (
    apply_pipeline_qc_filters,
    apply_pipeline_qc_filters_before_step,
    pipeline_without_qc_steps,
    qc_step_xy_inputs,
)
from sersflow.api.services.sessions_service import pipeline_hash, resolve_subset_indices, subset_hash
from sersflow.api.services.technique_guard import (
    dataset_technique_family,
    prepare_pipeline_for_run,
)
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
from sersflow.core.qc.low_signal import low_signal_metric_value
from sersflow.core.qc.outliers import outlier_scores_from_xy


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
    pipeline = prepare_pipeline_for_run(
        payload.pipeline or Pipeline(steps=[]),
        dataset_technique_family(ds.metadata),
        context=f"session create on dataset {payload.dataset_id}",
        allow_empty_align=True,
    )
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
    rec0 = get_session_for_user(session_id, user_id)
    if rec0 is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ds = get_dataset_for_user(rec0.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    pipeline = prepare_pipeline_for_run(
        payload.pipeline,
        dataset_technique_family(ds.metadata),
        context=f"session {session_id} pipeline update",
        allow_empty_align=True,
    )
    rec = update_session_pipeline(session_id, pipeline)
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


@router.post("/{session_id}/qc/preview", response_model=SessionQcPreviewResponse)
def session_qc_preview_endpoint(
    session_id: str,
    payload: SessionQcPreviewRequest,
    request: Request,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    rec = get_session_for_user(session_id, user_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ds = get_dataset_for_user(rec.dataset_id, user_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    cache_ns = (rec.cache.cache_namespace if rec.cache else rec.session_id)
    runtime_pipeline = hydrate_reference_transforms(
        rec.pipeline,
        ds,
        cache_namespace=cache_ns,
    )

    # Resolve refs from scope, then remove reference spectra.
    if payload.scope == "all":
        refs = filter_reference_spectra(ds.spectra, runtime_pipeline)
    else:
        indices = resolve_subset_indices(dataset=ds, subset=rec.subset, pipeline=runtime_pipeline)
        refs = filter_reference_spectra([ds.spectra[i] for i in indices], runtime_pipeline)

    # Find the QC step by step_id.
    step_id = payload.step_id.strip()
    idx = next((i for i, s in enumerate(runtime_pipeline.steps) if (s.step_id or "").strip() == step_id), None)
    if idx is None:
        raise HTTPException(status_code=400, detail="QC preview step_id does not match any pipeline step")
    step = runtime_pipeline.steps[idx]
    if step.name not in ("low_signal_filter", "outlier_detection", "metadata_filter"):
        raise HTTPException(status_code=400, detail="Selected step_id is not a previewable filter/QC step")

    # Apply earlier QC steps so preview matches the effective cohort at this location.
    refs, _qc_before = apply_pipeline_qc_filters_before_step(
        dataset=ds,
        pipeline=runtime_pipeline,
        refs=refs,
        cache_namespace=cache_ns,
        stop_before_step_index=idx,
        strict=True,
    )

    params = dict(step.params or {})
    params.update(dict(payload.step_params or {}))

    if step.name == "metadata_filter":
        from sersflow.api.services.spectrum_context import load_spectrum_contexts
        from sersflow.core.qc.metadata_filter import evaluate_filters
        from sersflow.infra.datasets_store import iter_spectrum_axes_page
        from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

        filters = params.get("filters") if isinstance(params.get("filters"), list) else []
        paths = sorted({str(r.relative_path) for r in refs if r.relative_path})
        con = with_connection()
        try:
            labels_by_path = fetch_upload_labels_for_paths(con, paths)
        finally:
            con.close()
        axes_by_sid: dict[str, dict[str, Any]] = {}
        offset = 0
        while True:
            page, total = iter_spectrum_axes_page(dataset_id=ds.dataset_id, limit=500, offset=offset)
            for it in page:
                sid = str(it.get("spectrum_id") or "")
                if sid:
                    axes_by_sid[sid] = it
            offset += len(page)
            if offset >= total or not page:
                break
        score_rows = []
        flagged_count = 0
        for ctx in load_spectrum_contexts(refs, labels_by_path=labels_by_path):
            row = dict(ctx.labels)
            axes = axes_by_sid.get(ctx.spectrum_id) or {}
            for k in ("axis_map_x", "axis_map_y", "axis_time_s", "file_kind"):
                if axes.get(k) is not None:
                    row[k] = axes[k]
            ok = evaluate_filters(row, filters)
            if not ok:
                flagged_count += 1
            score_rows.append(
                {
                    "spectrum_id": ctx.spectrum_id,
                    "score": 1.0 if ok else 0.0,
                    "flagged": not ok,
                }
            )
        total = len(score_rows)
        flagged_pct = float((flagged_count / total) * 100.0) if total else 0.0
        return {
            "step_id": step_id,
            "step_name": step.name,
            "summary": {"total": total, "flagged_count": flagged_count, "flagged_pct": flagged_pct},
            "histogram": {"bins": [], "counts": [], "nonfinite": 0},
            "threshold": 0.5,
            "direction": "below",
            "scores": score_rows,
            "meta": {"filters": filters, "n_filters": len(filters)},
        }

    # Compute XY right before this QC step and score.
    finals = qc_step_xy_inputs(
        pipeline=runtime_pipeline,
        refs=refs,
        cache_namespace=cache_ns,
        step_index=idx,
        strict=True,
    )

    scores_by_id: dict[str, float] = {}
    flagged: set[str] = set()
    threshold = float(params.get("threshold", 0.0))
    direction: str
    meta: dict[str, Any] = {}

    if step.name == "low_signal_filter":
        metric = str(params.get("metric", "median")).strip().lower()
        percentile = params.get("percentile")
        perc_val = float(percentile) if percentile is not None else None
        for sid, xy in finals.items():
            v = low_signal_metric_value(xy, metric=metric, percentile=perc_val)  # type: ignore[arg-type]
            scores_by_id[sid] = float(v)
            if not np.isfinite(float(v)) or float(v) < threshold:
                flagged.add(sid)
        direction = "below"
        meta = {"metric": metric, "percentile": perc_val}
    else:
        method = str(params.get("method", "correlation_to_median")).strip()
        n_components = int(params.get("n_components", 8))
        pca_scaler = str(params.get("pca_scaler", "none")).strip().lower()
        ys_by_id = {sid: xy.y for sid, xy in finals.items()}
        x_by_id = {sid: xy.x for sid, xy in finals.items()}
        scores_by_id, ometa = outlier_scores_from_xy(
            method=method,  # type: ignore[arg-type]
            ys_by_id=ys_by_id,
            x_by_id=x_by_id,
            n_components=n_components,
            pca_scaler=pca_scaler,  # type: ignore[arg-type]
        )
        for sid, v in scores_by_id.items():
            if not np.isfinite(float(v)):
                flagged.add(sid)
                continue
            if method == "correlation_to_median":
                if float(v) < threshold:
                    flagged.add(sid)
            else:
                if float(v) > threshold:
                    flagged.add(sid)
        direction = "below" if method == "correlation_to_median" else "above"
        meta = {"method": method, "n_components": n_components, "pca_scaler": pca_scaler, **ometa}

    # Histogram over finite scores only.
    vals = np.array([v for v in scores_by_id.values()], dtype=np.float64)
    finite = np.isfinite(vals)
    finite_vals = vals[finite]
    nonfinite = int(np.sum(~finite))
    bins: list[float] = []
    counts: list[int] = []
    if finite_vals.size >= 2:
        # Higher bin count for better readability (especially on log-scaled views).
        n_bins = int(min(200, max(60, np.sqrt(float(finite_vals.size)) * 6)))
        lo = float(np.min(finite_vals))
        hi = float(np.max(finite_vals))
        if hi > lo:
            # If all values are positive, use log-spaced bins (aligns better with log x-axis).
            if lo > 0:
                min_exp = float(np.floor(np.log10(lo)))
                max_exp = float(np.ceil(np.log10(hi)))
                lo_adj = 10 ** (min_exp - 1)
                hi_adj = 10 ** max_exp
                edges = np.logspace(np.log10(lo_adj), np.log10(hi_adj), n_bins + 1, dtype=np.float64)
            else:
                edges = np.linspace(lo, hi, n_bins + 1, dtype=np.float64)
            hist, _ = np.histogram(finite_vals, bins=edges)
            bins = edges.astype(float).tolist()
            counts = hist.astype(int).tolist()

    total = len(scores_by_id)
    flagged_count = len(flagged)
    flagged_pct = float((flagged_count / total) * 100.0) if total else 0.0

    # Stable output order: pipeline input order.
    score_rows = []
    for r in refs:
        sid = r.spectrum_id
        if sid not in scores_by_id:
            continue
        v = scores_by_id.get(sid)
        score_rows.append(
            {"spectrum_id": sid, "score": float(v) if v is not None and np.isfinite(float(v)) else None, "flagged": sid in flagged}
        )

    return {
        "step_id": step_id,
        "step_name": step.name,
        "summary": {"total": total, "flagged_count": flagged_count, "flagged_pct": flagged_pct},
        "histogram": {"bins": bins, "counts": counts, "nonfinite": nonfinite},
        "threshold": float(threshold),
        "direction": direction,
        "scores": score_rows,
        "meta": meta,
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

    prepare_pipeline_for_run(
        rec.pipeline,
        dataset_technique_family(ds.metadata),
        context=f"session {session_id} run",
    )

    runtime_pipeline = hydrate_reference_transforms(
        rec.pipeline,
        ds,
        cache_namespace=(rec.cache.cache_namespace if rec.cache else rec.session_id),
    )

    # Apply QC/filter steps as cohort exclusions (session-only).
    # QC steps do not transform XY; they only shrink the working set for downstream execution.
    cache_ns = (rec.cache.cache_namespace if rec.cache else rec.session_id)

    # Sentinels (no XY transforms):
    # - __source__: true raw subset/all — skip QC entirely
    # - __raw__: cohort QC (low_signal / outlier) applied, then raw XY of remaining spectra
    # - __raw__:<N>: cohort QC applied only through pipeline step index N (1-based), then raw XY
    up_token = str(payload.up_to_step or "").strip()
    source_only = up_token == "__source__"
    raw_through_step: int | None = None
    raw_only = False
    if up_token == "__raw__":
        raw_only = True
    elif up_token.startswith("__raw__:"):
        raw_only = True
        try:
            raw_through_step = int(up_token.split(":", 1)[1].strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid up_to_step {up_token!r}") from e
        if raw_through_step < 1:
            raise HTTPException(status_code=400, detail="__raw__:<N> requires N >= 1")

    if payload.scope == "all":
        refs = filter_reference_spectra(ds.spectra, runtime_pipeline)
    else:
        indices = resolve_subset_indices(dataset=ds, subset=rec.subset, pipeline=runtime_pipeline)
        refs = filter_reference_spectra([ds.spectra[i] for i in indices], runtime_pipeline)

    if not source_only:
        pipe_for_qc = runtime_pipeline
        if raw_through_step is not None:
            pipe_for_qc = runtime_pipeline.model_copy(
                update={"steps": [s.model_copy(deep=True) for s in runtime_pipeline.steps[:raw_through_step]]},
            )
        refs, _qc_report = apply_pipeline_qc_filters(
            dataset=ds,
            pipeline=pipe_for_qc,
            refs=refs,
            cache_namespace=cache_ns,
            strict=True,
        )
    runtime_pipeline_no_qc = pipeline_without_qc_steps(runtime_pipeline)

    cfg = EngineConfig(cache_namespace=cache_ns)

    if source_only or raw_only:
        runtime_pipeline_no_qc = Pipeline(steps=[])

    if isinstance(payload.return_, SessionRunReturnFinal):
        try:
            final = run_pipeline(
                inputs=refs,
                pipeline=runtime_pipeline_no_qc,
                cache=_cache,
                config=cfg,
                up_to_step=None if (source_only or raw_only) else payload.up_to_step,
                strict=True,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"Uploaded file not found: {e}") from e
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        items = [
            {"spectrum_id": sid, "x": xy.x.astype(float).tolist(), "y": xy.y.astype(float).tolist()}
            for sid, xy in final.items()
            if getattr(xy, "x", None) is not None and len(xy.x) > 0
        ]
        return {"items": items}

    if isinstance(payload.return_, SessionRunReturnIntermediates):
        if len(refs) > 50:
            raise HTTPException(status_code=400, detail="Too many spectra for intermediates; select a smaller subset")
        try:
            _, inter = run_pipeline_with_intermediates(
                inputs=refs,
                pipeline=runtime_pipeline_no_qc,
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
            for s in runtime_pipeline_no_qc.steps
        ]
        final = run_pipeline_parallel_no_cache(
            inputs=inputs,
            pipeline_steps=steps,
            config=cfg,
            up_to_step=payload.up_to_step,
            max_workers=SESSION_MAX_WORKERS,
            technique_family=getattr(runtime_pipeline_no_qc, "technique_family", None),
        )
    else:
        try:
            final = run_pipeline(
                inputs=refs,
                pipeline=runtime_pipeline_no_qc,
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
