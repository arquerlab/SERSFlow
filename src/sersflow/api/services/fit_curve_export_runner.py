"""Async export of per-spectrum fit curves (CSV / PNG / SVG zip)."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import zipfile
from typing import Any

import numpy as np

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
from sersflow.core.preprocess.fit_diagnostics import fit_health_metrics
from sersflow.core.preprocess.fitting_specs import XPS_BACKGROUND_COMPONENT_TYPES
from sersflow.core.preprocess.fitting import (
    evaluate_fit_curves,
    expand_fit_curves_to_full,
    fit_problem_from_step_params,
)
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


_HEALTH_COLUMNS = (
    "spectrum_id",
    "fit_status",
    "fit_failure_reason",
    "rmse",
    "n_at_bound",
    "bg_gt_data_frac",
    "resid_mean_edge_lo",
    "resid_mean_edge_hi",
    "resid_lag1_autocorr",
)


def _health_row(sid, xy, y_hat_arr, stored_diag, mapping, comps_full) -> dict[str, Any]:
    """Per-spectrum fit-health sidecar row. Edge/bg metrics are recomputed from the exported curves
    (inside the fit window) so old runs without stored health columns still get them; the pinned
    count can only come from the fit itself (stored diagnostics)."""
    mask = np.isfinite(y_hat_arr)
    bg = None
    for idx, m in enumerate(mapping):
        if str(m.get("component_type", "")).lower() in XPS_BACKGROUND_COMPONENT_TYPES:
            bg = np.asarray(comps_full[idx], dtype=float)[mask]
            break
    health = fit_health_metrics(
        xy.y.astype(float)[mask], y_hat_arr[mask], x=xy.x.astype(float)[mask], bg_curve=bg
    )
    succ = getattr(stored_diag, "success", None)
    status = "not_converged" if succ is not None and float(succ) == 0.0 else "ok"
    row: dict[str, Any] = {
        "spectrum_id": sid,
        "fit_status": status,
        "fit_failure_reason": "optimizer reported success=False" if status == "not_converged" else None,
        "rmse": getattr(stored_diag, "rmse", None),
    }
    row["n_at_bound"] = getattr(stored_diag, "n_at_bound", None)
    row.update(health)
    return row


def _health_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_HEALTH_COLUMNS)
    for r in rows:
        w.writerow(
            [
                "" if (r.get(c) is None or (isinstance(r.get(c), float) and not np.isfinite(r[c]))) else r.get(c)
                for c in _HEALTH_COLUMNS
            ]
        )
    return buf.getvalue().encode("utf-8")


def _failures_for_step(run: Any, step: Any, step_index: int) -> dict[str, str | None]:
    """spectrum_id -> reason for fits recorded as failed in the run (K2), for this fitting step."""
    raw = getattr(run, "warnings_json", None)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    items = ((data or {}).get("fit_failures") or {}).get("items") or []
    step_id = getattr(step, "step_id", None)
    out: dict[str, str | None] = {}
    for it in items:
        if not isinstance(it, dict) or it.get("status") != "failed":
            continue
        same = (step_id and it.get("step_id") == step_id) or (
            not step_id and it.get("step_index") == step_index
        )
        if same:
            out[str(it.get("spectrum_id"))] = it.get("reason")
    return out


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
        failures_by_sid = _failures_for_step(run, fitting_step, fitting_idx)
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
        health_rows: list[dict[str, Any]] = []
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
                    succ = getattr(stored_diag, "success", None)
                    if sid in failures_by_sid or (succ is not None and float(succ) == 0.0):
                        # Failed fit: no curves, but it must appear in fit_health.csv (K2).
                        health_rows.append(
                            {
                                "spectrum_id": sid,
                                "fit_status": "failed",
                                "fit_failure_reason": failures_by_sid.get(sid) or err,
                            }
                        )
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

                y_hat_arr, comps_full = expand_fit_curves_to_full(
                    xy, step_params, res.y_hat, res.component_y_hat, outside="nan"
                )
                x = xy.x.astype(float).tolist()
                y = xy.y.astype(float).tolist()
                y_hat = y_hat_arr.astype(float).tolist()
                residual_arr = np.where(
                    np.isfinite(y_hat_arr), xy.y.astype(float) - y_hat_arr, np.nan
                )
                residual = residual_arr.tolist()
                comps = []
                for idx, m in enumerate(res.mapping):
                    comps.append(
                        {
                            "component_id": m["component_id"],
                            "component_type": m["component_type"],
                            "y_hat": comps_full[idx].astype(float).tolist(),
                        }
                    )
                safe = _safe_name(sid)
                health_rows.append(
                    _health_row(sid, xy, y_hat_arr, res.diagnostics, res.mapping, comps_full)
                )
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

            if health_rows:
                zf.writestr("fit_health.csv", _health_csv_bytes(health_rows))

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
