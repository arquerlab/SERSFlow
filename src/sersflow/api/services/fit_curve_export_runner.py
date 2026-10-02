"""Async export of per-spectrum fit curves (CSV / PNG / SVG zip)."""

from __future__ import annotations

import csv
import io
import logging
import os
import zipfile
from typing import Any

from sersflow.api.services.fit_curve_plot import render_fit_residual_png, render_fit_residual_svg
from sersflow.api.services.fit_diagnostics_public import diagnostics_to_public
from sersflow.api.services.fitting_preview import (
    _find_fitting_step,
    _resolved_refs_for_run,
)
from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.core.pipeline.engine import EngineConfig, fitting_region_applies, run_pipeline_parallel_no_cache
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.infra.analysis_store import get_fit_curve_job, get_run, update_fit_curve_job
from sersflow.infra.explore_store import artifacts_root
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

logger = logging.getLogger(__name__)


def _max_spectra() -> int:
    raw = os.environ.get("SERSFLOW_FIT_CURVE_MAX_SPECTRA", "100000")
    try:
        return max(1, min(int(raw), 500_000))
    except ValueError:
        return 100_000


def _safe_name(sid: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in sid) or "spectrum"


def _csv_bytes(
    *,
    x: list[float],
    y: list[float],
    y_hat: list[float],
    residual: list[float],
    components: list[dict[str, Any]],
    include_components: bool,
) -> bytes:
    buf = io.StringIO()
    headers = ["x", "y", "y_hat", "residual"]
    comp_cols: list[tuple[str, list[float]]] = []
    if include_components:
        for c in components:
            cid = _safe_name(str(c.get("component_id") or "comp"))
            cy = c.get("y_hat") or []
            if isinstance(cy, list) and cy:
                headers.append(f"comp_{cid}")
                comp_cols.append((f"comp_{cid}", [float(v) for v in cy]))
    w = csv.writer(buf)
    w.writerow(headers)
    for i in range(len(x)):
        row: list[Any] = [x[i], y[i], y_hat[i], residual[i]]
        for _name, arr in comp_cols:
            row.append(arr[i] if i < len(arr) else "")
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def execute_fit_curve_job(job_id: str) -> None:
    rec = get_fit_curve_job(job_id)
    if rec is None:
        logger.error("fit curve job not found: %s", job_id)
        return
    try:
        update_fit_curve_job(job_id=job_id, status="running", finished=False)
        run = get_run(rec.run_id)
        if run is None:
            raise ValueError("analysis run not found")
        if run.status != "completed":
            raise ValueError("analysis run is not completed")

        effective_pipeline, _ds, refs, ns = _resolved_refs_for_run(run, None)
        if len(refs) > _max_spectra():
            raise ValueError(f"too many spectra (max {_max_spectra()})")

        _idx, fitting_step = _find_fitting_step(effective_pipeline, rec.fitting_step_num)
        step_params = dict(fitting_step.params or {})
        tech = getattr(effective_pipeline, "technique_family", None)
        if tech and "technique_family" not in step_params:
            step_params["technique_family"] = tech

        step_nums = assign_pipeline_step_nums(effective_pipeline.steps)
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
        packed = run_pipeline_parallel_no_cache(
            inputs=inputs,
            pipeline_steps=steps,
            config=EngineConfig(cache_namespace=ns),
            up_to_step=None,
            step_nums=step_nums,
            collect_step_inputs=True,
            max_workers=8,
            technique_family=getattr(effective_pipeline, "technique_family", None),
        )
        if not isinstance(packed, tuple):
            raise RuntimeError("expected step inputs")
        _final, per_inputs = packed

        paths = sorted({str(r.relative_path) for r in refs if r.relative_path})
        con = with_connection()
        try:
            labels_by_path = fetch_upload_labels_for_paths(con, paths)
        finally:
            con.close()

        include_components = rec.content == "data_fit_components_resid"
        fmt = rec.format
        out_dir = os.path.join(artifacts_root(), "fit_curve_jobs", job_id)
        os.makedirs(out_dir, exist_ok=True)
        zip_path = os.path.join(out_dir, "export.zip")

        total = len(refs)
        update_fit_curve_job(job_id=job_id, progress_done=0, progress_total=total)
        done = 0
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for r in refs:
                sid = str(r.spectrum_id)
                pin = per_inputs.get(sid) or {}
                xy = pin.get(int(rec.fitting_step_num))
                done += 1
                if xy is None or xy.x.size == 0:
                    if done % 25 == 0 or done == total:
                        update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=total)
                    continue
                ri = r.record_index if isinstance(r.record_index, int) else None
                row = _labels_for_spectrum(
                    labels_by_path.get(str(r.relative_path)) or {}, record_index=ri
                )
                raw_region = row.get("xps_region")
                spectrum_region = (
                    str(raw_region).strip()
                    if raw_region is not None and str(raw_region).strip()
                    else None
                )
                if not fitting_region_applies(step_params=step_params, spectrum_xps_region=spectrum_region):
                    if done % 25 == 0 or done == total:
                        update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=total)
                    continue
                try:
                    prob = fit_problem_from_step_params(xy, step_params)
                    if prob is None:
                        continue
                    res = fit_curve(prob)
                except (ValueError, RuntimeError):
                    if done % 25 == 0 or done == total:
                        update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=total)
                    continue

                x = xy.x.astype(float).tolist()
                y = xy.y.astype(float).tolist()
                y_hat = res.y_hat.astype(float).tolist()
                residual = (xy.y.astype(float) - res.y_hat.astype(float)).tolist()
                comps = []
                for idx, m in enumerate(res.mapping):
                    comps.append(
                        {
                            "component_id": m["component_id"],
                            "component_type": m["component_type"],
                            "y_hat": res.component_y_hat[idx].astype(float).tolist(),
                        }
                    )
                safe = _safe_name(sid)
                if fmt == "csv":
                    payload = _csv_bytes(
                        x=x,
                        y=y,
                        y_hat=y_hat,
                        residual=residual,
                        components=comps,
                        include_components=include_components,
                    )
                    zf.writestr(f"{safe}.csv", payload)
                else:
                    diag = diagnostics_to_public(res.diagnostics)
                    kwargs = dict(
                        x=x,
                        y=y,
                        y_hat=y_hat,
                        residual=residual,
                        components=comps if include_components else [],
                        title=sid,
                        diagnostics=diag,
                        include_components=include_components,
                    )
                    if fmt == "png":
                        zf.writestr(f"{safe}.png", render_fit_residual_png(**kwargs))
                    elif fmt == "svg":
                        zf.writestr(f"{safe}.svg", render_fit_residual_svg(**kwargs))
                    else:
                        raise ValueError(f"unknown format: {fmt}")

                if done % 25 == 0 or done == total:
                    update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=total)

        update_fit_curve_job(
            job_id=job_id,
            status="completed",
            progress_done=total,
            progress_total=total,
            artifact_path=zip_path,
            finished=True,
        )
    except Exception as e:
        logger.exception("fit curve job failed: %s", job_id)
        update_fit_curve_job(job_id=job_id, status="failed", error=str(e), finished=True)
