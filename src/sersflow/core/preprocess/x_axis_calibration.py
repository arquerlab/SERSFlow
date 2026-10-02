"""X-axis calibration: fixed offset or shift to a target from a prior fitting peak position."""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from sersflow.core.metrics.fitting_features import (
    _feature_keys_for_component,
    _param_keys_for_component,
)
from sersflow.core.preprocess.fitting import FitResult, fit_curve, fit_problem_from_step_params
from sersflow.core.spectrum import XY

# Feature-export prefixes (s{N}_) when multiple fittings exist; calibration keys are step-local.
_LEGACY_MULTI_FIT_POS_PREFIX = re.compile(r"^s\d+_(?=fit_)")


def canonicalize_calibration_pos_key(pos_key: str) -> str:
    """Strip optional ``s{N}_`` feature-export prefix; calibration keys are step-local."""
    return _LEGACY_MULTI_FIT_POS_PREFIX.sub("", str(pos_key or "").strip())


def fitting_pos_keys_for_step(
    step_params: dict[str, Any],
    *,
    step_index: int = 0,
    multi_fitting: bool = False,
) -> list[str]:
    """Return ``*_pos`` feature keys for a fitting step.

    For ``x_axis_calibration``, callers should use ``multi_fitting=False`` (step-local
    names). ``step_index`` / ``multi_fitting`` remain for feature-export naming helpers.
    """
    region = step_params.get("xps_region")
    xps_region = str(region).strip() if region is not None and str(region).strip() else None
    comps = step_params.get("components")
    if not isinstance(comps, list):
        return []
    out: list[str] = []
    for row in comps:
        if not isinstance(row, dict):
            continue
        ctype = str(row.get("component_type", "")).strip()
        cid = str(row.get("component_id") or "").strip() or "comp"
        try:
            param_keys = _param_keys_for_component(row)
        except ValueError:
            continue
        for key in _feature_keys_for_component(
            step_index, multi_fitting, cid, ctype, param_keys, xps_region=xps_region
        ):
            if key.endswith("_pos"):
                out.append(key)
    return out


def calibration_pos_keys_for_step(step_params: dict[str, Any]) -> list[str]:
    """Position keys offered/accepted by ``x_axis_calibration`` (never ``s{N}_``-prefixed)."""
    return fitting_pos_keys_for_step(step_params, step_index=0, multi_fitting=False)


def _pos_values_from_fit_result(
    res: FitResult,
    step_params: dict[str, Any],
    *,
    step_index: int,
    multi_fitting: bool,
) -> dict[str, float]:
    region = step_params.get("xps_region")
    xps_region = str(region).strip() if region is not None and str(region).strip() else None
    comps = step_params.get("components")
    if not isinstance(comps, list):
        return {}
    values: dict[str, float] = {}
    for m, row in zip(res.mapping, comps):
        if not isinstance(row, dict):
            continue
        ctype = str(row.get("component_type", "")).strip()
        cid = str(row.get("component_id") or "").strip() or "comp"
        try:
            param_keys = _param_keys_for_component(row)
        except ValueError:
            continue
        keys = _feature_keys_for_component(
            step_index, multi_fitting, cid, ctype, param_keys, xps_region=xps_region
        )
        keys_list = list(m.get("param_keys") or [])
        start, end = m.get("index_range", [0, 0])
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        sl = res.p_opt[start:end]
        pk = {keys_list[j]: float(sl[j]) for j in range(min(len(keys_list), len(sl)))}
        for param_key, final_key in zip(keys_list, keys[: len(keys_list)]):
            if not final_key.endswith("_pos"):
                continue
            value = pk.get(param_key)
            if value is not None and math.isfinite(value):
                values[final_key] = float(value)
    return values


