from __future__ import annotations

import json
import logging
import threading
from typing import Any

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.sessions_service import pipeline_hash, resolve_subset_indices, subset_hash
from sersflow.core.metrics.fitting_features import collect_fitting_features_for_pipeline, preview_fitting_feature_keys_for_pipeline
from sersflow.core.metrics.intensity_probes import collect_spectral_intensity_features_for_pipeline, preview_feature_keys_for_pipeline
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline_parallel_no_cache
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.infra.analysis_store import (
    insert_spectrum_rows_batch,
    prune_unpinned_runs,
    update_job_progress,
    update_run_status,
)
from sersflow.infra.analysis_store import get_run as store_get_run
from sersflow.infra.datasets_store import get_dataset
from sersflow.infra.sessions_store import get_session

logger = logging.getLogger(__name__)

COMMIT_BATCH = 250
PROGRESS_EVERY = 100
ANALYSIS_MAX_WORKERS = 8

_analysis_lock = threading.Lock()

# Analysis runs always process the full dataset; session.subset is for Prepare preview only.
_ANALYSIS_COHORT = SubsetStrategy(kind="all")


def _default_analysis_spectral_intensities_step() -> PipelineStep:
    """
    spectral_intensities is a no-op on XY but defines which probes become analysis columns.
    If the saved pipeline omits it, append one fixed probe so batch analysis can still run.
    """
    return PipelineStep(
        name="spectral_intensities",
        params={
            "probes": [
                {
                    "id": "analysis_fallback",
                    "target_cm1": 1000.0,
                    "acquisition": "fixed",
                    "method": "linear_interp",
                    "extrapolation": "nan",
                }
            ]
        },
        enabled=True,
    )


def _all_analysis_feature_keys(pipeline: Pipeline) -> list[str]:
    """spectral_intensities columns + fitted Gaussian parameters (pos, amp, fwhm, area)."""
    return [*preview_fitting_feature_keys_for_pipeline(pipeline), *preview_feature_keys_for_pipeline(pipeline)]


def _effective_pipeline_for_analysis(pipeline: Pipeline) -> tuple[Pipeline, bool]:
    """
    Returns (pipeline_to_execute_and_extract, used_fallback).

    When no enabled spectral_intensities step exists, the effective pipeline appends a default step
    (single probe at 1000 cm⁻¹). Users can add their own step in Prepare for meaningful probes.
    """
    keys = preview_feature_keys_for_pipeline(pipeline)
    if keys:
        return pipeline, False
    merged = Pipeline(steps=[*pipeline.steps, _default_analysis_spectral_intensities_step()])
    return merged, True


def _pipeline_subset_from_inline_run(rec: Any) -> tuple[Pipeline, SubsetStrategy]:
    if not rec.pipeline_json:
        raise ValueError("run has no pipeline_json; cannot execute inline pipeline")
    pl = Pipeline.model_validate(json.loads(rec.pipeline_json))
    raw = json.loads(rec.params_json or "{}")
    sub_raw = raw.get("subset")
    if not isinstance(sub_raw, dict):
        raise ValueError("run params_json.subset is required for inline pipeline mode")
    sub = SubsetStrategy.model_validate(sub_raw)
    return pl, sub


def prepare_run_context(*, rec: Any) -> tuple[Pipeline, SubsetStrategy, Any]:
    """
    Resolve pipeline and subset for a run record.

    If session_id is set, session wins. Otherwise load pipeline_json + params_json.subset.
    """
    if rec.session_id:
        sess = get_session(rec.session_id)
        if sess is None:
            raise ValueError("session not found")
        return sess.pipeline, sess.subset, sess

    pl, sub = _pipeline_subset_from_inline_run(rec)
    return pl, sub, None


def execute_analysis_run(*, run_id: str, job_id: str | None) -> None:
    with _analysis_lock:
        _execute_analysis_run_impl(run_id=run_id, job_id=job_id)


