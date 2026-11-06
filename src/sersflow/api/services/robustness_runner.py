"""Robustness study job: a factorial design of analyst choices, refitted over a run's spectra.

For a completed analysis run and one of its fitting steps, every cell of a factorial design (see
``core.robustness``) is fitted on every selected spectrum. Cells may change the fitting step (background, window,
line shape, constraints, ...) and/or any UPSTREAM step (baseline, smoothing, ...); cells that share their upstream
patches share their pre-fit spectra, so the pipeline up to the fit runs once per distinct upstream setting.

Execution
    * parallel: tasks (spectrum x upstream group x chunk of cells) run in a process pool
      (``workers`` option / ``SERSFLOW_ROBUSTNESS_WORKERS``); ``workers=1`` runs inline with identical results;
    * resumable: every finished record is appended to ``robustness_records.jsonl``; a job started again with the same
      id skips the (spectrum, cell) pairs already on disk;
    * multi-start per cell, optional counting-noise Monte Carlo on a reference cell (the comparison baseline);
    * the pre-run cost estimate is checked against ``SERSFLOW_ROBUSTNESS_MAX_FITS`` unless ``allow_large``.

Output ``robustness.zip``: ``summary.json`` (everything, per response), ``design.csv``, ``variant_points.csv``
(one row per spectrum x cell), ``anova.csv``, ``trend.csv``, ``bands.csv``, ``noise_comparison.csv``,
``filter_report.csv``, ``provenance.json``. The jsonl records allow re-analysis (other responses / filters /
interaction order) without refitting: ``reanalyse_job``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import numpy as np

from sersflow.api.services.fit_curve_export_runner import _max_spectra
from sersflow.api.services.fitting_preview import (
    _collect_fit_input_xy,
    _find_fitting_step,
    _resolved_refs_for_run,
)
from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.core.metrics.fit_uncertainty import run_monte_carlo
from sersflow.core.pipeline.engine import fitting_region_applies
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.provenance import software_info
from sersflow.core.robustness.cell_fit import common_window, fit_cell
from sersflow.core.robustness.design import Design, DesignError, build_design, estimate_cost
from sersflow.core.robustness.patches import (
    _norm_target,
    apply_fit_patches,
    apply_params_patch,
    resolve_step_index,
)
from sersflow.core.robustness.responses import evaluate_responses, validate_responses
from sersflow.core.robustness.study import apply_filter, summarize_study
from sersflow.infra.analysis_store import get_fit_curve_job, get_run, update_fit_curve_job
from sersflow.infra.explore_store import artifacts_root
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

logger = logging.getLogger(__name__)

ROBUSTNESS_CONTENT = "robustness"
SUMMARY_JSON = "robustness_summary.json"
RECORDS_JSONL = "robustness_records.jsonl"
NOISE_JSONL = "robustness_noise.jsonl"
CHUNK_CELLS = 16


def max_robustness_fits() -> int:
    raw = os.environ.get("SERSFLOW_ROBUSTNESS_MAX_FITS", "20000")
    try:
        return max(1, min(int(raw), 5_000_000))
    except ValueError:
        return 20000


def default_workers() -> int:
    raw = os.environ.get("SERSFLOW_ROBUSTNESS_WORKERS")
    if raw:
        try:
            return max(1, min(int(raw), 128))
        except ValueError:
            pass
    return max(1, min(os.cpu_count() or 1, 8))


# --------------------------------------------------------------------------------------------------------------
# options
# --------------------------------------------------------------------------------------------------------------

def parse_options(opts: dict[str, Any]) -> dict[str, Any]:
    """Validate the job options; returns the design and normalised options."""
    try:
        design = build_design(
            opts.get("factors"),
            max_cells=opts.get("max_cells"),
            interaction_order=opts.get("interaction_order"),
            subsample=opts.get("subsample"),
        )
    except DesignError as e:
        raise ValueError(str(e)) from e
    responses = validate_responses(opts.get("responses"))
    noise = dict(opts.get("noise") or {})
    n_rep = int(noise.get("n_replicates") or 0)
    if n_rep and not 2 <= n_rep <= 2000:
        raise ValueError("noise.n_replicates must be 0 (off) or 2..2000")
    ref = noise.get("reference_cell")
    if ref is not None and ref not in {c.cell_id for c in design.cells}:
        raise ValueError(f"noise.reference_cell {ref!r} is not a cell of the design")
    return {
        "design": design,
        "responses": responses,
        "n_starts": max(1, int(opts.get("n_starts") or 1)),
        "seed": int(opts.get("seed") or 0),
        "jitter_frac": float(opts.get("jitter_frac") or 0.15),
        "cost_tol": float(opts.get("cost_tol") or 0.005),
        "resp_tol_rel": float(opts.get("resp_tol_rel") or 0.02),
        "resp_tol_abs": float(opts.get("resp_tol_abs") or 1e-3),
        "x_label": (str(opts["x_label"]).strip() or None) if opts.get("x_label") else None,
        "filter": opts.get("filter") or {"mode": "none"},
        "noise_replicates": n_rep,
        "noise_reference_cell": ref or design.cells[0].cell_id,
        "noise_seed": int(noise.get("seed") or 0),
        "reference_cell": opts.get("reference_cell"),
        "workers": int(opts.get("workers") or default_workers()),
        "allow_large": bool(opts.get("allow_large")),
    }


def estimate_for_options(opts: dict[str, Any], n_spectra: int) -> dict[str, Any]:
    p = parse_options(opts)
    d: Design = p["design"]
    est = estimate_cost(
        n_cells=len(d.cells),
        n_spectra=n_spectra,
        n_starts=p["n_starts"],
        n_upstream_groups=d.n_upstream_groups(),
        noise_replicates=p["noise_replicates"],
    )
    est["server_limit"] = max_robustness_fits()
    est["exceeds_limit"] = est["n_total_fits"] > est["server_limit"]
    est["design"] = d.to_public_dict()
    return est


# --------------------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------------------

def _sanitize(o: Any) -> Any:
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitize(v) for v in o]
    if isinstance(o, np.generic):
        return _sanitize(o.item())
    return o


def _fmt(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, float) and not math.isfinite(v):
        return ""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return v


def _csv_bytes(headers: list[str], rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([_fmt(r.get(h)) for h in headers])
    return buf.getvalue().encode("utf-8")


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line after a crash: that record is simply refitted
    return out


def patched_pipeline(pipeline: Any, upstream_patches: list[dict[str, Any]], fitting_idx: int) -> tuple[Any, int]:
    """Copy of the pipeline with the upstream patches applied; also the fitting step_num in the copy."""
    p = pipeline.model_copy(deep=True)
    steps = p.steps
    for patch in upstream_patches:
        idx = resolve_step_index(
            steps, _norm_target(patch), get_name=lambda s: s.name, get_id=lambda s: s.step_id
        )
        if idx == fitting_idx:
            raise ValueError("an upstream patch cannot target the fitting step under study")
        step = steps[idx]
        if patch["op"] == "set_step_enabled":
            step.enabled = bool(patch["enabled"])
        else:
            step.params = apply_params_patch(dict(step.params or {}), patch)
    nums = assign_pipeline_step_nums(steps)
    return p, int(nums[fitting_idx])


def _make_pool(workers: int) -> ProcessPoolExecutor:
    # BLAS threads multiply with processes; spawned children inherit these.
    for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    return ProcessPoolExecutor(max_workers=workers)


# --------------------------------------------------------------------------------------------------------------
# worker tasks (module level: picklable)
# --------------------------------------------------------------------------------------------------------------

def _cell_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for cell_id, fit_patches in task["cells"]:
        rec = fit_cell(
            task["xy"],
            task["base_params"],
            list(fit_patches),
            spectrum_id=task["spectrum_id"],
            cell_id=cell_id,
            responses=task["responses"],
            n_starts=task["n_starts"],
            seed=task["seed"],
            window=task["window"],
            jitter_frac=task["jitter_frac"],
            cost_tol=task["cost_tol"],
            resp_tol_rel=task["resp_tol_rel"],
            resp_tol_abs=task["resp_tol_abs"],
        )
        out.append(_sanitize(rec))
    return out


def _noise_task(task: dict[str, Any]) -> dict[str, Any]:
    rec: dict[str, Any] = {"spectrum_id": task["spectrum_id"], "cell_id": task["cell_id"], "error": None}
    try:
        params = apply_fit_patches(task["base_params"], list(task["fit_patches"]))
        prob = fit_problem_from_step_params(task["xy"], params)
        if prob is None:
            raise ValueError("empty spectrum / fit window")
        res = fit_curve(prob)
        mc = run_monte_carlo(prob, res, n_replicates=task["n_replicates"], seed=task["seed"])
        vals: dict[str, list[float | None]] = {s["name"]: [] for s in task["responses"]}
        for row in mc.params:
            ev = evaluate_responses(task["responses"], res.mapping, row)
            for k, v in ev.items():
                vals[k].append(v)
        rec.update({"values": vals, "n_ok": mc.n_ok, "n_requested": mc.n_requested, "noise_model": mc.noise_model})
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    return _sanitize(rec)


def run_tasks(tasks: list[dict[str, Any]], fn, workers: int, on_result) -> None:
    """Run tasks inline (workers<=1) or in a process pool; ``on_result`` is called in the caller's thread."""
    if not tasks:
        return
    if workers <= 1 or len(tasks) == 1:
        for t in tasks:
            on_result(fn(t))
        return
    with _make_pool(min(workers, len(tasks))) as pool:
        futs = [pool.submit(fn, t) for t in tasks]
        for f in as_completed(futs):
            on_result(f.result())


