from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy.interpolate import interp1d

from sersflow.core.metrics.feature_operations import parse_feature_operations
from sersflow.core.metrics.integration_features import parse_integration_windows
from sersflow.core.pipeline.hashing import canonical_json
from sersflow.core.preprocess.baseline import baseline_kwargs, correct_baseline
from sersflow.core.preprocess.cosmic_ray import remove_cosmic_rays
from sersflow.core.metrics.intensity_probes import parse_probes
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.noise import apply_savitzky_golay
from sersflow.core.spectrum import XY

logger = logging.getLogger(__name__)


Transform = Callable[[XY, dict[str, Any]], XY]


@dataclass(frozen=True)
class StepImpl:
    name: str
    impl_version: str
    transform: Transform


def normalization_point_x(params: dict[str, Any], *, method: str) -> float:
    if "point_x" in params:
        point_x = float(params["point_x"])
    elif "baseline_point" in params:
        point_x = float(params["baseline_point"])
    else:
        raise ValueError(f"point_x must be provided for normalization method={method!r}")
    if not np.isfinite(point_x):
        raise ValueError(f"point_x must be finite for normalization method={method!r}")
    return point_x


def normalize_by_reference_point(
    xy: XY,
    *,
    reference_x: np.ndarray,
    reference_y: np.ndarray,
    point_x: float,
    allow_empty_reference: bool = False,
    reference_label: str = "reference",
) -> XY:
    y = xy.y.astype(float, copy=False)
    rx = np.asarray(reference_x, dtype=float).ravel()
    ry = np.asarray(reference_y, dtype=float).ravel()
    if rx.size != ry.size:
        raise ValueError(f"{reference_label} x and y must have the same length")
    if rx.size == 0:
        if not allow_empty_reference:
            raise ValueError(f"{reference_label} is empty")
        denom = 1.0
    else:
        idx = int(np.argmin(np.abs(rx - point_x)))
        denom = float(ry[idx])
    if denom == 0.0:
        denom = 1.0
    return XY(x=xy.x, y=y / denom)


def _crop(xy: XY, params: dict[str, Any]) -> XY:
    min_x = float(params["min_x"])
    max_x = float(params["max_x"])
    x = xy.x
    y = xy.y
    mask = (x >= min_x) & (x <= max_x)
    return XY(x=x[mask], y=y[mask])


def _normalize(xy: XY, params: dict[str, Any]) -> XY:
    method = str(params.get("method", "max"))
    y = xy.y.astype(float, copy=False)
    if method == "max":
        denom = float(np.max(y)) if y.size else 1.0
    elif method == "min":
        denom = float(np.min(y)) if y.size else 1.0
    elif method == "mean":
        denom = float(np.mean(y)) if y.size else 1.0
    elif method == "median":
        denom = float(np.median(y)) if y.size else 1.0
    elif method in ("vector", "l2"):
        # Vector (L2) normalization: y / ||y||_2
        denom = float(np.linalg.norm(y)) if y.size else 1.0
    elif method in ("spectrum_point", "baseline"):
        point_x = normalization_point_x(params, method=method)
        return normalize_by_reference_point(
            xy,
            reference_x=xy.x,
            reference_y=y,
            point_x=point_x,
            allow_empty_reference=True,
            reference_label="spectrum",
        )
    elif method == "baseline_point":
        raise ValueError("normalization method='baseline_point' requires pipeline baseline_step_id context")
    else:
        raise ValueError(f"Unknown normalization method: {method}")
    if denom == 0.0:
        denom = 1.0
    return XY(x=xy.x, y=y / denom)


def _noise_savgol(xy: XY, params: dict[str, Any]) -> XY:
    window_length = int(params.get("window_length", 11))
    polyorder = int(params.get("polyorder", 3))
    deriv = int(params.get("deriv", 0))
    delta = float(params.get("delta", 1.0))
    mode = str(params.get("mode", "interp"))
    n = int(xy.y.size)
    if n == 0 or window_length > n or polyorder >= window_length:
        return xy
    y = apply_savitzky_golay(
        xy.y.astype(float, copy=False),
        window_length=window_length,
        polyorder=polyorder,
        deriv=deriv,
        delta=delta,
        mode=mode,
    )
    return XY(x=xy.x, y=np.asarray(y, dtype=float))


