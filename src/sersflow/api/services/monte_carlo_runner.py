"""Monte Carlo parameter uncertainties over one fitting step of a completed analysis run (F2).

For every selected spectrum the step is refitted once (best fit), then ``n_replicates`` noisy copies of the best-fit
curve are refitted (noise from the fit's own weighting model; see ``core.metrics.fit_uncertainty``). The pre-fit
spectra are collected once, like the parameter sweep. Output ``export.zip``:

* ``mc_summary.csv``: one row per spectrum x component x quantity (each parameter, ``area``, ``area_pct``) with the
  best-fit value, the covariance 1-sigma error and the Monte Carlo mean / SD / 2.5, 50, 97.5 percentiles;
* ``mc_replicates.csv``: every refitted replicate (wide: parameters, areas and %area per component);
* ``mc_summary.json``: the same summary as JSON (also served by ``GET /analysis/monte-carlo-jobs/{id}/summary``).
"""

from __future__ import annotations

import csv
import io
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
from sersflow.core.metrics.fit_uncertainty import component_uncertainty_rows, run_monte_carlo, spread
from sersflow.core.pipeline.engine import fitting_region_applies
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.infra.analysis_store import get_fit_curve_job, get_run, update_fit_curve_job
from sersflow.infra.explore_store import artifacts_root
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

logger = logging.getLogger(__name__)

MONTE_CARLO_CONTENT = "monte_carlo"
SUMMARY_JSON = "mc_summary.json"


def max_monte_carlo_fits() -> int:
    """Server cap on spectra x replicates per job (``SERSFLOW_MC_MAX_FITS``, default 20000)."""
    raw = os.environ.get("SERSFLOW_MC_MAX_FITS", "20000")
    try:
        return max(1, min(int(raw), 500_000))
    except ValueError:
        return 20000


SUMMARY_HEADERS = [
    "spectrum_id",
    "experiment_id",
    "current_density_A_cm2",
    "component_id",
    "component_type",
    "quantity",
    "best_fit",
    "stderr_cov",
    "mc_mean",
    "mc_sd",
    "mc_p2_5",
    "mc_p50",
    "mc_p97_5",
    "n_ok",
    "n_requested",
    "noise_model",
]


def _fmt(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, float) and not math.isfinite(v):
        return ""
    return v


