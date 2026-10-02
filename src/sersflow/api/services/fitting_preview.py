"""On-demand fitting preview for analysis runs (evaluate stored params; no re-fit)."""

from __future__ import annotations

import logging
from typing import Any

from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.analysis_runner import (
    _effective_pipeline_for_analysis,
    prepare_run_context,
)
from sersflow.api.services.fit_diagnostics_public import diagnostics_to_public
from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.api.services.pipeline_qc import apply_pipeline_qc_filters, pipeline_without_qc_steps
from sersflow.api.services.reference_runtime import filter_reference_spectra, hydrate_reference_transforms
from sersflow.api.services.sessions_service import resolve_subset_indices
from sersflow.core.metrics.fitting_features import p_opt_and_gof_from_features
from sersflow.core.pipeline.engine import EngineConfig, fitting_region_applies, run_pipeline_parallel_no_cache
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.preprocess.fitting import evaluate_fit_curves, fit_problem_from_step_params
from sersflow.infra.analysis_store import get_run as store_get_run
from sersflow.infra.analysis_store import get_spectrum_features_for_ids
from sersflow.infra.datasets_store import get_dataset_internal
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

logger = logging.getLogger(__name__)

_ANALYSIS_COHORT = SubsetStrategy(kind="all")


def _find_fitting_step(pipeline: Any, fitting_step_num: int) -> tuple[int, Any]:
    steps = pipeline.steps
    sns = assign_pipeline_step_nums(steps)
    for i, step in enumerate(steps):
        if not getattr(step, "enabled", True):
            continue
        if step.name != "fitting":
            continue
        if int(sns[i]) == int(fitting_step_num):
            return i, step
    raise ValueError(f"No enabled fitting step with step_num={fitting_step_num}")


def list_fitting_steps_for_pipeline(pipeline: Any) -> list[dict[str, Any]]:
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not getattr(step, "enabled", True) or step.name != "fitting":
            continue
        params = step.params or {}
        region = params.get("xps_region")
        out.append(
            {
                "step_num": int(sns[i]),
                "step_index": i,
                "xps_region": str(region).strip() if region is not None and str(region).strip() else None,
                "n_components": len(params.get("components") or [])
                if isinstance(params.get("components"), list)
                else 0,
            }
        )
    return out


def _resolved_refs_for_run(rec: Any, spectrum_ids: list[str] | None) -> tuple[Any, Any, list[Any], str]:
    pipeline, _preview_subset, sess = prepare_run_context(rec=rec)
    effective_pipeline, _ = _effective_pipeline_for_analysis(pipeline)
    ds = get_dataset_internal(rec.dataset_id)
    if ds is None:
        raise ValueError("dataset not found")
    ns = (sess.cache.cache_namespace if sess and sess.cache else None) or rec.run_id
    effective_pipeline = hydrate_reference_transforms(effective_pipeline, ds, cache_namespace=ns)
    indices = resolve_subset_indices(dataset=ds, subset=_ANALYSIS_COHORT, pipeline=effective_pipeline)
    refs = filter_reference_spectra([ds.spectra[i] for i in indices], effective_pipeline)
    refs, _qc = apply_pipeline_qc_filters(
        dataset=ds,
        pipeline=effective_pipeline,
        refs=refs,
        cache_namespace=ns,
        strict=True,
    )
    effective_pipeline = pipeline_without_qc_steps(effective_pipeline)
    if spectrum_ids is not None:
        wanted = set(spectrum_ids)
        refs = [r for r in refs if r.spectrum_id in wanted]
        missing = wanted - {r.spectrum_id for r in refs}
        if missing:
            raise ValueError(f"spectrum_ids not in analysis cohort: {sorted(missing)[:5]}")
    return effective_pipeline, ds, refs, ns


def _pipeline_steps_without_fitting(pipeline: Any, *, fitting_idx: int) -> list[dict[str, Any]]:
    """
    Disable every fitting step and all steps after the target fitting index so the
    engine never re-runs fit_curve while still collecting pre-fit XY inputs.
    """
    out: list[dict[str, Any]] = []
    for i, s in enumerate(pipeline.steps):
        enabled = bool(getattr(s, "enabled", True))
        if i >= fitting_idx or s.name == "fitting":
            enabled = False
        out.append(
            {
                "name": s.name,
                "params": s.params,
                "enabled": enabled,
                "impl_version": s.impl_version,
                "step_id": s.step_id,
                "input_from": s.input_from,
                "after_step_id": s.after_step_id,
            }
        )
    return out


def _collect_fit_input_xy(
    *,
    pipeline: Any,
    refs: list[Any],
    ns: str,
    fitting_idx: int,
    fitting_step_num: int,
) -> dict[str, Any]:
    steps = _pipeline_steps_without_fitting(pipeline, fitting_idx=fitting_idx)
    step_nums = assign_pipeline_step_nums(pipeline.steps)
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
        max_workers=min(8, max(1, len(inputs))),
        technique_family=getattr(pipeline, "technique_family", None),
    )
    if not isinstance(packed, tuple):
        raise RuntimeError("expected (final, per_step_inputs)")
    _final, per_inputs = packed
    return {sid: (pin.get(int(fitting_step_num)) if isinstance(pin, dict) else None) for sid, pin in per_inputs.items()}


