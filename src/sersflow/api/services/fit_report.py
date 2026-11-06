"""
Publication fit report for a completed analysis run (R1).

``build_fit_report`` returns the machine-readable report (JSON-safe dict) plus figure PNGs; ``core.report.render``
turns it into HTML and Markdown. Values come from the run's stored fit columns (the same numbers as the observation
export and the Analyze fit diagnostics), uncertainties from F2, weighting from F1, constraints from the step's links
(F3/F4). Quantification (Q1/Q2) is not implemented yet and is reported as such.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable

from sersflow.api.services.fit_curve_export_runner import _max_spectra
from sersflow.api.services.fitting_preview import (
    _resolved_refs_for_run,
    fitting_preview_for_run,
    list_fitting_steps_for_pipeline,
)
from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.core.metrics.fitting_features import _param_keys_for_component
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.provenance import file_sha256, software_info
from sersflow.core.report.fit_report_model import (
    CHECKLIST,
    REPORT_SCHEMA,
    casaxps_lineshape,
    optimiser_text,
    parameter_status,
)
from sersflow.infra.analysis_store import get_run
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

logger = logging.getLogger(__name__)

_LABEL_KEYS = (
    "experiment_id",
    "xps_region",
    "block_name",
    "sample",
    "current_density_A_cm2",
    "potential_V",
    "replicate_index",
    "spectrum_role",
)
_PREVIEW_CHUNK = 50

QUANT_NOT_PERFORMED = (
    "Quantification (atomic %) is not part of this report: SpecFlow has no RSF / cross-section library and no "
    "transmission or escape-depth correction yet (gap items Q1/Q2 deferred). Peak areas below are raw, "
    "background-subtracted areas in the units of the processed spectrum."
)


def _fin(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _json_safe(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if hasattr(o, "item") and callable(o.item):
        try:
            return _json_safe(o.item())
        except Exception:
            return str(o)
    if o is None or isinstance(o, (str, int, bool)):
        return o
    return str(o)


def _step_dict(step: Any) -> dict[str, Any]:
    return {
        "name": step.name,
        "step_id": getattr(step, "step_id", None),
        "enabled": bool(getattr(step, "enabled", True)),
        "params": dict(step.params or {}),
    }


def _processing_history(pipeline: Any) -> list[dict[str, Any]]:
    steps = list(getattr(pipeline, "steps", None) or [])
    nums = assign_pipeline_step_nums(steps)
    out = []
    for i, s in enumerate(steps):
        d = _step_dict(s)
        d["step_num"] = int(nums[i])
        d["step_index"] = i
        if s.name == "fitting":
            p = d["params"]
            d["summary"] = {
                "xps_region": p.get("xps_region"),
                "n_components": len(p.get("components") or []),
                "fit_window": [p.get("fit_min_x"), p.get("fit_max_x")],
                "weighting": p.get("weighting") or "auto",
                "n_links": len(p.get("param_links") or []),
                "recipe_ids": p.get("recipe_ids") or ([p["recipe_id"]] if p.get("recipe_id") else []),
            }
        out.append(d)
    return out


def _charge_correction(pipeline: Any, refs: list[Any], ns: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    """Calibration steps (method + reference) and the per-spectrum shift each applied, recomputed for the cohort."""
    steps = list(getattr(pipeline, "steps", None) or [])
    nums = assign_pipeline_step_nums(steps)
    cal = [(i, s) for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "x_axis_calibration"]
    methods = []
    for i, s in cal:
        p = dict(s.params or {})
        methods.append(
            {
                "step_num": int(nums[i]),
                "step_id": getattr(s, "step_id", None),
                "method": p.get("method"),
                "reference": {k: v for k, v in p.items() if k not in ("method", "_delta")},
            }
        )
    if not cal:
        return methods, {}
    deltas: dict[str, dict[str, float]] = {}
    try:
        from sersflow.core.pipeline.engine import _prepare_calibration_cohort

        inputs = [
            {
                "spectrum_id": r.spectrum_id,
                "relative_path": r.relative_path,
                "record_index": r.record_index,
                "blob_id": r.blob_id,
                "blob_relative_path": r.blob_relative_path,
                "original_relative_path": r.original_relative_path,
                "spectrum_labels": getattr(r, "spectrum_labels", None),
            }
            for r in refs
        ]
        step_dicts = [_step_dict(s) for s in steps]
        by_step = _prepare_calibration_cohort(
            inputs, step_dicts, technique_family=getattr(pipeline, "technique_family", None), namespace=ns
        ) or {}
        id_to_num = {getattr(s, "step_id", None): int(nums[i]) for i, s in cal}
        for step_id, per in by_step.items():
            num = id_to_num.get(step_id)
            for sid, d in (per or {}).items():
                deltas.setdefault(str(sid), {})[str(num if num is not None else step_id)] = float(d)
        # Fixed-offset / static methods are not precomputed per cohort: their delta is the parameter.
        from sersflow.core.preprocess.x_axis_calibration import calibration_delta

        for i, s in cal:
            try:
                d = calibration_delta(dict(s.params or {}))
            except ValueError:
                continue
            for r in refs:
                deltas.setdefault(str(r.spectrum_id), {}).setdefault(str(int(nums[i])), float(d))
    except Exception as e:  # report what we can, never fail the report on this
        logger.warning("charge-correction shifts not recomputed: %s", e)
        for m in methods:
            m["shift_error"] = f"{type(e).__name__}: {e}"
    return methods, deltas


def _acquisition(ds: Any, sid: str) -> dict[str, Any]:
    from sersflow.api.services.vamas_acquisition import vamas_acquisition_payload

    try:
        acq = vamas_acquisition_payload(ds, sid, include_arrays=False)
    except (KeyError, ValueError) as e:
        return {"available": False, "note": str(e)}
    keep = (
        "technique",
        "source_label",
        "excitation_energy_eV",
        "analyser_mode",
        "pass_energy_eV",
        "x_step_eV",
        "dwell_time_s",
        "n_scans",
        "y_unit",
        "signal_mode",
        "n_points",
        "max_channel_counts",
        "max_channel_cps",
        "source_analyser_angle_deg",
        "source_polar_deg",
        "analyser_polar_deg",
        "aux_arrays",
    )
    return {"available": True, **{k: acq.get(k) for k in keep}}


def _component_rows(step_params: dict[str, Any], item: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Component table rows (peaks) and the background description for one fitted spectrum."""
    comps = [c for c in (step_params.get("components") or []) if isinstance(c, dict)]
    p0 = list(step_params.get("p0") or [])
    lo = list(step_params.get("bounds_lower") or [])
    hi = list(step_params.get("bounds_upper") or [])
    vary = list(step_params.get("vary") or [])
    links = {
        (str(lk.get("source_component_id")), str(lk.get("source_key"))): lk
        for lk in (step_params.get("param_links") or [])
        if isinstance(lk, dict)
    }
    fitted = {str(c.get("component_id")): c for c in item.get("components") or []}
    rows: list[dict[str, Any]] = []
    backgrounds: list[dict[str, Any]] = []
    cursor = 0
    for c in comps:
        cid = str(c.get("component_id") or "")
        ctype = str(c.get("component_type") or "").strip().lower()
        try:
            keys = _param_keys_for_component(c)
        except ValueError:
            keys = []
        fc = fitted.get(cid) or {}
        values = {k: _fin((fc.get("params") or {}).get(k)) for k in keys}
        errs = {k: _fin((fc.get("stderr") or {}).get(k)) for k in keys}
        params = {}
        for j, k in enumerate(keys):
            idx = cursor + j
            st = parameter_status(
                vary=bool(vary[idx]) if idx < len(vary) else True,
                lower=_fin(lo[idx]) if idx < len(lo) else None,
                upper=_fin(hi[idx]) if idx < len(hi) else None,
                link=links.get((cid, k)),
            )
            params[k] = {"value": values[k], "stderr": errs[k], "initial": _fin(p0[idx]) if idx < len(p0) else None, **st}
        cursor += len(keys)
        row = {
            "component_id": cid,
            "component_type": ctype,
            "lineshape": casaxps_lineshape(ctype, {k: v for k, v in values.items() if v is not None}),
            "params": params,
        }
        if ctype.endswith("_bg") or ctype == "polynomial_background":
            opts = {k: v for k, v in c.items() if k not in ("component_id", "component_type", "degree")}
            if opts:
                row["options"] = opts  # avg_width / offsets, SB source peak, ...
            backgrounds.append(row)
            continue
        row.update(
            {
                "position": values.get("pos"),
                "position_stderr": errs.get("pos"),
                "fwhm": values.get("fwhm"),
                "fwhm_stderr": errs.get("fwhm"),
                "height": values.get("amp"),
                "height_stderr": errs.get("amp"),
                "area": _fin(fc.get("area")),
                "area_stderr": _fin(fc.get("area_stderr")),
                "area_pct": _fin(fc.get("area_pct")),
                "area_pct_stderr": _fin(fc.get("area_pct_stderr")),
            }
        )
        rows.append(row)
    return rows, backgrounds


