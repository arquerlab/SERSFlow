"""X-axis calibration: fixed offset or shift to a target from a prior fitting peak position."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from sersflow.core.metrics.fitting_features import (
    _feature_keys_for_component,
    _param_keys_for_component,
)
from sersflow.core.preprocess.fitting import FitResult, fit_curve, fit_problem_from_step_params
from sersflow.core.spectrum import XY


def fitting_pos_keys_for_step(
    step_params: dict[str, Any],
    *,
    step_index: int,
    multi_fitting: bool,
) -> list[str]:
    """Return ``*_pos`` feature keys a fitting step would export (same naming as feature export)."""
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
    step_index: int,
    multi_fitting: bool,
    pos_key: str,
    technique_family: str | None = None,
) -> float:
    """
    Re-fit ``xy`` with ``fit_params`` and return the value for ``pos_key``.

    Raises ValueError when the fit fails or ``pos_key`` is missing / non-finite.
    """
    key = str(pos_key or "").strip()
    if not key:
        raise ValueError("pos_key must be provided for x_axis_calibration method='reference_peak'")
    expected = fitting_pos_keys_for_step(fit_params, step_index=step_index, multi_fitting=multi_fitting)
    if key not in expected:
        raise ValueError(
            f"pos_key {key!r} is not a position feature of the selected fitting step "
            f"(expected one of {expected})"
        )
    if xy.x.size == 0 or xy.y.size == 0:
        # #region agent log
        try:
            import json as _dj
            import time as _dt
            from pathlib import Path as _dp

            _logp = _dp(__file__).resolve().parents[4] / "debug-7bfc6e.log"
            with _logp.open("a", encoding="utf-8") as _lf:
                _lf.write(
                    _dj.dumps(
                        {
                            "sessionId": "7bfc6e",
                            "hypothesisId": "A,D",
                            "location": "x_axis_calibration.py:measured_pos_from_fitting_xy",
                            "message": "empty fitting input — about to raise",
                            "data": {
                                "pos_key": str(pos_key or ""),
                                "step_index": int(step_index),
                                "x_size": int(xy.x.size),
                                "y_size": int(xy.y.size),
                            },
                            "timestamp": int(_dt.time() * 1000),
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion
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
        res, fit_params, step_index=step_index, multi_fitting=multi_fitting
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