def _cosmic_ray_removal(xy: XY, params: dict[str, Any]) -> XY:
    if xy.y.size == 0:
        return xy
    method = str(params.get("method", "zscore"))
    threshold = float(params.get("threshold", 5.0))
    window = int(params.get("window", 5))
    interpolation = str(params.get("interpolation", "median"))
    max_width = int(params.get("max_width", 10))
    min_intensity_ratio = float(params.get("min_intensity_ratio", 2.0))
    n_iterations = int(params.get("n_iterations", 3))
    corrected, _, _ = remove_cosmic_rays(
        xy.y.astype(float, copy=False),
        method=method,
        threshold=threshold,
        window=window,
        interpolation=interpolation,
        max_width=max_width,
        min_intensity_ratio=min_intensity_ratio,
        n_iterations=n_iterations,
    )
    return XY(x=xy.x, y=np.asarray(corrected, dtype=float))


def _baseline(xy: XY, params: dict[str, Any]) -> XY:
    if xy.y.size == 0:
        return xy

    method = str(params.get("method", "derpsalsa"))
    kwargs = baseline_kwargs(method, params)
    corrected, _ = correct_baseline(xy.y.astype(float, copy=False), method=method, **kwargs)
    return XY(x=xy.x, y=np.asarray(corrected, dtype=float))


def _fitting(xy: XY, params: dict[str, Any]) -> XY:
    """
    Nonlinear least-squares fit (sum of gaussian / polynomial_background components).

    Params (flattened for caching + API):
    - output_mode: "fit" (replace y with model sum) or "residual" (y - model sum)
    - components: list of {component_id, component_type, degree?}
    - p0: list[float]
    - bounds_lower, bounds_upper: list[float | null] (null = unbounded)
    - initial_guess_mode: "default" | "auto" (Gaussian amp from y at pos in auto mode)
    """
    output_mode = str(params.get("output_mode", "fit"))
    prob = fit_problem_from_step_params(xy, params)
    if prob is None:
        return xy
    try:
        res = fit_curve(prob)
    except (ValueError, RuntimeError) as e:
        # Mixed batches: crop may leave too few points or non-overlapping wavenumbers for some spectra.
        logger.info("Fitting step skipped (pass-through unchanged spectrum): %s", e)
        return xy
    y_in = xy.y.astype(float, copy=False)
    if output_mode == "residual":
        return XY(x=xy.x, y=y_in - res.y_hat)
    if output_mode == "fit":
        return XY(x=xy.x, y=res.y_hat)
    raise ValueError(f"Unknown fitting output_mode: {output_mode}")


def _spectral_intensities(xy: XY, params: dict[str, Any]) -> XY:
    """
    No-op on XY; params describe probes evaluated after preprocessing for batch/export.

    Validates params.probes at execution time.
    """
    parse_probes(params)
    return XY(x=xy.x, y=xy.y)


def _spectral_integrations(xy: XY, params: dict[str, Any]) -> XY:
    """
    No-op on XY; params describe integration windows evaluated for batch/export.
    """
    parse_integration_windows(params)
    return XY(x=xy.x, y=xy.y)


def _feature_operations(xy: XY, params: dict[str, Any]) -> XY:
    """
    No-op on XY; params describe formulas evaluated against previously extracted features.
    """
    parse_feature_operations(params)
    return XY(x=xy.x, y=xy.y)


