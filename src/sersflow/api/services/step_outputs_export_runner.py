"""Async export of per-spectrum step outputs (raw XY + selected pipeline steps, CSV zip)."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import zipfile
from typing import Any

import numpy as np

from sersflow.api.services.analysis_runner import _effective_pipeline_for_analysis, prepare_run_context
from sersflow.api.services.fit_curve_export_runner import _max_spectra, _safe_name
from sersflow.api.services.fitting_preview import _resolved_refs_for_run
from sersflow.api.services.pipeline_qc import pipeline_without_qc_steps
from sersflow.core.pipeline.engine import RAW_COLLECT_TOKEN, EngineConfig, run_pipeline_parallel_no_cache
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.spectrum import XY
from sersflow.infra.analysis_store import get_fit_curve_job, get_run, update_fit_curve_job
from sersflow.infra.explore_store import artifacts_root

logger = logging.getLogger(__name__)

STEP_OUTPUTS_CONTENT = "step_outputs"


def _step_label(step: Any, step_num: int) -> str:
    label = f"s{step_num}_{step.name}"
    region = (step.params or {}).get("xps_region") if step.name == "fitting" else None
    if region is not None and str(region).strip():
        label += f"_{_safe_name(str(region).strip())}"
    return label


def list_pipeline_steps_for_export(pipeline: Any) -> list[dict[str, Any]]:
    """Enabled steps of an (effective, QC-free) pipeline, numbered like the step-outputs job."""
    steps = list(getattr(pipeline, "steps", None) or [])
    sns = assign_pipeline_step_nums(steps)
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not getattr(step, "enabled", True):
            continue
        region = (step.params or {}).get("xps_region")
        out.append(
            {
                "step_num": int(sns[i]),
                "step_index": i,
                "name": step.name,
                "xps_region": str(region).strip() if region is not None and str(region).strip() else None,
                "label": _step_label(step, int(sns[i])),
            }
        )
    return out


def export_pipeline_for_run(rec: Any) -> Any:
    """Pipeline whose step numbering matches the step-outputs job (QC steps removed)."""
    pipeline, _sub, _sess = prepare_run_context(rec=rec)
    effective, _ = _effective_pipeline_for_analysis(pipeline)
    return pipeline_without_qc_steps(effective)


def _steps_as_dicts(pipeline: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "params": s.params,
            "enabled": bool(getattr(s, "enabled", True)),
            "impl_version": s.impl_version,
            "step_id": s.step_id,
            "input_from": s.input_from,
            "after_step_id": s.after_step_id,
        }
        for s in pipeline.steps
    ]


def _same_x(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape and bool(np.allclose(a, b, equal_nan=True))


def step_outputs_csv_bytes(*, raw: XY, step_outputs: list[tuple[str, XY | None]]) -> bytes:
    """
    Columns: ``x_raw, y_raw`` then one ``<label>`` column per step when the step keeps the raw x grid,
    otherwise a ``<label>_x, <label>_y`` pair (crop, resample, x calibration, ...). Steps that did not
    run for this spectrum (e.g. region-gated fitting) get an empty column.
    """
    rx = np.asarray(raw.x, dtype=float)
    ry = np.asarray(raw.y, dtype=float)
    headers = ["x_raw", "y_raw"]
    cols: list[np.ndarray] = [rx, ry]
    for label, xy in step_outputs:
        if xy is None or xy.x.size == 0:
            headers.append(label)
            cols.append(np.array([], dtype=float))
            continue
        sx = np.asarray(xy.x, dtype=float)
        sy = np.asarray(xy.y, dtype=float)
        if _same_x(sx, rx):
            headers.append(label)
            cols.append(sy)
        else:
            headers.extend([f"{label}_x", f"{label}_y"])
            cols.extend([sx, sy])
    n = max((c.size for c in cols), default=0)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for i in range(n):
        w.writerow([(float(c[i]) if np.isfinite(c[i]) else "") if i < c.size else "" for c in cols])
    return buf.getvalue().encode("utf-8")


def execute_step_outputs_job(job_id: str) -> None:
    rec = get_fit_curve_job(job_id)
    if rec is None:
        logger.error("step outputs job not found: %s", job_id)
        return
    try:
        update_fit_curve_job(job_id=job_id, status="running", finished=False)
        run = get_run(rec.run_id)
        if run is None:
            raise ValueError("analysis run not found")
        if run.status != "completed":
            raise ValueError("analysis run is not completed")
        opts = json.loads(rec.params_json or "{}")
        wanted_nums = [int(n) for n in (opts.get("step_nums") or [])]
        spectrum_ids = opts.get("spectrum_ids")

        pipeline, _ds, refs, ns = _resolved_refs_for_run(run, list(spectrum_ids) if spectrum_ids else None)
        if len(refs) > _max_spectra():
            raise ValueError(f"too many spectra (max {_max_spectra()})")

        steps = list(pipeline.steps)
        sns = assign_pipeline_step_nums(steps)
        selected: list[tuple[int, str, str]] = []  # (index, collect token, column label)
        for i, step in enumerate(steps):
            if getattr(step, "enabled", True) and int(sns[i]) in wanted_nums:
                selected.append((i, f"{step.name}__{sns[i]}", _step_label(step, int(sns[i]))))
        missing = set(wanted_nums) - {int(sns[i]) for i, _t, _l in selected}
        if missing:
            raise ValueError(f"unknown or disabled step_nums: {sorted(missing)}")
        if not selected:
            raise ValueError("select at least one step")

        # Stop after the last selected step; later steps (e.g. more fits) are not needed.
        up_to = selected[-1][1]
        collect = {RAW_COLLECT_TOKEN} | {tok for _i, tok, _l in selected}

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
        total = len(inputs)
        update_fit_curve_job(job_id=job_id, progress_done=0, progress_total=total)
        packed = run_pipeline_parallel_no_cache(
            inputs=inputs,
            pipeline_steps=_steps_as_dicts(pipeline),
            config=EngineConfig(cache_namespace=ns),
            up_to_step=up_to,
            step_nums=sns,
            collect_steps=collect,
            max_workers=min(8, max(1, total)),
            technique_family=getattr(pipeline, "technique_family", None),
        )
        if not isinstance(packed, tuple):
            raise RuntimeError("expected (final, per_step_outputs)")
        _final, per_out = packed

        out_dir = os.path.join(artifacts_root(), "fit_curve_jobs", job_id)
        os.makedirs(out_dir, exist_ok=True)
        zip_path = os.path.join(out_dir, "export.zip")
        written = 0
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for done, r in enumerate(refs, start=1):
                sid = str(r.spectrum_id)
                spec = per_out.get(sid) or {}
                raw = spec.get(RAW_COLLECT_TOKEN)
                if raw is not None and raw.x.size:
                    payload = step_outputs_csv_bytes(
                        raw=raw,
                        step_outputs=[(label, spec.get(tok)) for _i, tok, label in selected],
                    )
                    zf.writestr(f"{_safe_name(sid)}.csv", payload)
                    written += 1
                if done % 25 == 0 or done == total:
                    update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=total)
        if written == 0:
            raise ValueError("no spectra could be processed")

        update_fit_curve_job(
            job_id=job_id,
            status="completed",
            progress_done=total,
            progress_total=total,
            artifact_path=zip_path,
            finished=True,
        )
    except Exception as e:
        logger.exception("step outputs job failed: %s", job_id)
        update_fit_curve_job(job_id=job_id, status="failed", error=str(e), finished=True)
