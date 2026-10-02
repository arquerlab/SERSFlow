"""
Export fitted peak parameters as analysis feature columns (per spectrum).

Area formulas match fitting_models (amplitude = peak height):
- gaussian / lorentzian / gl / pseudo_voigt / apv / la / lf / a_gl: via peak_area.area_per_height
- voigt / asymmetric_voigt: amp / unit-profile height (exact for SciPy voigt_profile)
- ds / gds: no area export (non-integrable tail for alpha > 0)
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
from scipy.special import voigt_profile

from sersflow.core.metrics.key_dedupe import dedupe_parallel
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.preprocess.fit_diagnostics import GOF_METRIC_KEYS, diagnostics_as_feature_dict
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.fitting_specs import (
    AREA_EXPORT_COMPONENT_TYPES,
    component_param_specs,
)
from sersflow.core.preprocess.peak_area import (
    apv_area_per_height,
    area_per_height,
    gaussian_area_per_height,
    gl_area_per_height,
    lorentzian_area_per_height,
)
from sersflow.core.spectrum import XY

_LN2 = math.log(2.0)
_GAUSS_FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * _LN2))


def gaussian_peak_area(amp: float, fwhm: float) -> float:
    """Analytical area under the Gaussian peak used in fitting_models.gaussian."""
    if not math.isfinite(amp) or not math.isfinite(fwhm) or fwhm <= 0:
        return float("nan")
    return float(amp * gaussian_area_per_height(fwhm))


def lorentzian_peak_area(amp: float, fwhm: float) -> float:
    """Analytical area under fitting_models.lorentzian (peak-height amplitude)."""
    if not math.isfinite(amp) or not math.isfinite(fwhm) or fwhm <= 0:
        return float("nan")
    return float(amp * lorentzian_area_per_height(fwhm))


def pseudo_voigt_peak_area(amp: float, fwhm: float, eta: float) -> float:
    """Analytical area under fitting_models.pseudo_voigt."""
    if not math.isfinite(amp) or not math.isfinite(fwhm) or not math.isfinite(eta) or fwhm <= 0:
        return float("nan")
    return float(amp * gl_area_per_height(fwhm, eta * 100.0))


def gl_peak_area(amp: float, fwhm: float, m: float) -> float:
    """Analytical area under fitting_models.gl (CasaXPS GL(m), m = % Lorentzian)."""
    if not math.isfinite(amp) or not math.isfinite(fwhm) or not math.isfinite(m) or fwhm <= 0:
        return float("nan")
    return float(amp * gl_area_per_height(fwhm, m))


def voigt_peak_area(amp: float, fwhm_g: float, fwhm_l: float) -> float:
    """
    Analytical area under fitting_models.voigt (peak-height amplitude).

    Area = amp / voigt_profile(0, sigma, gamma) because the SciPy profile integrates to 1.
    """
    if not math.isfinite(amp) or not math.isfinite(fwhm_g) or not math.isfinite(fwhm_l):
        return float("nan")
    if fwhm_g <= 0 and fwhm_l <= 0:
        return float("nan")
    sigma = max(float(fwhm_g), 1e-12) * _GAUSS_FWHM_TO_SIGMA
    gamma = max(float(fwhm_l), 0.0) * 0.5
    y0 = float(voigt_profile(0.0, sigma, gamma))
    if not math.isfinite(y0) or y0 <= 0.0:
        return float("nan")
    return float(amp / y0)


def apv_peak_area(amp: float, fwhm_l: float, fwhm_r: float, eta_l: float, eta_r: float) -> float:
    """Half-side sum of pseudo-Voigt areas (continuous unit-height branches)."""
    if not math.isfinite(amp):
        return float("nan")
    return float(amp * apv_area_per_height(fwhm_l, fwhm_r, eta_l, eta_r))


def asymmetric_voigt_peak_area(
    amp: float, fwhm_g_l: float, fwhm_l_l: float, fwhm_g_r: float, fwhm_l_r: float
) -> float:
    """Half-side sum of Voigt areas (continuous unit-height branches)."""
    left = 0.5 * voigt_peak_area(amp, fwhm_g_l, fwhm_l_l)
    right = 0.5 * voigt_peak_area(amp, fwhm_g_r, fwhm_l_r)
    if not math.isfinite(left) or not math.isfinite(right):
        return float("nan")
    return float(left + right)


def _safe_id_fragment(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip())
    return t or "comp"


def _param_keys_for_component(row: dict[str, Any]) -> list[str]:
    ctype = str(row.get("component_type") or "").strip()
    degree_raw = row.get("degree")
    degree = int(degree_raw) if degree_raw is not None else None
    params = component_param_specs(ctype, degree=degree)
    return [p.key for p in params]


def _feature_keys_for_component(
    step_index: int,
    multi_step: bool,
    component_id: str,
    component_type: str,
    param_keys: list[str],
    xps_region: str | None = None,
) -> list[str]:
    cid = _safe_id_fragment(component_id)
    prefix = f"s{step_index}_" if multi_step else ""
    region = _safe_id_fragment(xps_region) if xps_region else ""
    mid = f"{region}_" if region else ""
    base = f"{prefix}fit_{mid}{cid}_"
    keys = [base + _safe_id_fragment(k) for k in param_keys]
    if component_type.strip().lower() in AREA_EXPORT_COMPONENT_TYPES:
        keys.append(base + "area")
    return keys


def _gof_feature_keys(
    step_index: int,
    multi_step: bool,
    xps_region: str | None = None,
) -> list[str]:
    prefix = f"s{step_index}_" if multi_step else ""
    region = _safe_id_fragment(xps_region) if xps_region else ""
    mid = f"{region}_" if region else ""
    base = f"{prefix}fit_{mid}gof_"
    return [base + m for m in GOF_METRIC_KEYS]


def _step_component_and_gof_key_count(
    step_index: int,
    multi_step: bool,
    comps: list[Any],
    xps_region: str | None,
) -> int:
    n = 0
    if isinstance(comps, list):
        for row in comps:
            if not isinstance(row, dict):
                continue
            ctype = str(row.get("component_type", "")).strip()
            cid = str(row.get("component_id") or "").strip() or "comp"
            try:
                param_keys = _param_keys_for_component(row)
            except ValueError:
                continue
            n += len(
                _feature_keys_for_component(
                    step_index, multi_step, cid, ctype, param_keys, xps_region=xps_region
                )
            )
    n += len(_gof_feature_keys(step_index, multi_step, xps_region=xps_region))
    return n


def _derived_peak_area(ctype: str, pk: dict[str, float]) -> float | None:
    ct = ctype.strip().lower()
    if ct not in AREA_EXPORT_COMPONENT_TYPES:
        return None
    amp = pk.get("amp")
    if amp is None or not math.isfinite(amp):
        return None
    # Exact Voigt area from amplitude / unit-profile height (more accurate than peak_area approx).
    if ct == "voigt":
        fwhm_g, fwhm_l = pk.get("fwhm_g"), pk.get("fwhm_l")
        if fwhm_g is None or fwhm_l is None:
            return None
        area = voigt_peak_area(amp, fwhm_g, fwhm_l)
        return area if math.isfinite(area) else None
    if ct == "asymmetric_voigt":
        fwhm_g_l, fwhm_l_l = pk.get("fwhm_g_l"), pk.get("fwhm_l_l")
        fwhm_g_r, fwhm_l_r = pk.get("fwhm_g_r"), pk.get("fwhm_l_r")
        if None in (fwhm_g_l, fwhm_l_l, fwhm_g_r, fwhm_l_r):
            return None
        area = asymmetric_voigt_peak_area(
            float(amp), float(fwhm_g_l), float(fwhm_l_l), float(fwhm_g_r), float(fwhm_l_r)
        )
        return area if math.isfinite(area) else None
    # Shared Area/amp factors (recipe links + export stay consistent), including LA / a_gl.
    try:
        factor = area_per_height(ct, pk)
    except Exception:
        return None
    area = float(amp) * float(factor)
    return area if math.isfinite(area) else None


def _raw_fitting_keys_and_nums(pipeline: Any) -> tuple[list[str], list[int]]:
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    fit_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "fitting"]
    multi = len(fit_indices) > 1
    raw: list[str] = []
    nums: list[int] = []
    for i in fit_indices:
        step = steps[i]
        params = step.params or {}
        region = params.get("xps_region")
        xps_region = str(region).strip() if region is not None and str(region).strip() else None
        comps = params.get("components")
        if not isinstance(comps, list):
            continue
        for row in comps:
            if not isinstance(row, dict):
                continue
            ctype = str(row.get("component_type", "")).strip()
            cid = str(row.get("component_id") or "").strip() or "comp"
            try:
                param_keys = _param_keys_for_component(row)
            except ValueError:
                continue
            for kk in _feature_keys_for_component(i, multi, cid, ctype, param_keys, xps_region=xps_region):
                raw.append(kk)
                nums.append(sns[i])
        for kk in _gof_feature_keys(i, multi, xps_region=xps_region):
            raw.append(kk)
            nums.append(sns[i])
    return raw, nums


def preview_fitting_feature_keys_for_pipeline(pipeline: Any) -> list[str]:
    """Column names for fitting exports (no spectrum data required)."""
    raw, nums = _raw_fitting_keys_and_nums(pipeline)
    return dedupe_parallel(raw, nums)


def fitting_feature_key_groups_for_pipeline(pipeline: Any) -> dict[int, list[str]]:
    """
    Map step_num -> final feature keys for enabled fitting steps.
    """
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw, nums = _raw_fitting_keys_and_nums(pipeline)
    final_keys = dedupe_parallel(raw, nums)
    fit_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "fitting"]
    out: dict[int, list[str]] = {}
    key_cursor = 0
    multi = len(fit_indices) > 1
    for i in fit_indices:
        step = steps[i]
        params = step.params or {}
        comps = params.get("components")
        region = params.get("xps_region")
        xps_region = str(region).strip() if region is not None and str(region).strip() else None
        step_key_count = _step_component_and_gof_key_count(i, multi, comps or [], xps_region)
        out[sns[i]] = final_keys[key_cursor : key_cursor + step_key_count]
        key_cursor += step_key_count
    return out


def collect_fitting_features_for_pipeline(
    xy: XY,
    pipeline: Any,
    *,
    per_step_input_xy: dict[int, XY] | None = None,
    spectrum_xps_region: str | None = None,
) -> tuple[list[str], dict[str, float | None]]:
    """
    Re-fit using stored step params and export optimized parameters per component.
    Peak components also export a derived area column.
    Each fitting step also exports goodness-of-fit scalars (fit_*_gof_*).

    On failure (non-convergence, too few points), returns None for that component's keys.

    per_step_input_xy:
        When provided, each fitting step uses the spectrum *input* to that step (after prior
        transforms). Otherwise all steps use ``xy`` (legacy single-final-XY behavior).

    spectrum_xps_region:
        When set, fitting steps whose ``xps_region`` does not match are skipped (null features).
    """
    from sersflow.core.pipeline.engine import fitting_region_applies

    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw, nums = _raw_fitting_keys_and_nums(pipeline)
    final_keys = dedupe_parallel(raw, nums)

    fit_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "fitting"]
    multi = len(fit_indices) > 1
    ordered_keys = list(final_keys)
    merged: dict[str, float | None] = {}

    key_cursor = 0
    for i in fit_indices:
        step = steps[i]
        params = step.params or {}
        comps = params.get("components")
        if not isinstance(comps, list):
            continue
        region = params.get("xps_region")
        xps_region = str(region).strip() if region is not None and str(region).strip() else None
        step_key_groups: list[list[str]] = []
        for row in comps:
            if not isinstance(row, dict):
                continue
            ctype = str(row.get("component_type", "")).strip()
            cid = str(row.get("component_id") or "").strip() or "comp"
            try:
                param_keys = _param_keys_for_component(row)
            except ValueError:
                continue
            step_key_groups.append(
                _feature_keys_for_component(i, multi, cid, ctype, param_keys, xps_region=xps_region)
            )
        gof_raw_keys = _gof_feature_keys(i, multi, xps_region=xps_region)

        step_raw: list[str] = []
        for group in step_key_groups:
            step_raw.extend(group)
        step_raw.extend(gof_raw_keys)
        n_step_keys = len(step_raw)
        step_final_keys = final_keys[key_cursor : key_cursor + n_step_keys]
        key_cursor += n_step_keys

        step_final_groups: list[list[str]] = []
        group_cursor = 0
        for group in step_key_groups:
            n_group = len(group)
            step_final_groups.append(step_final_keys[group_cursor : group_cursor + n_group])
            group_cursor += n_group
        gof_final_keys = step_final_keys[group_cursor : group_cursor + len(gof_raw_keys)]

        sn = sns[i]
        xy_use = per_step_input_xy.get(sn, xy) if per_step_input_xy is not None else xy

        nulls = {k: None for k in step_final_keys}
        if not fitting_region_applies(step_params=dict(params), spectrum_xps_region=spectrum_xps_region):
            merged.update(nulls)
            continue
        if xy_use.x.size == 0 or xy_use.y.size == 0:
            merged.update(nulls)
            continue
        try:
            fit_params = dict(params)
            tech = getattr(pipeline, "technique_family", None)
            if tech and "technique_family" not in fit_params:
                fit_params["technique_family"] = tech
            prob = fit_problem_from_step_params(xy_use, fit_params)
        except ValueError:
            merged.update(nulls)
            continue
        if prob is None:
            merged.update(nulls)
            continue
        try:
            res = fit_curve(prob)
        except (ValueError, RuntimeError):
            failed = dict(nulls)
            for fk, metric in zip(gof_final_keys, GOF_METRIC_KEYS):
                if metric == "success":
                    failed[fk] = 0.0
            merged.update(failed)
            continue

        out = dict(nulls)
        for m, final_group in zip(res.mapping, step_final_groups):
            ctype = str(m.get("component_type", "")).strip().lower()
            keys_list = list(m.get("param_keys") or [])
            start, end = m.get("index_range", [0, 0])
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            sl = res.p_opt[start:end]
            pk = {keys_list[j]: float(sl[j]) for j in range(min(len(keys_list), len(sl)))}
            param_final_keys = final_group[: len(keys_list)]
            for param_key, final_key in zip(keys_list, param_final_keys):
                value = pk.get(param_key)
                if value is not None and math.isfinite(value):
                    out[final_key] = value

            if ctype in AREA_EXPORT_COMPONENT_TYPES and len(final_group) > len(keys_list):
                area_key = final_group[len(keys_list)]
                out[area_key] = _derived_peak_area(ctype, pk)

        gof_vals = diagnostics_as_feature_dict(res.diagnostics)
        for fk, metric in zip(gof_final_keys, GOF_METRIC_KEYS):
            out[fk] = gof_vals.get(metric)

        merged.update(out)

    return ordered_keys, merged
