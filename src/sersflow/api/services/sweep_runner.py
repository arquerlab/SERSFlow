"""Parameter sweep over one fitting step of a completed analysis run.

Fix one or more parameters of a fitting step at each value of a grid and refit every selected spectrum,
reporting goodness of fit and fit health per grid point. This replaces the manual loop of "edit the
pipeline, start a run, download the observation" used to tune e.g. a shared FWHM.

The pre-fit spectra of the step are collected once (calibration and earlier steps are NOT recomputed per
grid point); only the fit is repeated. Output: ``sweep.zip`` with ``sweep_points.csv`` (one row per
spectrum x grid point) and ``sweep_summary.csv`` (per grid point, aggregated over spectra).
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import logging
import math
import os
import zipfile
from typing import Any

import numpy as np

from sersflow.api.services.fit_curve_export_runner import _max_spectra
from sersflow.api.services.fitting_preview import (
    _collect_fit_input_xy,
    _find_fitting_step,
    _resolved_refs_for_run,
)
from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.core.metrics.fitting_features import _param_keys_for_component
from sersflow.core.pipeline.engine import fitting_region_applies
from sersflow.core.preprocess.fit_diagnostics import diagnostics_as_feature_dict
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.infra.analysis_store import get_fit_curve_job, get_run, update_fit_curve_job
from sersflow.infra.explore_store import artifacts_root
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

logger = logging.getLogger(__name__)

SWEEP_CONTENT = "sweep"

# Hard server-side cap on the number of fits one sweep may perform.
def max_sweep_fits() -> int:
    raw = os.environ.get("SERSFLOW_SWEEP_MAX_FITS", "5000")
    try:
        return max(1, min(int(raw), 200_000))
    except ValueError:
        return 5000


_METRIC_COLUMNS = (
    "rmse",
    "r2",
    "bic",
    "aic",
    "n_vary",
    "n_at_bound",
    "bg_gt_data_frac",
    "resid_mean_edge_lo",
    "resid_mean_edge_hi",
    "resid_lag1_autocorr",
    "success",
)


def grid_points(axes: list[dict[str, Any]]) -> list[tuple[float, ...]]:
    """Cartesian product of the axes' values (axis order preserved)."""
    if not axes:
        raise ValueError("grid must contain at least one axis")
    value_lists: list[list[float]] = []
    for a in axes:
        vals = [float(v) for v in (a.get("values") or [])]
        if not vals or not all(math.isfinite(v) for v in vals):
            raise ValueError(f"axis {a.get('component_id')}.{a.get('key')} needs finite values")
        value_lists.append(vals)
    return list(itertools.product(*value_lists))


def _flat_index(components: list[dict[str, Any]], component_id: str, key: str) -> int:
    cursor = 0
    for row in components:
        keys = _param_keys_for_component(row)
        if str(row.get("component_id")) == component_id:
            if key not in keys:
                raise ValueError(f"component {component_id!r} has no parameter {key!r} (has: {keys})")
            return cursor + keys.index(key)
        cursor += len(keys)
    raise ValueError(f"unknown component_id {component_id!r}")


def _fixed_params(
    step_params: dict[str, Any],
    axes: list[dict[str, Any]],
    values: tuple[float, ...],
) -> dict[str, Any]:
    """Copy of the step params with each axis parameter fixed (vary=False) at its grid value."""
    out = dict(step_params)
    comps = [c for c in (out.get("components") or []) if isinstance(c, dict)]
    n = sum(len(_param_keys_for_component(c)) for c in comps)
    p0 = list(out.get("p0") or [])
    lo = list(out.get("bounds_lower") or [])
    hi = list(out.get("bounds_upper") or [])
    vary = list(out.get("vary") or [True] * n)
    if len(p0) != n or len(lo) != n or len(hi) != n or len(vary) != n:
        raise ValueError("fitting step has inconsistent p0 / bounds / vary lengths")
    for axis, v in zip(axes, values):
        i = _flat_index(comps, str(axis["component_id"]), str(axis["key"]))
        p0[i] = float(v)
        vary[i] = False
        # Keep the fixed value inside its bounds so the fit does not reject it.
        if lo[i] is not None:
            lo[i] = min(float(lo[i]), float(v))
        if hi[i] is not None:
            hi[i] = max(float(hi[i]), float(v))
    out.update({"p0": p0, "bounds_lower": lo, "bounds_upper": hi, "vary": vary})
    return out