# --------------------------------------------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------------------------------------------

_HEALTH = [
    "n_points", "n_common", "weighting", "rmse", "rmse_common", "chi2", "bic", "bic_common", "aic",
    "n_vary", "n_at_bound", "bg_gt_data_frac", "resid_lag1_autocorr", "success",
    "n_starts", "n_starts_ok", "best_start", "n_equivalent_starts", "degenerate", "degenerate_responses",
]


def build_tables(
    design: Design,
    records: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    summary: dict[str, Any],
    kept: set[tuple[str, str]],
    labels_by_spectrum: dict[str, dict[str, Any]],
    x_label: str | None,
) -> dict[str, bytes]:
    names = design.factor_names
    resp_names = [s["name"] for s in responses]
    cell_by_id = {c.cell_id: c for c in design.cells}
    files: dict[str, bytes] = {}

    files["design.csv"] = _csv_bytes(
        ["cell_id", *names, "upstream_group"],
        [
            {"cell_id": c.cell_id, **dict(zip(names, c.levels)), "upstream_group": c.upstream_key}
            for c in design.cells
        ],
    )
    rows = []
    for r in records:
        c = cell_by_id.get(r["cell_id"])
        lab = labels_by_spectrum.get(r["spectrum_id"], {})
        row = {
            "spectrum_id": r["spectrum_id"],
            "experiment_id": lab.get("experiment_id"),
            "cell_id": r["cell_id"],
            **(dict(zip(names, c.levels)) if c else {}),
            "kept": int((r["spectrum_id"], r["cell_id"]) in kept),
            "error": r.get("error"),
            **{h: r.get(h) for h in _HEALTH},
            **{k: v for k, v in (r.get("responses") or {}).items()},
        }
        if x_label:
            row[x_label] = lab.get(x_label)
        rows.append(row)
    head = ["spectrum_id", "experiment_id", *([x_label] if x_label else []), "cell_id", *names, "kept", "error", *_HEALTH, *resp_names]
    files["variant_points.csv"] = _csv_bytes(head, rows)

    anova_rows, trend_rows, band_rows, noise_rows = [], [], [], []
    for rname, block in summary["responses"].items():
        for t in block["anova"]["terms"]:
            anova_rows.append({"response": rname, **{k: v for k, v in t.items()}, "exact": block["anova"]["exact"]})
        tr = block.get("trend")
        if tr:
            for p in tr["per_cell"]:
                trend_rows.append({"response": rname, **{k: v for k, v in p.items() if k != "levels"}, **dict(zip(names, p["levels"]))})
            for b in tr["bands"]:
                band_rows.append({"response": rname, **b})
        nc = block.get("noise_comparison")
        if nc:
            for sid, v in nc["per_spectrum"].items():
                noise_rows.append({"response": rname, "spectrum_id": sid, **v})
    files["anova.csv"] = _csv_bytes(
        ["response", "term", "order", "share_mean", "share_median", "share_min", "share_max", "share_pooled", "n_spectra", "exact"], anova_rows
    )
    files["trend.csv"] = _csv_bytes(
        ["response", "cell_id", *names, "n", "spearman", "slope", "sign", "ordering_vs_median"], trend_rows
    )
    files["bands.csv"] = _csv_bytes(
        ["response", "spectrum_id", "x", "p2_5", "p50", "p97_5", "min", "max", "n"], band_rows
    )
    files["noise_comparison.csv"] = _csv_bytes(
        ["response", "spectrum_id", "choice_var", "noise_var", "choice_sd", "noise_sd", "ratio_var"], noise_rows
    )
    frows = []
    for fname, lv in summary["filter"]["by_level"].items():
        for lname, c in lv.items():
            frows.append({"factor": fname, "level": lname, **c})
    files["filter_report.csv"] = _csv_bytes(["factor", "level", "total", "kept", "removed", "failed"], frows)
    return files


