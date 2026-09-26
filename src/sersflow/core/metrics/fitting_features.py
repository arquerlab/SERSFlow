"""
Export fitted peak parameters as analysis feature columns (per spectrum).

Area formulas match fitting_models (amplitude = peak height):
- gaussian: amp * fwhm * sqrt(pi / (4 ln 2))
- lorentzian: amp * pi * fwhm / 2
- pseudo_voigt: eta * lorentzian_area + (1 - eta) * gaussian_area
- voigt: amp / voigt_profile(0, sigma, gamma)  (unit-area profile normalized to peak height)
"""

from __future__ import annotations

import math
import re
from typing import Any

from scipy.special import voigt_profile

from sersflow.core.metrics.key_dedupe import dedupe_parallel
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.fitting_specs import PEAK_COMPONENT_TYPES, build_component_function
from sersflow.core.spectrum import XY

_LN2 = math.log(2.0)
_GAUSS_FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * _LN2))


def gaussian_peak_area(amp: float, fwhm: float) -> float:
    """Analytical area under the Gaussian peak used in fitting_models.gaussian (same x units as pos)."""
    if not math.isfinite(amp) or not math.isfinite(fwhm) or fwhm <= 0:
        return float("nan")
    return float(amp * fwhm * math.sqrt(math.pi / (4.0 * _LN2)))


def lorentzian_peak_area(amp: float, fwhm: float) -> float:
    """Analytical area under fitting_models.lorentzian (peak-height amplitude)."""
    if not math.isfinite(amp) or not math.isfinite(fwhm) or fwhm <= 0:
        return float("nan")
    return float(amp * math.pi * fwhm / 2.0)


def pseudo_voigt_peak_area(amp: float, fwhm: float, eta: float) -> float:
    """Analytical area under fitting_models.pseudo_voigt."""
    if not math.isfinite(eta):
        return float("nan")
    g = gaussian_peak_area(amp, fwhm)
    lor = lorentzian_peak_area(amp, fwhm)
    if not math.isfinite(g) or not math.isfinite(lor):
        return float("nan")
    return float(eta * lor + (1.0 - eta) * g)


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


def _safe_id_fragment(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip())
    return t or "comp"


def _param_keys_for_component(row: dict[str, Any]) -> list[str]:
    ctype = str(row.get("component_type") or "").strip()
    degree_raw = row.get("degree")
    degree = int(degree_raw) if degree_raw is not None else None
    _func, params = build_component_function(ctype, degree=degree)
    return [p.key for p in params]


def _feature_keys_for_component(
    step_index: int,
    multi_step: bool,
    component_id: str,
    component_type: str,
    param_keys: list[str],
) -> list[str]:
    cid = _safe_id_fragment(component_id)
    prefix = f"s{step_index}_" if multi_step else ""
    base = f"{prefix}fit_{cid}_"
    keys = [base + _safe_id_fragment(k) for k in param_keys]
    if component_type.strip().lower() in PEAK_COMPONENT_TYPES:
        keys.append(base + "area")
    return keys


def _derived_peak_area(ctype: str, pk: dict[str, float]) -> float | None:
    ct = ctype.strip().lower()
    if ct == "gaussian":
        amp, fwhm = pk.get("amp"), pk.get("fwhm")
        if amp is None or fwhm is None:
            return None
        area = gaussian_peak_area(amp, fwhm)
    elif ct == "lorentzian":
        amp, fwhm = pk.get("amp"), pk.get("fwhm")
        if amp is None or fwhm is None:
            return None
        area = lorentzian_peak_area(amp, fwhm)
    elif ct == "pseudo_voigt":
        amp, fwhm, eta = pk.get("amp"), pk.get("fwhm"), pk.get("eta")
        if amp is None or fwhm is None or eta is None:
            return None
        area = pseudo_voigt_peak_area(amp, fwhm, eta)
    elif ct == "voigt":
        amp, fwhm_g, fwhm_l = pk.get("amp"), pk.get("fwhm_g"), pk.get("fwhm_l")
        if amp is None or fwhm_g is None or fwhm_l is None:
            return None
        area = voigt_peak_area(amp, fwhm_g, fwhm_l)
    else:
        return None
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
            for kk in _feature_keys_for_component(i, multi, cid, ctype, param_keys):
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
    for i in fit_indices:
        step = steps[i]
        params = step.params or {}
        comps = params.get("components")
        step_key_count = 0
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
                step_key_count += len(_feature_keys_for_component(i, len(fit_indices) > 1, cid, ctype, param_keys))
        out[sns[i]] = final_keys[key_cursor : key_cursor + step_key_count]
        key_cursor += step_key_count
    return out


def collect_fitting_features_for_pipeline(
    xy: XY,
    pipeline: Any,
    *,
    per_step_input_xy: dict[int, XY] | None = None,
) -> tuple[list[str], dict[str, float | None]]:
    """
    Re-fit using stored step params and export optimized parameters per component.
    Peak components also export a derived area column.

    On failure (non-convergence, too few points), returns None for that component's keys.

    per_step_input_xy:
        When provided, each fitting step uses the spectrum *input* to that step (after prior
        transforms). Otherwise all steps use ``xy`` (legacy single-final-XY behavior).
    """
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
            step_key_groups.append(_feature_keys_for_component(i, multi, cid, ctype, param_keys))

        step_raw: list[str] = []
        for group in step_key_groups:
            step_raw.extend(group)
        n_step_keys = len(step_raw)
        step_final_keys = final_keys[key_cursor : key_cursor + n_step_keys]
        key_cursor += n_step_keys

        step_final_groups: list[list[str]] = []
        group_cursor = 0
        for group in step_key_groups:
            n_group = len(group)
            step_final_groups.append(step_final_keys[group_cursor : group_cursor + n_group])
            group_cursor += n_group

        sn = sns[i]
        xy_use = per_step_input_xy.get(sn, xy) if per_step_input_xy is not None else xy

        nulls = {k: None for k in step_final_keys}
        if xy_use.x.size == 0 or xy_use.y.size == 0:
            merged.update(nulls)
            continue
        try:
            prob = fit_problem_from_step_params(xy_use, params)
        except ValueError:
            merged.update(nulls)
            continue
        if prob is None:
            merged.update(nulls)
            continue
        try:
            res = fit_curve(prob)
        except (ValueError, RuntimeError):
            merged.update(nulls)
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

            if ctype in PEAK_COMPONENT_TYPES and len(final_group) > len(keys_list):
                area_key = final_group[len(keys_list)]
                out[area_key] = _derived_peak_area(ctype, pk)

        merged.update(out)

    return ordered_keys, merged