def _statistics(diag: dict[str, Any] | None, technique: str | None) -> dict[str, Any]:
    d = diag or {}
    keys = (
        "n_points",
        "n_vary",
        "chi2",
        "redchi",
        "chi2_reduced_weighted",
        "residual_std_normalised",
        "poisson_gain",
        "weighting",
        "weighting_note",
        "rmse",
        "r2",
        "aic",
        "bic",
        "success",
        "nfev",
        "n_at_bound",
    )
    out = {k: d.get(k) for k in keys}
    out["optimiser"] = optimiser_text(technique)
    return out


def build_fit_report(
    run_id: str,
    *,
    spectrum_ids: list[str] | None = None,
    fitting_step_nums: list[int] | None = None,
    include_figures: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """(report dict, {figure path: PNG bytes}) for the run's fitted spectra."""
    rec = get_run(run_id)
    if rec is None:
        raise ValueError("analysis run not found")
    if rec.status != "completed":
        raise ValueError("analysis run is not completed")
    pipeline, ds, refs, ns = _resolved_refs_for_run(rec, list(spectrum_ids) if spectrum_ids else None)
    if len(refs) > _max_spectra():
        raise ValueError(f"too many spectra for one report (max {_max_spectra()}); pass spectrum_ids")
    tech = getattr(pipeline, "technique_family", None)
    fit_steps = list_fitting_steps_for_pipeline(pipeline)
    if fitting_step_nums:
        wanted = {int(n) for n in fitting_step_nums}
        fit_steps = [s for s in fit_steps if s["step_num"] in wanted]
    if not fit_steps:
        raise ValueError("the run has no (selected) enabled fitting step")
    steps = list(pipeline.steps)

    paths = sorted({str(r.relative_path) for r in refs if r.relative_path})
    con = with_connection()
    try:
        labels_by_path = fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()
    cal_methods, shifts = _charge_correction(pipeline, refs, ns)

    from sersflow.core.pipeline.engine import _resolve_ref_path

    spectra: dict[str, dict[str, Any]] = {}
    for r in refs:
        sid = str(r.spectrum_id)
        ri = r.record_index if isinstance(r.record_index, int) else None
        lab = _labels_for_spectrum(labels_by_path.get(str(r.relative_path)) or {}, record_index=ri)
        try:
            path = _resolve_ref_path(r)
        except Exception:
            path = None
        spectra[sid] = {
            "spectrum_id": sid,
            "file": {
                "relative_path": str(r.original_relative_path or r.relative_path),
                "record_index": ri,
                "sha256": file_sha256(path) if path else None,
            },
            "labels": {k: lab.get(k) for k in _LABEL_KEYS if lab.get(k) is not None},
            "acquisition": _acquisition(ds, sid),
            "charge_shift_eV": shifts.get(sid, {}),
            "fits": [],
        }

    figures: dict[str, bytes] = {}
    total = len(refs) * len(fit_steps)
    done = 0
    for fs in fit_steps:
        step = steps[fs["step_index"]]
        step_params = dict(step.params or {})
        for k in range(0, len(refs), _PREVIEW_CHUNK):
            chunk = [str(r.spectrum_id) for r in refs[k : k + _PREVIEW_CHUNK]]
            prev = fitting_preview_for_run(
                run_id=run_id, spectrum_ids=chunk, fitting_step_num=fs["step_num"], return_curve=include_figures
            )
            for item in prev.get("items") or []:
                sid = str(item.get("spectrum_id"))
                done += 1
                if progress is not None:
                    progress(done, total)
                err = item.get("error")
                if err and "does not apply" in str(err):
                    continue  # spectrum of another region
                fit: dict[str, Any] = {
                    "fitting_step_num": fs["step_num"],
                    "xps_region": fs.get("xps_region"),
                    "column_prefix": fs.get("column_prefix"),
                    "error": err,
                }
                if not err:
                    rows, bgs = _component_rows(step_params, item)
                    fit.update(
                        {
                            "fit_window": [step_params.get("fit_min_x"), step_params.get("fit_max_x")],
                            "background": bgs[0] if bgs else None,
                            "backgrounds": bgs,
                            "components": rows,
                            "statistics": _statistics(item.get("diagnostics"), tech),
                            "recipe_ids": step_params.get("recipe_ids") or [],
                        }
                    )
                    if include_figures and item.get("y_hat"):
                        name = f"figures/{_safe(sid)}_step{fs['step_num']}.png"
                        try:
                            figures[name] = _figure_png(item, rows, sid, fs, ds)
                            fit["figure"] = name
                        except Exception as e:
                            logger.warning("report figure failed for %s: %s", sid, e)
                spectra[sid]["fits"].append(fit)
    spectra_list = [s for s in spectra.values() if s["fits"]]
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "software": software_info(),
        "run": {
            "run_id": rec.run_id,
            "label": rec.label,
            "dataset_id": rec.dataset_id,
            "dataset_name": getattr(getattr(ds, "metadata", None), "name", None),
            "pipeline_name": rec.pipeline_name,
            "pipeline_hash": rec.pipeline_hash,
            "subset_hash": rec.subset_hash,
            "created_at": rec.created_at,
            "finished_at": rec.finished_at,
            "technique_family": tech,
        },
        "processing_history": _processing_history(pipeline),
        "charge_correction": {
            "steps": cal_methods,
            "note": None if cal_methods else "no x-axis calibration step: energies as recorded (no charge correction)",
        },
        "quantification": {"status": "not_performed", "reason": QUANT_NOT_PERFORMED},
        "spectra": spectra_list,
    }
    report["checklist"] = checklist(report, include_figures=include_figures)
    return _json_safe(report), figures