# --------------------------------------------------------------------------------------------------------------
# job
# --------------------------------------------------------------------------------------------------------------

def _x_value(label_row: dict[str, Any], x_label: str | None) -> float | None:
    if not x_label:
        return None
    try:
        f = float(label_row.get(x_label))
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _load_labels(refs: list[Any]) -> dict[str, dict[str, Any]]:
    paths = sorted({str(r.relative_path) for r in refs if r.relative_path})
    con = with_connection()
    try:
        by_path = fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()
    out: dict[str, dict[str, Any]] = {}
    for r in refs:
        ri = r.record_index if isinstance(r.record_index, int) else None
        out[str(r.spectrum_id)] = _labels_for_spectrum(by_path.get(str(r.relative_path)) or {}, record_index=ri)
    return out


def applicable_spectra(refs: list[Any], labels: dict[str, dict[str, Any]], step_params: dict[str, Any]) -> list[Any]:
    out = []
    for r in refs:
        raw = labels.get(str(r.spectrum_id), {}).get("xps_region")
        region = str(raw).strip() if raw is not None and str(raw).strip() else None
        if fitting_region_applies(step_params=step_params, spectrum_xps_region=region):
            out.append(r)
    return out


def execute_robustness_job(job_id: str) -> None:
    rec = get_fit_curve_job(job_id)
    if rec is None:
        logger.error("robustness job not found: %s", job_id)
        return
    try:
        update_fit_curve_job(job_id=job_id, status="running", error="", finished=False)
        run = get_run(rec.run_id)
        if run is None:
            raise ValueError("analysis run not found")
        if run.status != "completed":
            raise ValueError("analysis run is not completed")
        raw_opts = json.loads(rec.params_json or "{}")
        p = parse_options(raw_opts)
        design: Design = p["design"]
        responses = p["responses"]
        spectrum_ids = raw_opts.get("spectrum_ids")

        pipeline, _ds, refs, ns = _resolved_refs_for_run(run, list(spectrum_ids) if spectrum_ids else None)
        if len(refs) > _max_spectra():
            raise ValueError(f"too many spectra (max {_max_spectra()})")
        fitting_idx, fitting_step = _find_fitting_step(pipeline, rec.fitting_step_num)
        base_params = dict(fitting_step.params or {})
        tech = getattr(pipeline, "technique_family", None)
        if tech and "technique_family" not in base_params:
            base_params["technique_family"] = tech

        labels = _load_labels(list(refs))
        refs = applicable_spectra(list(refs), labels, base_params)
        if not refs:
            raise ValueError("no spectrum of the cohort belongs to this fitting step's region")
        n_fits_total = len(refs) * len(design.cells)
        est = estimate_cost(
            n_cells=len(design.cells),
            n_spectra=len(refs),
            n_starts=p["n_starts"],
            n_upstream_groups=design.n_upstream_groups(),
            noise_replicates=p["noise_replicates"],
        )
        if est["n_total_fits"] > max_robustness_fits() and not p["allow_large"]:
            raise ValueError(
                f"study needs {est['n_total_fits']} fits ({len(design.cells)} cells x {len(refs)} spectra x "
                f"{p['n_starts']} starts + noise); server limit is {max_robustness_fits()} "
                "(SERSFLOW_ROBUSTNESS_MAX_FITS). Reduce the design, or set allow_large=true."
            )
        progress_total = n_fits_total + (len(refs) if p["noise_replicates"] else 0)
        update_fit_curve_job(job_id=job_id, progress_done=0, progress_total=progress_total)

        out_dir = os.path.join(artifacts_root(), "fit_curve_jobs", job_id)
        os.makedirs(out_dir, exist_ok=True)
        rec_path = os.path.join(out_dir, RECORDS_JSONL)
        noise_path = os.path.join(out_dir, NOISE_JSONL)
        records = _read_jsonl(rec_path)
        done_keys = {(r["spectrum_id"], r["cell_id"]) for r in records}
        noise_recs = _read_jsonl(noise_path)
        noise_done = {r["spectrum_id"] for r in noise_recs}
        done = len(done_keys)
        update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=progress_total)

        win = common_window(base_params, [c.fit_patches for c in design.cells])
        window = win  # (-inf, +inf) when no cell sets a fit window: the common score then covers the whole fit
        ref_cell = next(c for c in design.cells if c.cell_id == p["noise_reference_cell"])

        groups: dict[str, list[Any]] = {}
        for c in design.cells:
            groups.setdefault(c.upstream_key, []).append(c)

        rec_fh = open(rec_path, "a", encoding="utf-8")
        noise_fh = open(noise_path, "a", encoding="utf-8")
        try:
            for ukey, gcells in groups.items():
                todo_cells = {c.cell_id for c in gcells}
                need_noise = (
                    p["noise_replicates"] > 0
                    and ref_cell.upstream_key == ukey
                    and any(str(r.spectrum_id) not in noise_done for r in refs)
                )
                pending = [
                    (r, [c for c in gcells if (str(r.spectrum_id), c.cell_id) not in done_keys]) for r in refs
                ]
                if not need_noise and not any(cs for _r, cs in pending):
                    continue
                up = list(gcells[0].upstream_patches)
                pl, fit_num = patched_pipeline(pipeline, up, fitting_idx) if up else (pipeline, rec.fitting_step_num)
                xy_by_id = _collect_fit_input_xy(
                    pipeline=pl, refs=refs, ns=ns, fitting_idx=fitting_idx, fitting_step_num=fit_num
                )
                tasks: list[dict[str, Any]] = []
                for r, cs in pending:
                    xy = xy_by_id.get(str(r.spectrum_id))
                    if xy is None or xy.x.size == 0 or not cs:
                        continue
                    for i in range(0, len(cs), CHUNK_CELLS):
                        tasks.append(
                            {
                                "xy": xy,
                                "base_params": base_params,
                                "spectrum_id": str(r.spectrum_id),
                                "cells": [(c.cell_id, list(c.fit_patches)) for c in cs[i : i + CHUNK_CELLS]],
                                "responses": responses,
                                "n_starts": p["n_starts"],
                                "seed": p["seed"],
                                "window": window,
                                "jitter_frac": p["jitter_frac"],
                                "cost_tol": p["cost_tol"],
                                "resp_tol_rel": p["resp_tol_rel"],
                                "resp_tol_abs": p["resp_tol_abs"],
                            }
                        )

                def on_cells(batch: list[dict[str, Any]]) -> None:
                    nonlocal done
                    for rr in batch:
                        rec_fh.write(json.dumps(rr, allow_nan=False) + "\n")
                        records.append(rr)
                        done_keys.add((rr["spectrum_id"], rr["cell_id"]))
                    rec_fh.flush()
                    done += len(batch)
                    update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=progress_total)

                run_tasks(tasks, _cell_task, p["workers"], on_cells)

                if need_noise:
                    ntasks = [
                        {
                            "xy": xy_by_id[str(r.spectrum_id)],
                            "base_params": base_params,
                            "fit_patches": list(ref_cell.fit_patches),
                            "spectrum_id": str(r.spectrum_id),
                            "cell_id": ref_cell.cell_id,
                            "responses": responses,
                            "n_replicates": p["noise_replicates"],
                            "seed": p["noise_seed"] + i,
                        }
                        for i, r in enumerate(refs)
                        if str(r.spectrum_id) not in noise_done
                        and xy_by_id.get(str(r.spectrum_id)) is not None
                        and xy_by_id[str(r.spectrum_id)].x.size > 0
                    ]

                    def on_noise(nr: dict[str, Any]) -> None:
                        nonlocal done
                        noise_fh.write(json.dumps(nr, allow_nan=False) + "\n")
                        noise_fh.flush()
                        noise_recs.append(nr)
                        noise_done.add(nr["spectrum_id"])
                        done += 1
                        update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=progress_total)

                    run_tasks(ntasks, _noise_task, p["workers"], on_noise)
                del xy_by_id
        finally:
            rec_fh.close()
            noise_fh.close()

        summary, files = _finalise(
            design=design,
            records=records,
            noise_recs=noise_recs,
            responses=responses,
            p=p,
            labels=labels,
            raw_opts=raw_opts,
            job_id=job_id,
            run_id=rec.run_id,
            fitting_step_num=rec.fitting_step_num,
            window=window,
            n_spectra=len(refs),
        )
        with open(os.path.join(out_dir, SUMMARY_JSON), "w", encoding="utf-8") as f:
            json.dump(summary, f, allow_nan=False)
        zip_path = os.path.join(out_dir, "export.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in files.items():
                zf.writestr(name, data)
            zf.write(rec_path, RECORDS_JSONL)
        update_fit_curve_job(
            job_id=job_id,
            status="completed",
            progress_done=progress_total,
            progress_total=progress_total,
            artifact_path=zip_path,
            finished=True,
        )
    except Exception as e:
        logger.exception("robustness job failed: %s", job_id)
        update_fit_curve_job(job_id=job_id, status="failed", error=str(e), finished=True)


def _noise_values(noise_recs: list[dict[str, Any]]) -> dict[str, dict[str, list[float]]]:
    out: dict[str, dict[str, list[float]]] = {}
    for n in noise_recs:
        if n.get("error"):
            continue
        for rname, vals in (n.get("values") or {}).items():
            out.setdefault(rname, {})[n["spectrum_id"]] = [v for v in vals if v is not None]
    return out


def _finalise(
    *,
    design: Design,
    records: list[dict[str, Any]],
    noise_recs: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    p: dict[str, Any],
    labels: dict[str, dict[str, Any]],
    raw_opts: dict[str, Any],
    job_id: str,
    run_id: str,
    fitting_step_num: int,
    window: tuple[float, float] | None,
    n_spectra: int,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    x_by = None
    if p["x_label"]:
        x_by = {sid: _x_value(lab, p["x_label"]) for sid, lab in labels.items()}
    summary = summarize_study(
        design,
        records,
        responses,
        x_by_spectrum=x_by,
        filter_spec=p["filter"],
        noise=_noise_values(noise_recs) or None,
        reference_cell=p["reference_cell"],
    )
    kept, _ = apply_filter(records, design, p["filter"])
    summary["meta"] = {
        "job_id": job_id,
        "run_id": run_id,
        "fitting_step_num": fitting_step_num,
        "n_spectra": n_spectra,
        "n_records": len(records),
        "x_label": p["x_label"],
        "common_window": None if window is None else list(window),
        "n_starts": p["n_starts"],
        "seed": p["seed"],
        "noise": {
            "n_replicates": p["noise_replicates"],
            "reference_cell": p["noise_reference_cell"],
            "n_spectra": len([n for n in noise_recs if not n.get("error")]),
            "model": next((n.get("noise_model") for n in noise_recs if n.get("noise_model")), None),
        },
        "comparability": (
            "Native BIC is only comparable between fits of identical data points and weighting. The common-window "
            "score (rmse_common, bic_common) re-scores every fit on the window shared by all cells and is "
            "comparable across windows, backgrounds and constraints, but only between cells with the same "
            "upstream settings (an upstream baseline or normalisation change rescales y)."
        ),
    }
    summary = _sanitize(summary)
    files = build_tables(design, records, responses, summary, kept, labels, p["x_label"])
    files["summary.json"] = json.dumps(summary, indent=1, allow_nan=False).encode("utf-8")
    files["study_spec.json"] = json.dumps(_sanitize(raw_opts), indent=1).encode("utf-8")
    files["provenance.json"] = json.dumps(
        _sanitize({"software": software_info(), "design_hash": design.design_hash(), "job_id": job_id, "run_id": run_id, "seed": p["seed"]}),
        indent=1,
    ).encode("utf-8")
    return summary, files


def read_robustness_summary(artifact_path: str) -> dict[str, Any]:
    with open(os.path.join(os.path.dirname(artifact_path), SUMMARY_JSON), encoding="utf-8") as f:
        return json.load(f)


def reanalyse_job(job_id: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """Recompute the summary of a finished job with other responses / filter / interaction order (no refit)."""
    rec = get_fit_curve_job(job_id)
    if rec is None or rec.content != ROBUSTNESS_CONTENT:
        raise ValueError("robustness job not found")
    if not rec.artifact_path:
        raise ValueError(f"robustness job is not ready (status {rec.status})")
    out_dir = os.path.dirname(rec.artifact_path)
    opts = json.loads(rec.params_json or "{}")
    opts.update({k: v for k, v in overrides.items() if v is not None})
    p = parse_options(opts)
    design: Design = p["design"]
    records = _read_jsonl(os.path.join(out_dir, RECORDS_JSONL))
    noise_recs = _read_jsonl(os.path.join(out_dir, NOISE_JSONL))
    run = get_run(rec.run_id)
    labels: dict[str, dict[str, Any]] = {}
    if p["x_label"] and run is not None:
        sids = sorted({r["spectrum_id"] for r in records})
        pipeline, _ds, refs, _ns = _resolved_refs_for_run(run, sids or None)
        labels = _load_labels(list(refs))
    x_by = {sid: _x_value(lab, p["x_label"]) for sid, lab in labels.items()} if p["x_label"] else None
    # noise values exist only for the responses the job was run with; others are skipped by summarize_study
    summary = summarize_study(
        design,
        records,
        p["responses"],
        x_by_spectrum=x_by,
        filter_spec=p["filter"],
        noise=_noise_values(noise_recs) or None,
        reference_cell=p["reference_cell"],
    )
    return _sanitize(summary)
