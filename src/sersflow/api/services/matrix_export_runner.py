from __future__ import annotations

import json
import logging
import os
from typing import Any

import numpy as np

from sersflow.api.schemas.sessions import SubsetStrategy

# Matrix export for exploration uses the full dataset; session.subset is preview-only.
_MATRIX_COHORT = SubsetStrategy(kind="all")
from sersflow.api.services.sessions_service import resolve_subset_indices
from sersflow.api.services.reference_runtime import filter_reference_spectra, hydrate_reference_transforms
from sersflow.api.services.pipeline_qc import apply_pipeline_qc_filters, pipeline_without_qc_steps
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline_parallel_no_cache
from sersflow.infra.datasets_store import get_dataset_internal
from sersflow.infra.explore_store import artifacts_root, update_matrix_job
from sersflow.infra.explore_store import get_matrix_job as store_get_matrix_job
from sersflow.infra.sessions_store import get_session

logger = logging.getLogger(__name__)
MATRIX_MAX_WORKERS = 8


def _max_spectra() -> int:
    raw = os.environ.get("SERSFLOW_MATRIX_MAX_SPECTRA", "100000")
    try:
        return max(1, min(int(raw), 500_000))
    except ValueError:
        return 100_000


def execute_matrix_export_job(matrix_job_id: str) -> None:
    rec = store_get_matrix_job(matrix_job_id)
    if rec is None:
        logger.error("matrix job not found: %s", matrix_job_id)
        return

    try:
        update_matrix_job(matrix_job_id=matrix_job_id, status="running", finished=False)
        pipeline: Pipeline
        if rec.session_id:
            sess = get_session(rec.session_id)
            if sess is None:
                raise ValueError("session not found")
            if sess.dataset_id != rec.dataset_id:
                raise ValueError("session dataset mismatch")
            pipeline = sess.pipeline
            ns = sess.cache.cache_namespace if sess.cache else matrix_job_id
        else:
            if not rec.pipeline_json:
                raise ValueError("matrix export requires session_id or pipeline_json")
            pipeline = Pipeline.model_validate_json(rec.pipeline_json)
            ns = matrix_job_id

        ds = get_dataset_internal(rec.dataset_id)
        if ds is None:
            raise ValueError("dataset not found")
        pipeline = hydrate_reference_transforms(pipeline, ds, cache_namespace=ns)

        indices = resolve_subset_indices(dataset=ds, subset=_MATRIX_COHORT, pipeline=pipeline)
        refs = filter_reference_spectra([ds.spectra[i] for i in indices], pipeline)
        refs, _qc_report = apply_pipeline_qc_filters(
            dataset=ds,
            pipeline=pipeline,
            refs=refs,
            cache_namespace=ns,
            strict=True,
        )
        pipeline = pipeline_without_qc_steps(pipeline)
        if len(refs) > _max_spectra():
            raise ValueError(f"too many spectra (max {_max_spectra()})")

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
            for s in pipeline.steps
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
        cfg = EngineConfig(cache_namespace=ns)

        final = run_pipeline_parallel_no_cache(
            inputs=inputs,
            pipeline_steps=steps,
            config=cfg,
            up_to_step=rec.up_to_step,
            max_workers=MATRIX_MAX_WORKERS,
        )

        x0: np.ndarray | None = None
        rows: list[np.ndarray] = []
        sids: list[str] = []
        for sid, xy in final.items():
            xf = xy.x.astype(float, copy=False)
            yf = xy.y.astype(float, copy=False)
            if x0 is None:
                x0 = np.asarray(xf, dtype=np.float64)
                if x0.size < 1:
                    raise ValueError(
                        "matrix export produced an empty Raman shift grid (0 points). "
                        "This usually means crop min/max do not overlap the dataset wavenumbers."
                    )
            elif x0.shape != xf.shape or not np.allclose(x0, xf, rtol=0.0, atol=1e-3):
                raise ValueError(
                    "inconsistent Raman shift grid after pipeline. Add an enabled align_resample step after crop "
                    "(shared crop + same align params) before matrix export."
                )
            rows.append(np.asarray(yf, dtype=np.float32))
            sids.append(sid)

        if not rows:
            raise ValueError("no spectra in matrix export result")

        Y = np.stack(rows, axis=0)
        root = artifacts_root()
        subdir = os.path.join(root, "matrix", matrix_job_id)
        os.makedirs(subdir, exist_ok=True)
        npz_path = os.path.join(subdir, "matrix.npz")
        np.savez_compressed(
            npz_path,
            Y=Y,
            x=x0.astype(np.float64),
            spectrum_ids=np.array(sids, dtype=object),
        )

        manifest: dict[str, Any] = {
            "matrix_job_id": matrix_job_id,
            "dataset_id": rec.dataset_id,
            "session_id": rec.session_id,
            "pipeline_hash": rec.pipeline_hash,
            "subset_hash": rec.subset_hash,
            "up_to_step": rec.up_to_step,
            "shape": [int(Y.shape[0]), int(Y.shape[1])],
            "x_len": int(x0.shape[0]),
            "npz_path": npz_path,
        }
        manifest_json = json.dumps(manifest, separators=(",", ":"), ensure_ascii=False)
        update_matrix_job(
            matrix_job_id=matrix_job_id,
            status="completed",
            npz_path=npz_path,
            manifest_json=manifest_json,
            error=None,
            finished=True,
        )
    except Exception as e:
        logger.exception("matrix export failed: %s", matrix_job_id)
        update_matrix_job(matrix_job_id=matrix_job_id, status="failed", error=str(e), finished=True)


def subset_from_session(session_id: str) -> SubsetStrategy:
    sess = get_session(session_id)
    if sess is None:
        raise ValueError("session not found")
    return sess.subset