def _csv_bytes(headers: list[str], rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([_fmt(r.get(h)) for h in headers])
    return buf.getvalue().encode("utf-8")


def _fin(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def monte_carlo_for_spectrum(xy: Any, step_params: dict[str, Any], *, n_replicates: int, seed: int, progress=None):
    """Best fit + Monte Carlo for one spectrum; returns (summary rows without labels, replicate rows, meta)."""
    prob = fit_problem_from_step_params(xy, step_params)
    if prob is None:
        raise ValueError("empty spectrum / fit window")
    res = fit_curve(prob)
    mc = run_monte_carlo(prob, res, n_replicates=n_replicates, seed=seed, progress=progress)
    cov_rows = component_uncertainty_rows(res)
    rows: list[dict[str, Any]] = []
    rep_rows: list[dict[str, Any]] = [{"replicate": k} for k in range(mc.n_ok)]
    for ci, m in enumerate(res.mapping):
        cid = str(m["component_id"])
        keys = list(m["param_keys"])
        s, _e = m["index_range"]
        cr = cov_rows[ci]
        for j, k in enumerate(keys):
            col = mc.params[:, int(s) + j] if mc.n_ok else np.array([])
            sp = spread(col)
            se = cr["stderr"].get(k)
            if se is None and (sp["sd"] is None or sp["sd"] == 0.0):
                continue  # fixed parameter: no uncertainty to report
            rows.append(
                {
                    "component_id": cid,
                    "component_type": m["component_type"],
                    "quantity": k,
                    "best_fit": _fin(res.p_opt[int(s) + j]),
                    "stderr_cov": se,
                    **{f"mc_{a}": b for a, b in sp.items()},
                }
            )
            for r, v in zip(rep_rows, col.tolist()):
                r[f"{cid}.{k}"] = v
        if cr["area"] is not None:
            for qty, arr, se_key in (("area", mc.areas, "area_stderr"), ("area_pct", mc.area_pct, "area_pct_stderr")):
                col = arr[:, ci] if mc.n_ok else np.array([])
                sp = spread(col)
                rows.append(
                    {
                        "component_id": cid,
                        "component_type": m["component_type"],
                        "quantity": qty,
                        "best_fit": cr[qty],
                        "stderr_cov": cr[se_key],
                        **{f"mc_{a}": b for a, b in sp.items()},
                    }
                )
                for r, v in zip(rep_rows, col.tolist()):
                    r[f"{cid}.{qty}"] = v
    meta = {
        "n_ok": mc.n_ok,
        "n_requested": mc.n_requested,
        "noise_model": mc.noise_model,
        "weighting": res.diagnostics.weighting,
        "errors": mc.errors[:20],
    }
    for r in rows:
        r.update({"n_ok": mc.n_ok, "n_requested": mc.n_requested, "noise_model": mc.noise_model})
    return rows, rep_rows, meta


def execute_monte_carlo_job(job_id: str) -> None:
    rec = get_fit_curve_job(job_id)
    if rec is None:
        logger.error("monte carlo job not found: %s", job_id)
        return
    try:
        update_fit_curve_job(job_id=job_id, status="running", finished=False)
        run = get_run(rec.run_id)
        if run is None:
            raise ValueError("analysis run not found")
        if run.status != "completed":
            raise ValueError("analysis run is not completed")
        opts = json.loads(rec.params_json or "{}")
        n_rep = int(opts.get("n_replicates") or 100)
        seed = int(opts.get("seed") or 0)
        spectrum_ids = opts.get("spectrum_ids")

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
        n_fits = len(applicable) * n_rep
        if n_fits == 0:
            raise ValueError("no spectrum of the cohort belongs to this fitting step's region")
        if n_fits > max_monte_carlo_fits():
            raise ValueError(
                f"Monte Carlo needs {n_fits} fits ({len(applicable)} spectra x {n_rep} replicates); "
                f"server limit is {max_monte_carlo_fits()} (SERSFLOW_MC_MAX_FITS)"
            )
        update_fit_curve_job(job_id=job_id, progress_done=0, progress_total=n_fits)

        summary_rows: list[dict[str, Any]] = []
        replicate_rows: list[dict[str, Any]] = []
        spectra_meta: list[dict[str, Any]] = []
        done_base = 0
        for idx, (r, xy, label_row) in enumerate(applicable):
            sid = str(r.spectrum_id)
            labels = {
                "spectrum_id": sid,
                "experiment_id": label_row.get("experiment_id"),
                "current_density_A_cm2": label_row.get("current_density_A_cm2"),
            }

            def progress(k: int, n: int, _base: int = done_base) -> None:
                if k % 10 == 0 or k == n:
                    update_fit_curve_job(job_id=job_id, progress_done=_base + k, progress_total=n_fits)

            try:
                rows, reps, meta = monte_carlo_for_spectrum(
                    xy, step_params, n_replicates=n_rep, seed=seed + idx, progress=progress
                )
                summary_rows.extend({**labels, **row} for row in rows)
                replicate_rows.extend({**labels, **rep} for rep in reps)
                spectra_meta.append({**labels, **meta, "error": None})
            except Exception as e:  # one bad spectrum must not kill the job
                spectra_meta.append({**labels, "error": f"{type(e).__name__}: {e}"})
            done_base += n_rep
            update_fit_curve_job(job_id=job_id, progress_done=done_base, progress_total=n_fits)

        rep_cols: list[str] = []
        for rr in replicate_rows:
            for k in rr:
                if k not in rep_cols:
                    rep_cols.append(k)
        summary = {
            "run_id": rec.run_id,
            "fitting_step_num": rec.fitting_step_num,
            "n_replicates": n_rep,
            "seed": seed,
            "spectra": spectra_meta,
            "rows": summary_rows,
        }
        out_dir = os.path.join(artifacts_root(), "fit_curve_jobs", job_id)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, SUMMARY_JSON), "w", encoding="utf-8") as f:
            json.dump(summary, f, allow_nan=False, default=lambda o: None)
        zip_path = os.path.join(out_dir, "export.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mc_summary.csv", _csv_bytes(SUMMARY_HEADERS, summary_rows))
            zf.writestr("mc_replicates.csv", _csv_bytes(rep_cols, replicate_rows))
            zf.writestr(SUMMARY_JSON, json.dumps(summary, indent=1, allow_nan=False, default=lambda o: None))
        update_fit_curve_job(
            job_id=job_id,
            status="completed",
            progress_done=n_fits,
            progress_total=n_fits,
            artifact_path=zip_path,
            finished=True,
        )
    except Exception as e:
        logger.exception("monte carlo job failed: %s", job_id)
        update_fit_curve_job(job_id=job_id, status="failed", error=str(e), finished=True)


def read_monte_carlo_summary(artifact_path: str) -> dict[str, Any]:
    with open(os.path.join(os.path.dirname(artifact_path), SUMMARY_JSON), encoding="utf-8") as f:
        return json.load(f)
