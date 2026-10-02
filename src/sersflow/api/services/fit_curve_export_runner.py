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
    _collect_fit_input_xy,
    _find_fitting_step,
    _resolved_refs_for_run,
)
from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.core.metrics.fitting_features import p_opt_and_gof_from_features
from sersflow.core.pipeline.engine import fitting_region_applies
from sersflow.core.preprocess.fitting import evaluate_fit_curves, fit_problem_from_step_params
from sersflow.infra.analysis_store import (
    get_fit_curve_job,
    get_run,
    get_spectrum_features_for_ids,
    update_fit_curve_job,
)
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

        fitting_idx, fitting_step = _find_fitting_step(effective_pipeline, rec.fitting_step_num)
        step_params = dict(fitting_step.params or {})
        tech = getattr(effective_pipeline, "technique_family", None)
        if tech and "technique_family" not in step_params:
            step_params["technique_family"] = tech

        xy_by_id = _collect_fit_input_xy(
            pipeline=effective_pipeline,
            refs=refs,
            ns=ns,
            fitting_idx=fitting_idx,
            fitting_step_num=rec.fitting_step_num,
        )
        features_by_id = get_spectrum_features_for_ids(
            run_id=rec.run_id,
            spectrum_ids=[str(r.spectrum_id) for r in refs],
        )

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
                xy = xy_by_id.get(sid)
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

                feat = features_by_id.get(sid) or {}
                p_opt, stored_diag, err = p_opt_and_gof_from_features(
                    pipeline=effective_pipeline,
                    fitting_step_num=rec.fitting_step_num,
                    features=feat,
                )
                if p_opt is None:
                    logger.debug("skip %s: %s", sid, err)
                    if done % 25 == 0 or done == total:
                        update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=total)
                    continue
                try:
                    prob = fit_problem_from_step_params(xy, step_params)
                    if prob is None:
                        continue
                    res = evaluate_fit_curves(prob, p_opt, diagnostics=stored_diag)
                except (ValueError, RuntimeError, ImportError):
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
