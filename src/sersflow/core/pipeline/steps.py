from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from sersflow.core.pipeline.hashing import canonical_json
from sersflow.core.preprocess.baseline import correct_baseline
from sersflow.core.preprocess.cosmic_ray import remove_cosmic_rays
from sersflow.core.preprocess.noise import apply_savitzky_golay
from sersflow.core.spectrum import XY


Transform = Callable[[XY, dict[str, Any]], XY]


@dataclass(frozen=True)
class StepImpl:
    name: str
    impl_version: str
    transform: Transform


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
    elif method == "baseline":
        if "baseline_point" not in params:
            raise ValueError("baseline_point must be provided for normalization method='baseline'")
        if not xy.x.size or not y.size:
            denom = 1.0
        else:
            bp = float(params["baseline_point"])
            idx = int(np.argmin(np.abs(xy.x.astype(float, copy=False) - bp)))
            denom = float(y[idx])
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
    method = str(params.get("method", "derpsalsa"))

    # Only forward supported kwargs (avoid leaking unexpected keys).
    kwargs: dict[str, Any] = {}
    if "lam" in params:
        kwargs["lam"] = float(params["lam"])
    if "p" in params:
        kwargs["p"] = float(params["p"])
    if "half_window" in params:
        kwargs["half_window"] = int(params["half_window"])
    if "max_half_window" in params:
        kwargs["max_half_window"] = int(params["max_half_window"])

    corrected, _ = correct_baseline(xy.y.astype(float, copy=False), method=method, **kwargs)
    return XY(x=xy.x, y=np.asarray(corrected, dtype=float))


def _baseline_curve(xy: XY, params: dict[str, Any]) -> XY:
    method = str(params.get("method", "derpsalsa"))

    # Keep param forwarding identical to _baseline for 1:1 comparability.
    kwargs: dict[str, Any] = {}
    if "lam" in params:
        kwargs["lam"] = float(params["lam"])
    if "p" in params:
        kwargs["p"] = float(params["p"])
    if "half_window" in params:
        kwargs["half_window"] = int(params["half_window"])
    if "max_half_window" in params:
        kwargs["max_half_window"] = int(params["max_half_window"])

    _, info = correct_baseline(xy.y.astype(float, copy=False), method=method, **kwargs)
    baseline = np.asarray(info.get("baseline", []), dtype=float)
    return XY(x=xy.x, y=baseline)


DEFAULT_STEPS: dict[str, StepImpl] = {
    "crop": StepImpl(name="crop", impl_version="1", transform=_crop),
    "normalize": StepImpl(name="normalize", impl_version="2", transform=_normalize),
    "noise_savgol": StepImpl(name="noise_savgol", impl_version="1", transform=_noise_savgol),
    "cosmic_ray_removal": StepImpl(name="cosmic_ray_removal", impl_version="1", transform=_cosmic_ray_removal),
    "baseline": StepImpl(name="baseline", impl_version="1", transform=_baseline),
    "baseline_curve": StepImpl(name="baseline_curve", impl_version="1", transform=_baseline_curve),
}


def params_fingerprint(step_name: str, params: dict[str, Any], impl_version: str) -> str:
    return canonical_json({"step": step_name, "params": params, "impl_version": impl_version})