def _dedupe_x_average_y(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sort by x ascending; duplicate x values get mean y (stable for np.interp)."""
    order = np.argsort(x)
    x_s = x[order]
    y_s = y[order]
    ux, inv = np.unique(x_s, return_inverse=True)
    if ux.size == x_s.size:
        return ux, y_s
    sums = np.bincount(inv, weights=y_s)
    counts = np.bincount(inv)
    y_agg = sums / np.maximum(counts, 1)
    return ux, y_agg.astype(float)


def _spectrum_derivative(xy: XY, params: dict[str, Any]) -> XY:
    method = str(params.get("method", "gradient"))
    if method != "gradient":
        raise ValueError(f"Unknown spectrum_derivative method: {method}")
    x = np.asarray(xy.x, dtype=np.float64).ravel()
    y = np.asarray(xy.y, dtype=np.float64).ravel()
    if x.size == 0 or y.size == 0:
        return xy
    if x.size != y.size:
        raise ValueError("spectrum_derivative: x and y must have the same length")
    xs, ys = _dedupe_x_average_y(x, y)
    if xs.size < 2:
        return XY(x=xs, y=ys)
    order = int(params.get("order", 1))
    if order < 1:
        raise ValueError("spectrum_derivative: order must be >= 1")
    out = np.asarray(ys, dtype=np.float64)
    edge_order = 2 if xs.size >= 3 else 1
    for _ in range(order):
        out = np.gradient(out, xs, edge_order=edge_order)
    return XY(x=xs, y=np.asarray(out, dtype=float))


def _reference_transform(xy: XY, params: dict[str, Any]) -> XY:
    x = np.asarray(xy.x, dtype=np.float64).ravel()
    y = np.asarray(xy.y, dtype=np.float64).ravel()
    if x.size == 0 or y.size == 0:
        return xy
    if x.size != y.size:
        raise ValueError("reference_transform: x and y must have the same length")

    rx_raw = params.get("_reference_x")
    ry_raw = params.get("_reference_y")
    if rx_raw is None or ry_raw is None:
        raise ValueError("reference_transform requires a selected reference spectrum")
    rx = np.asarray(rx_raw, dtype=np.float64).ravel()
    ry = np.asarray(ry_raw, dtype=np.float64).ravel()
    if rx.size == 0 or ry.size == 0:
        raise ValueError("reference_transform reference spectrum is empty")
    if rx.size != ry.size:
        raise ValueError("reference_transform reference x and y must have the same length")

    rx_s, ry_s = _dedupe_x_average_y(rx, ry)
    if rx_s.size < 2:
        raise ValueError("reference_transform reference spectrum needs at least two x points")
    ref_y = np.interp(x, rx_s, ry_s, left=float(ry_s[0]), right=float(ry_s[-1]))
    operation = str(params.get("operation", "subtract")).strip().lower()
    if operation == "subtract":
        return XY(x=xy.x, y=np.asarray(y - ref_y, dtype=float))
    if operation == "divide":
        out = np.full_like(y, np.nan, dtype=np.float64)
        np.divide(y, ref_y, out=out, where=np.abs(ref_y) > 1e-12)
        return XY(x=xy.x, y=out.astype(float))
    raise ValueError("reference_transform operation must be subtract or divide")


def _uniform_grid_step(x_min: float, x_max: float, step: float) -> np.ndarray:
    """Ascending uniform grid: x_min, x_min+step, ... last <= x_max (within float tolerance)."""
    span = x_max - x_min
    if span <= 0:
        return np.array([x_min, x_max], dtype=np.float64)
    n_seg = int(np.floor(span / step + 1e-12))
    n_pts = n_seg + 1
    x_out = x_min + step * np.arange(n_pts, dtype=np.float64)
    tol = 1e-9 * max(abs(x_max), abs(x_min), 1.0)
    x_out = x_out[x_out <= x_max + tol]
    if x_out.size == 0:
        return np.linspace(x_min, x_max, 2, dtype=np.float64)
    return x_out


def _align_resample(xy: XY, params: dict[str, Any]) -> XY:
    """
    Interpolate onto a uniform Raman-shift grid.

    Empty spectrum: pass-through (unchanged). Single unique x after deduplication: pass-through.

    Params:
      min_x, max_x: optional floats defining a global target range. If provided, the output grid uses
        exactly [min_x, max_x] regardless of the spectrum's native coverage. Values outside the native
        x range are extrapolated by edge-clamping.
      grid_mode: "step" | "points"
      step: positive float (grid_mode step)
      n_points: int >= 2 (grid_mode points)
      interp: "linear" | "cubic"
    """
    x = np.asarray(xy.x, dtype=np.float64).ravel()
    y = np.asarray(xy.y, dtype=np.float64).ravel()
    if x.size == 0 or y.size == 0:
        return xy
    if x.size != y.size:
        raise ValueError("align_resample: x and y must have the same length")

    grid_mode = str(params.get("grid_mode", "step"))
    interp = str(params.get("interp", "linear"))
    if grid_mode not in ("step", "points"):
        raise ValueError(f"align_resample: unknown grid_mode {grid_mode!r} (expected 'step' or 'points')")
    if interp not in ("linear", "cubic"):
        raise ValueError(f"align_resample: unknown interp {interp!r} (expected 'linear' or 'cubic')")

    x_s, y_s = _dedupe_x_average_y(x, y)
    if x_s.size < 2:
        # No meaningful domain to resample; keep single point as-is for downstream clarity.
        return XY(x=x_s, y=y_s)

    x_min_native = float(x_s[0])
    x_max_native = float(x_s[-1])
    x_min = float(params.get("min_x", x_min_native))
    x_max = float(params.get("max_x", x_max_native))
    if not (np.isfinite(x_min) and np.isfinite(x_max)):
        raise ValueError("align_resample: min_x/max_x must be finite when provided")
    if x_max <= x_min:
        raise ValueError("align_resample: max_x must be > min_x")

    if grid_mode == "step":
        step = float(params.get("step", 1.0))
        if step <= 0.0:
            raise ValueError("align_resample: step must be positive when grid_mode='step'")
        x_out = _uniform_grid_step(x_min, x_max, step)
    else:
        n_points = int(params.get("n_points", 512))
        if n_points < 2:
            raise ValueError("align_resample: n_points must be at least 2 when grid_mode='points'")
        x_out = np.linspace(x_min, x_max, n_points, dtype=np.float64)

    if interp == "linear":
        # np.interp edge-clamps outside [x_s[0], x_s[-1]].
        y_out = np.interp(x_out, x_s, y_s)
    else:
        # SciPy cubic needs k+1 points; fall back to linear if too few.
        if x_s.size < 4:
            y_out = np.interp(x_out, x_s, y_s)
        else:
            f = interp1d(
                x_s,
                y_s,
                kind="cubic",
                bounds_error=False,
                fill_value=(float(y_s[0]), float(y_s[-1])),  # edge clamp
            )
            y_out = np.asarray(f(x_out), dtype=np.float64)

    if not np.all(np.isfinite(y_out)):
        y_out = np.nan_to_num(y_out, nan=float(y_s[len(y_s) // 2]), posinf=float(y_s[-1]), neginf=float(y_s[0]))

    return XY(x=x_out, y=y_out)


def _baseline_curve(xy: XY, params: dict[str, Any]) -> XY:
    if xy.y.size == 0:
        return xy

    method = str(params.get("method", "derpsalsa"))
    kwargs = baseline_kwargs(method, params)
    _, info = correct_baseline(xy.y.astype(float, copy=False), method=method, **kwargs)
    baseline = np.asarray(info.get("baseline", []), dtype=float)
    return XY(x=xy.x, y=baseline)


DEFAULT_STEPS: dict[str, StepImpl] = {
    "crop": StepImpl(name="crop", impl_version="1", transform=_crop),
    "align_resample": StepImpl(name="align_resample", impl_version="1", transform=_align_resample),
    "normalize": StepImpl(name="normalize", impl_version="2", transform=_normalize),
    "noise_savgol": StepImpl(name="noise_savgol", impl_version="1", transform=_noise_savgol),
    "cosmic_ray_removal": StepImpl(name="cosmic_ray_removal", impl_version="1", transform=_cosmic_ray_removal),
    "baseline": StepImpl(name="baseline", impl_version="1", transform=_baseline),
    "baseline_curve": StepImpl(name="baseline_curve", impl_version="1", transform=_baseline_curve),
    "fitting": StepImpl(name="fitting", impl_version="3", transform=_fitting),
    "spectral_intensities": StepImpl(name="spectral_intensities", impl_version="1", transform=_spectral_intensities),
    "spectral_integrations": StepImpl(name="spectral_integrations", impl_version="1", transform=_spectral_integrations),
    "feature_operations": StepImpl(name="feature_operations", impl_version="1", transform=_feature_operations),
    "spectrum_derivative": StepImpl(name="spectrum_derivative", impl_version="1", transform=_spectrum_derivative),
    "reference_transform": StepImpl(name="reference_transform", impl_version="1", transform=_reference_transform),
}


def params_fingerprint(step_name: str, params: dict[str, Any], impl_version: str) -> str:
    return canonical_json({"step": step_name, "params": params, "impl_version": impl_version})