def _execute_analysis_run_impl(*, run_id: str, job_id: str | None) -> None:
    rec = store_get_run(run_id)
    if rec is None:
        logger.error("analysis run not found: %s", run_id)
        return

    try:
        update_run_status(run_id=run_id, status="running", finished=False)

        pipeline, _preview_subset, sess = prepare_run_context(rec=rec)
        effective_pipeline, used_si_fallback = _effective_pipeline_for_analysis(pipeline)
        keys = _all_analysis_feature_keys(effective_pipeline)
        if not keys:
            raise ValueError("pipeline has no spectral_intensities step and default probe injection failed")

        if used_si_fallback:
            logger.info(
                "analysis run %s: pipeline has no enabled spectral_intensities step; using default probe I_analysis_fallback at 1000 cm-1",
                run_id,
            )

        ds = get_dataset(rec.dataset_id)
        if ds is None:
            raise ValueError("dataset not found")

        indices = resolve_subset_indices(dataset=ds, subset=_ANALYSIS_COHORT, pipeline=effective_pipeline)
        refs = [ds.spectra[i] for i in indices]
        total = len(refs)
        if total == 0:
            raise ValueError("no spectra in resolved subset")

        if job_id:
            update_job_progress(job_id=job_id, status="running", progress_done=0, progress_total=total)

        ns = (sess.cache.cache_namespace if sess and sess.cache else None) or run_id
        cfg = EngineConfig(cache_namespace=ns)

        # IMPORTANT: preserve pipeline wiring (input_from / after_step_id) and numbering (step_id),
        # otherwise repeated-step pipelines (e.g. crop from initial, multiple fittings) diverge
        # from Prepare preview and later metric-step features become empty.
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
            for s in effective_pipeline.steps
        ]
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

        step_nums = assign_pipeline_step_nums(effective_pipeline.steps)
        packed = run_pipeline_parallel_no_cache(
            inputs=inputs,
            pipeline_steps=steps,
            config=cfg,
            up_to_step=None,
            step_nums=step_nums,
            collect_step_inputs=True,
            max_workers=ANALYSIS_MAX_WORKERS,
        )
        if not isinstance(packed, tuple):
            raise RuntimeError("collect_step_inputs=True must return (final_xy_map, per_step_inputs)")
        final, per_inputs = packed

        buffer: list[tuple[str, dict[str, Any]]] = []
        done = 0
        null_row = {k: None for k in keys}
        for sid, xy in final.items():
            feats = dict(null_row)
            pin = per_inputs.get(sid) or {}
            try:
                _, fd = collect_fitting_features_for_pipeline(xy, effective_pipeline, per_step_input_xy=pin)
                feats.update(fd)
            except Exception as e:
                logger.warning("fitting feature extraction failed for spectrum %s (skipped): %s", sid, e)
            try:
                _, sd = collect_spectral_intensity_features_for_pipeline(xy, effective_pipeline, per_step_input_xy=pin)
                feats.update(sd)
            except Exception as e:
                logger.warning("spectral feature extraction failed for spectrum %s (skipped): %s", sid, e)
            buffer.append((sid, feats))
            done += 1
            if len(buffer) >= COMMIT_BATCH:
                insert_spectrum_rows_batch(run_id=run_id, rows=buffer)
                buffer.clear()
                if job_id and (done % PROGRESS_EVERY == 0 or done == total):
                    update_job_progress(
                        job_id=job_id,
                        status=None,
                        progress_done=done,
                        progress_total=total,
                    )

        if buffer:
            insert_spectrum_rows_batch(run_id=run_id, rows=buffer)

        update_run_status(
            run_id=run_id,
            status="completed",
            error=None,
            feature_columns=keys,
            finished=True,
        )
        if job_id:
            update_job_progress(
                job_id=job_id,
                status="completed",
                progress_done=total,
                progress_total=total,
            )
        prune_unpinned_runs(dataset_id=rec.dataset_id)
    except Exception as e:
        logger.exception("analysis run failed: %s", run_id)
        update_run_status(run_id=run_id, status="failed", error=str(e), finished=True)
        if job_id:
            update_job_progress(
                job_id=job_id,
                status="failed",
                progress_done=0,
                progress_total=0,
                error=str(e),
            )


def build_stored_pipeline_json(*, pipeline: Pipeline, subset: SubsetStrategy, session_id: str | None) -> str | None:
    """Persist pipeline JSON for runs without session (inline mode)."""
    if session_id:
        return None
    return pipeline.model_dump_json()


def build_stored_params_json(*, subset: SubsetStrategy) -> dict[str, Any]:
    return {"subset": subset.model_dump()}