def _safe(s: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)[:80]


def _figure_png(item: dict[str, Any], rows: list[dict[str, Any]], sid: str, fs: dict[str, Any], ds: Any) -> bytes:
    from sersflow.api.services.fit_curve_plot import render_fit_residual_png

    table = [["Peak", "Line shape", "Pos (eV)", "FWHM", "%Area"]]
    for r in rows:
        table.append(
            [
                r["component_id"],
                r["lineshape"].split(" ")[0],
                _fmt(r.get("position"), r.get("position_stderr")),
                _fmt(r.get("fwhm"), r.get("fwhm_stderr")),
                _fmt(r.get("area_pct"), r.get("area_pct_stderr")),
            ]
        )
    resid = item.get("residual") or []
    return render_fit_residual_png(
        x=item["x"],
        y=item["y"],
        y_hat=[float("nan") if v is None else v for v in item["y_hat"]],
        residual=[float("nan") if v is None else v for v in resid],
        components=item.get("components") or [],
        title=f"{sid}  ({fs.get('xps_region') or 'fitting step ' + str(fs['step_num'])})",
        diagnostics=None,
        table_rows=table,
        x_label="Binding energy (eV)" if str(getattr(ds.metadata, "technique_family", "") or "").lower() == "xps" else "X",
        invert_x=str(getattr(ds.metadata, "technique_family", "") or "").lower() == "xps",
    )


