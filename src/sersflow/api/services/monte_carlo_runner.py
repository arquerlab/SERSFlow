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

import json
import logging
import os
import zipfile
from typing import Any

import numpy as np

from sersflow.core.metrics.fit_uncertainty import component_uncertainty_rows, run_monte_carlo, spread
from sersflow.core.pipeline.engine import run_in_pipeline_pool
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.infra.analysis_store import update_fit_curve_job
from sersflow.api.services.fit_job_common import (
    applicable_spectra,
    fit_job_dir,
    fit_job_lifecycle,
    load_fit_job_context,
)
from sersflow.core.jsonutil import finite_or_none as _fin, rows_to_csv_bytes as _csv_bytes

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


def _mc_spectrum_task(task: dict[str, Any]) -> dict[str, Any]:
    """Pool worker: best fit + Monte Carlo of ONE spectrum. Errors are returned, not raised (one bad spectrum
    must not kill the job)."""
    try:
        rows, reps, meta = monte_carlo_for_spectrum(
            task["xy"], task["step_params"], n_replicates=task["n_replicates"], seed=task["seed"], progress=task.get("progress")
        )
        return {"rows": rows, "reps": reps, "meta": meta, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def execute_monte_carlo_job(job_id: str) -> None:
    with fit_job_lifecycle(job_id, "monte carlo", logger) as rec:
        if rec is None:
            return
        opts = json.loads(rec.params_json or "{}")
        n_rep = int(opts.get("n_replicates") or 100)
        seed = int(opts.get("seed") or 0)
        ctx = load_fit_job_context(rec, spectrum_ids=opts.get("spectrum_ids"))
        step_params = ctx.step_params
        applicable = applicable_spectra(ctx)
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
        # One task per spectrum; the seed belongs to the spectrum (seed + index), so the numbers do not depend
        # on the order in which the worker processes finish.
        tasks = [
            {"xy": xy, "step_params": step_params, "n_replicates": n_rep, "seed": seed + idx}
            for idx, (_r, xy, _row) in enumerate(applicable)
        ]
        if len(tasks) == 1:
            # A single spectrum gains nothing from the pool; run it here and keep per-replicate progress.
            def progress(k: int, n: int) -> None:
                if k % 10 == 0 or k == n:
                    update_fit_curve_job(job_id=job_id, progress_done=k, progress_total=n_fits)

            results = [_mc_spectrum_task({**tasks[0], "progress": progress})]
        else:
            finished = 0

            def on_result(_i: int, _res: Any) -> None:
                nonlocal finished
                finished += 1
                update_fit_curve_job(job_id=job_id, progress_done=finished * n_rep, progress_total=n_fits)

            results = run_in_pipeline_pool(_mc_spectrum_task, tasks, on_result)

        for (r, _xy, label_row), res in zip(applicable, results):
            labels = {
                "spectrum_id": str(r.spectrum_id),
                "experiment_id": label_row.get("experiment_id"),
                "current_density_A_cm2": label_row.get("current_density_A_cm2"),
            }
            if res.get("error") is None:
                summary_rows.extend({**labels, **row} for row in res["rows"])
                replicate_rows.extend({**labels, **rep} for rep in res["reps"])
                spectra_meta.append({**labels, **res["meta"], "error": None})
            else:
                spectra_meta.append({**labels, "error": res["error"]})
        update_fit_curve_job(job_id=job_id, progress_done=n_fits, progress_total=n_fits)

        rep_cols_seen: dict[str, None] = {}
        for rr in replicate_rows:
            for k in rr:
                rep_cols_seen.setdefault(k, None)
        rep_cols = list(rep_cols_seen)
        summary = {
            "run_id": rec.run_id,
            "fitting_step_num": rec.fitting_step_num,
            "n_replicates": n_rep,
            "seed": seed,
            "spectra": spectra_meta,
            "rows": summary_rows,
        }
        out_dir = fit_job_dir(job_id)
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


def read_monte_carlo_summary(artifact_path: str) -> dict[str, Any]:
    with open(os.path.join(os.path.dirname(artifact_path), SUMMARY_JSON), encoding="utf-8") as f:
        return json.load(f)