def _fmt(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, float) and not math.isfinite(v):
        return ""
    return v


def _summary_rows(axes_names: list[str], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_grid: dict[tuple, list[dict[str, Any]]] = {}
    for p in points:
        by_grid.setdefault(tuple(p["grid"]), []).append(p)
    rows: list[dict[str, Any]] = []
    for grid, ps in by_grid.items():
        def mean(key: str) -> float | None:
            vals = [q[key] for q in ps if isinstance(q.get(key), (int, float)) and math.isfinite(q[key])]
            return float(np.mean(vals)) if vals else None

        def worst(key: str) -> float | None:
            vals = [q[key] for q in ps if isinstance(q.get(key), (int, float)) and math.isfinite(q[key])]
            return float(np.max(vals)) if vals else None

        n_fail = sum(1 for q in ps if q.get("error"))
        row = {name: v for name, v in zip(axes_names, grid)}
        row.update(
            {
                "n_spectra": len(ps),
                "n_failed": n_fail,
                "rmse_mean": mean("rmse"),
                "rmse_max": worst("rmse"),
                "bic_mean": mean("bic"),
                "resid_lag1_autocorr_mean": mean("resid_lag1_autocorr"),
                "bg_gt_data_frac_mean": mean("bg_gt_data_frac"),
                "resid_mean_edge_hi_mean": mean("resid_mean_edge_hi"),
                "resid_mean_edge_lo_mean": mean("resid_mean_edge_lo"),
                "n_at_bound_total": float(sum(q["n_at_bound"] for q in ps if isinstance(q.get("n_at_bound"), (int, float)))),
            }
        )
        rows.append(row)
    rows.sort(key=lambda r: (r["rmse_mean"] is None, r["rmse_mean"] if r["rmse_mean"] is not None else 0.0))
    return rows


def _csv_bytes(headers: list[str], rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([_fmt(r.get(h)) for h in headers])
    return buf.getvalue().encode("utf-8")


def execute_sweep_job(job_id: str) -> None:
    rec = get_fit_curve_job(job_id)
    if rec is None:
        logger.error("sweep job not found: %s", job_id)
        return
    try:
        update_fit_curve_job(job_id=job_id, status="running", finished=False)
        run = get_run(rec.run_id)
        if run is None:
            raise ValueError("analysis run not found")
        if run.status != "completed":
            raise ValueError("analysis run is not completed")
        opts = json.loads(rec.params_json or "{}")
        axes: list[dict[str, Any]] = list(opts.get("grid") or [])
        spectrum_ids = opts.get("spectrum_ids")
        points_grid = grid_points(axes)
        axes_names = [f"{a['component_id']}.{a['key']}" for a in axes]

        pipeline, _ds, refs, ns = _resolved_refs_for_run(run, list(spectrum_ids) if spectrum_ids else None)
        if len(refs) > _max_spectra():
            raise ValueError(f"too many spectra (max {_max_spectra()})")
        fitting_idx, fitting_step = _find_fitting_step(pipeline, rec.fitting_step_num)
        step_params = dict(fitting_step.params or {})
        tech = getattr(pipeline, "technique_family", None)
        if tech and "technique_family" not in step_params:
            step_params["technique_family"] = tech

        xy_by_id = _collect_fit_input_xy(
            pipeline=pipeline, refs=refs, ns=ns, fitting_idx=fitting_idx, fitting_step_num=rec.fitting_step_num
        )
        paths = sorted({str(r.relative_path) for r in refs if r.relative_path})
        con = with_connection()
        try:
            labels_by_path = fetch_upload_labels_for_paths(con, paths)
        finally:
            con.close()

        applicable: list[tuple[Any, Any, dict[str, Any]]] = []
        for r in refs:
            xy = xy_by_id.get(str(r.spectrum_id))
            if xy is None or xy.x.size == 0:
                continue
            ri = r.record_index if isinstance(r.record_index, int) else None
            row = _labels_for_spectrum(labels_by_path.get(str(r.relative_path)) or {}, record_index=ri)
            raw_region = row.get("xps_region")
            region = str(raw_region).strip() if raw_region is not None and str(raw_region).strip() else None
            if not fitting_region_applies(step_params=step_params, spectrum_xps_region=region):
                continue
            applicable.append((r, xy, row))
        n_fits = len(applicable) * len(points_grid)
        if n_fits == 0:
            raise ValueError("no spectrum of the cohort belongs to this fitting step's region")
        if n_fits > max_sweep_fits():
            raise ValueError(
                f"sweep needs {n_fits} fits ({len(applicable)} spectra x {len(points_grid)} grid points); "
                f"server limit is {max_sweep_fits()} (SERSFLOW_SWEEP_MAX_FITS)"
            )
        update_fit_curve_job(job_id=job_id, progress_done=0, progress_total=n_fits)

        comps = [c for c in (step_params.get("components") or []) if isinstance(c, dict)]
        param_names: list[str] = []
        for c in comps:
            for k in _param_keys_for_component(c):
                param_names.append(f"p:{c.get('component_id')}.{k}")

        point_rows: list[dict[str, Any]] = []
        done = 0
        for grid in points_grid:
            fixed = _fixed_params(step_params, axes, grid)
            for r, xy, label_row in applicable:
                rowd: dict[str, Any] = {
                    "spectrum_id": str(r.spectrum_id),
                    "experiment_id": label_row.get("experiment_id"),
                    "current_density_A_cm2": label_row.get("current_density_A_cm2"),
                    "grid": list(grid),
                    "error": None,
                }
                rowd.update({name: v for name, v in zip(axes_names, grid)})
                try:
                    prob = fit_problem_from_step_params(xy, fixed)
                    if prob is None:
                        raise ValueError("empty spectrum / fit window")
                    res = fit_curve(prob)
                    metrics = diagnostics_as_feature_dict(res.diagnostics)
                    rowd.update({k: metrics.get(k) for k in _METRIC_COLUMNS})
                    for name, v in zip(param_names, res.p_opt.astype(float).tolist()):
                        rowd[name] = v
                except Exception as e:  # one bad fit must not kill the sweep
                    rowd["error"] = f"{type(e).__name__}: {e}"
                point_rows.append(rowd)
                done += 1
                if done % 10 == 0 or done == n_fits:
                    update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=n_fits)

        out_dir = os.path.join(artifacts_root(), "fit_curve_jobs", job_id)
        os.makedirs(out_dir, exist_ok=True)
        zip_path = os.path.join(out_dir, "export.zip")
        point_headers = (
            ["spectrum_id", "experiment_id", "current_density_A_cm2", *axes_names, *_METRIC_COLUMNS, "error", *param_names]
        )
        summary = _summary_rows(axes_names, point_rows)
        summary_headers = [
            *axes_names,
            "n_spectra",
            "n_failed",
            "rmse_mean",
            "rmse_max",
            "bic_mean",
            "resid_lag1_autocorr_mean",
            "bg_gt_data_frac_mean",
            "resid_mean_edge_hi_mean",
            "resid_mean_edge_lo_mean",
            "n_at_bound_total",
        ]
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("sweep_summary.csv", _csv_bytes(summary_headers, summary))
            zf.writestr("sweep_points.csv", _csv_bytes(point_headers, point_rows))
        update_fit_curve_job(
            job_id=job_id,
            status="completed",
            progress_done=n_fits,
            progress_total=n_fits,
            artifact_path=zip_path,
            finished=True,
        )
    except Exception as e:
        logger.exception("sweep job failed: %s", job_id)
        update_fit_curve_job(job_id=job_id, status="failed", error=str(e), finished=True)