def measured_pos_from_fitting_xy(
    xy: XY,
    fit_params: dict[str, Any],
    *,
    step_index: int = 0,
    multi_fitting: bool = False,
    pos_key: str,
    technique_family: str | None = None,
) -> float:
    """
    Re-fit ``xy`` with ``fit_params`` and return the value for ``pos_key``.

    Calibration always resolves step-local keys (``fit_..._pos``). Legacy feature-export
    names with an ``s{N}_`` prefix are accepted and canonicalized.

    ``step_index`` / ``multi_fitting`` are ignored for key naming (kept for call-site compat).

    Raises ValueError when the fit fails or ``pos_key`` is missing / non-finite.
    """
    del step_index, multi_fitting  # naming is always step-local for calibration
    key = canonicalize_calibration_pos_key(pos_key)
    if not key:
        raise ValueError("pos_key must be provided for x_axis_calibration method='reference_peak'")
    expected = calibration_pos_keys_for_step(fit_params)
    if key not in expected:
        raise ValueError(
            f"pos_key {key!r} is not a position feature of the selected fitting step "
            f"(expected one of {expected})"
        )
    if xy.x.size == 0 or xy.y.size == 0:
        raise ValueError("x_axis_calibration reference_peak: fitting input spectrum is empty")

    params = dict(fit_params)
    if technique_family and "technique_family" not in params:
        params["technique_family"] = technique_family
    try:
        prob = fit_problem_from_step_params(xy, params)
    except ValueError as e:
        raise ValueError(f"x_axis_calibration reference_peak: cannot build fit problem: {e}") from e
    if prob is None:
        raise ValueError("x_axis_calibration reference_peak: fitting step has no components")
    try:
        res = fit_curve(prob)
    except (ValueError, RuntimeError) as e:
        raise ValueError(f"x_axis_calibration reference_peak: fit failed: {e}") from e

    values = _pos_values_from_fit_result(
        res, fit_params, step_index=0, multi_fitting=False
    )
    measured = values.get(key)
    if measured is None or not math.isfinite(measured):
        raise ValueError(f"x_axis_calibration reference_peak: fitted {key!r} is missing or non-finite")
    return float(measured)


def calibration_delta(params: dict[str, Any]) -> float:
    """Return the additive x shift from calibration params (including runtime ``_measured_pos``)."""
    method = str(params.get("method", "fixed_offset")).strip().lower()
    if method == "fixed_offset":
        if "offset" not in params:
            raise ValueError("offset must be provided for x_axis_calibration method='fixed_offset'")
        offset = float(params["offset"])
        if not math.isfinite(offset):
            raise ValueError("offset must be finite for x_axis_calibration method='fixed_offset'")
        return offset
    if method == "reference_peak":
        if "_measured_pos" not in params:
            raise ValueError(
                "x_axis_calibration method='reference_peak' requires pipeline fitting_step_id context"
            )
        measured = float(params["_measured_pos"])
        if not math.isfinite(measured):
            raise ValueError("_measured_pos must be finite for x_axis_calibration method='reference_peak'")
        if "target_x" not in params:
            raise ValueError("target_x must be provided for x_axis_calibration method='reference_peak'")
        target = float(params["target_x"])
        if not math.isfinite(target):
            raise ValueError("target_x must be finite for x_axis_calibration method='reference_peak'")
        return target - measured
    raise ValueError(
        f"Unknown x_axis_calibration method {method!r} (expected 'fixed_offset' or 'reference_peak')"
    )


def apply_x_axis_calibration(xy: XY, params: dict[str, Any]) -> XY:
    x = np.asarray(xy.x, dtype=float).ravel()
    y = np.asarray(xy.y, dtype=float).ravel()
    if x.size == 0 or y.size == 0:
        return xy
    if x.size != y.size:
        raise ValueError("x_axis_calibration: x and y must have the same length")
    delta = calibration_delta(params)
    if delta == 0.0:
        return XY(x=xy.x, y=xy.y)
    return XY(x=x + delta, y=y.astype(float, copy=False))