def _fmt(v: Any, se: Any) -> str:
    v, se = _fin(v), _fin(se)
    if v is None:
        return "-"
    if se is None or se <= 1e-9 * max(abs(v), 1.0):  # 0 or round-off (e.g. %area of a single peak)
        return f"{v:.2f}"
    d = max(0, min(6, 1 - int(math.floor(math.log10(se)))))
    return f"{v:.{d}f}±{se:.{d}f}"


def checklist(report: dict[str, Any], *, include_figures: bool = True) -> list[dict[str, Any]]:
    """Which report items are present (gap analysis R1 list)."""
    spectra = report.get("spectra") or []
    fits = [f for s in spectra for f in s.get("fits") or [] if not f.get("error")]
    comps = [c for f in fits for c in f.get("components") or []]
    sw = report.get("software") or {}
    present = {
        "raw_file": bool(spectra) and all(s["file"].get("relative_path") and s["file"].get("sha256") for s in spectra),
        "software": bool(sw.get("name") and sw.get("version")),
        "pipeline_hash": bool((report.get("run") or {}).get("pipeline_hash")),
        "acquisition": bool(spectra) and all((s.get("acquisition") or {}).get("available") for s in spectra),
        "max_channel": bool(spectra) and all((s.get("acquisition") or {}).get("max_channel_counts") is not None for s in spectra),
        "charge_correction": bool(report.get("charge_correction")),
        "processing_history": bool(report.get("processing_history")),
        "background": bool(fits) and all(f.get("background") is not None or f.get("fit_window") for f in fits),
        "lineshape": bool(comps) and all(c.get("lineshape") for c in comps),
        "values_with_errors": bool(comps) and all(c.get("area") is not None and "position_stderr" in c for c in comps),
        "constraints": bool(comps) and all(all("status" in p for p in c["params"].values()) for c in comps),
        "fit_statistics": bool(fits) and all((f.get("statistics") or {}).get("n_points") is not None for f in fits),
        "quantification": bool(report.get("quantification")),
        "figure": (not include_figures) or (bool(fits) and all(f.get("figure") for f in fits)),
    }
    notes = {
        "max_channel": "needs count-based VAMAS data (counts, or cps with dwell and scans)",
        "acquisition": "acquisition metadata is read from VAMAS blocks",
        "quantification": "reported as not performed (Q1/Q2 deferred)",
    }
    return [
        {"item": key, "label": label, "present": bool(present.get(key)), "note": notes.get(key)}
        for key, label in CHECKLIST
    ]