def fitting_preview_for_run(
    *,
    run_id: str,
    spectrum_ids: list[str],
    fitting_step_num: int,
    return_curve: bool = True,
) -> dict[str, Any]:
    if not spectrum_ids:
        raise ValueError("spectrum_ids must be non-empty")
    if len(spectrum_ids) > 50:
        raise ValueError("spectrum_ids max is 50 per request")

    rec = store_get_run(run_id)
    if rec is None:
        raise ValueError("analysis run not found")
    if rec.status != "completed":
        raise ValueError("analysis run is not completed")

    effective_pipeline, _ds, refs, ns = _resolved_refs_for_run(rec, spectrum_ids)
    fitting_idx, fitting_step = _find_fitting_step(effective_pipeline, fitting_step_num)
    step_params = dict(fitting_step.params or {})
    tech = getattr(effective_pipeline, "technique_family", None)
    if tech and "technique_family" not in step_params:
        step_params["technique_family"] = tech

    features_by_id = get_spectrum_features_for_ids(run_id=run_id, spectrum_ids=[str(r.spectrum_id) for r in refs])
    xy_by_id = _collect_fit_input_xy(
        pipeline=effective_pipeline,
        refs=refs,
        ns=ns,
        fitting_idx=fitting_idx,
        fitting_step_num=fitting_step_num,
    )

    paths = sorted({str(r.relative_path) for r in refs if r.relative_path})
    con = with_connection()
    try:
        labels_by_path = fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()

    items: list[dict[str, Any]] = []
    for r in refs:
        sid = str(r.spectrum_id)
        xy = xy_by_id.get(sid)
        if xy is None or xy.x.size == 0:
            items.append(
                {
                    "spectrum_id": sid,
                    "error": "no pipeline input XY for fitting step",
                    "x": [],
                    "y": [],
                    "y_hat": None,
                    "residual": None,
                    "components": [],
                    "diagnostics": None,
                }
            )
            continue
        ri = r.record_index if isinstance(r.record_index, int) else None
        row = _labels_for_spectrum(labels_by_path.get(str(r.relative_path)) or {}, record_index=ri)
        raw_region = row.get("xps_region")
        spectrum_region = (
            str(raw_region).strip() if raw_region is not None and str(raw_region).strip() else None
        )
        if not fitting_region_applies(step_params=step_params, spectrum_xps_region=spectrum_region):
            items.append(
                {
                    "spectrum_id": sid,
                    "error": "fitting xps_region does not apply to this spectrum",
                    "x": xy.x.astype(float).tolist(),
                    "y": xy.y.astype(float).tolist(),
                    "y_hat": None,
                    "residual": None,
                    "components": [],
                    "diagnostics": None,
                }
            )
            continue

        feat = features_by_id.get(sid) or {}
        p_opt, stored_diag, err = p_opt_and_gof_from_features(
            pipeline=effective_pipeline,
            fitting_step_num=fitting_step_num,
            features=feat,
        )
        if p_opt is None:
            items.append(
                {
                    "spectrum_id": sid,
                    "error": err or "missing stored fit parameters",
                    "x": xy.x.astype(float).tolist(),
                    "y": xy.y.astype(float).tolist(),
                    "y_hat": None,
                    "residual": None,
                    "components": [],
                    "diagnostics": diagnostics_to_public(stored_diag) if stored_diag else None,
                }
            )
            continue

        try:
            prob = fit_problem_from_step_params(xy, step_params)
            if prob is None:
                raise ValueError("empty spectrum")
            res = evaluate_fit_curves(prob, p_opt, diagnostics=stored_diag)
        except (ValueError, RuntimeError, ImportError) as e:
            items.append(
                {
                    "spectrum_id": sid,
                    "error": str(e),
                    "x": xy.x.astype(float).tolist(),
                    "y": xy.y.astype(float).tolist(),
                    "y_hat": None,
                    "residual": None,
                    "components": [],
                    "diagnostics": diagnostics_to_public(stored_diag) if stored_diag else None,
                }
            )
            continue

        comps_out = []
        for idx, m in enumerate(res.mapping):
            s, e = m["index_range"]
            keys = m["param_keys"]
            vals = res.p_opt[s:e].astype(float).tolist()
            yc = res.component_y_hat[idx].astype(float).tolist() if return_curve else None
            comps_out.append(
                {
                    "component_id": m["component_id"],
                    "component_type": m["component_type"],
                    "degree": m.get("degree"),
                    "param_keys": keys,
                    "params": {k: float(v) for k, v in zip(keys, vals)},
                    "y_hat": yc,
                }
            )
        y_hat = res.y_hat.astype(float)
        y_in = xy.y.astype(float)
        items.append(
            {
                "spectrum_id": sid,
                "error": None,
                "x": xy.x.astype(float).tolist(),
                "y": y_in.tolist(),
                "y_hat": y_hat.tolist() if return_curve else None,
                "residual": (y_in - y_hat).tolist() if return_curve else None,
                "components": comps_out,
                "diagnostics": diagnostics_to_public(res.diagnostics),
            }
        )

    return {
        "run_id": run_id,
        "fitting_step_num": int(fitting_step_num),
        "items": items,
    }


def iter_all_refs_for_fit_export(run_id: str) -> tuple[Any, Any, list[Any], str, int]:
    """Return (pipeline, ds, refs, ns, fitting ready). Used by export jobs."""
    rec = store_get_run(run_id)
    if rec is None:
        raise ValueError("analysis run not found")
    if rec.status != "completed":
        raise ValueError("analysis run is not completed")
    effective_pipeline, ds, refs, ns = _resolved_refs_for_run(rec, None)
    return effective_pipeline, ds, refs, ns, rec
