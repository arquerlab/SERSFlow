"""Instrumental Gaussian broadening of peak components (step option ``gaussian_fwhm_eV``).

The broadening is a convolution of each peak with a normalised Gaussian of the given FWHM, so peak AREAS are
unchanged and the fitted ``fwhm`` / ``sigma`` parameters stay the intrinsic (pre-broadening) widths.
Backgrounds are not broadened.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np

FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))  # 2.3548...
_KERNEL_SIGMAS = 4.0
_MAX_GRID = 40_000


def gaussian_fwhm_from_params(params: dict) -> float:
    """Read ``gaussian_fwhm_eV`` from step params; invalid / negative / missing -> 0 (no broadening)."""
    raw = params.get("gaussian_fwhm_eV")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) and v > 0 else 0.0


def broaden_curve(x: np.ndarray, y_fn: Callable[[np.ndarray], np.ndarray], fwhm: float) -> np.ndarray:
    """Convolve ``y_fn`` (evaluated on a fine uniform grid padded by 4 sigma) with a Gaussian, sampled at ``x``."""
    xf = np.asarray(x, dtype=float)
    if fwhm <= 0 or xf.size == 0:
        return np.asarray(y_fn(xf), dtype=float)
    sigma = fwhm / FWHM_PER_SIGMA
    pad = _KERNEL_SIGMAS * sigma
    lo, hi = float(np.min(xf)) - pad, float(np.max(xf)) + pad
    step = sigma / 6.0
    if (hi - lo) / step > _MAX_GRID:
        step = (hi - lo) / _MAX_GRID
    n = int(math.ceil((hi - lo) / step)) + 1
    grid = lo + step * np.arange(n)
    yg = np.asarray(y_fn(grid), dtype=float)
    half = max(1, int(round(pad / step)))
    k = np.exp(-0.5 * ((np.arange(-half, half + 1) * step) / sigma) ** 2)
    k /= k.sum()
    conv = np.convolve(yg, k, mode="same")
    return np.interp(xf, grid, conv)


def with_gaussian_broadening(fn: Callable[..., np.ndarray], fwhm: float) -> Callable[..., np.ndarray]:
    """Wrap a component function ``fn(x, *params)`` so it is Gaussian-broadened; identity when ``fwhm <= 0``."""
    if not fwhm or fwhm <= 0:
        return fn

    def broadened(x, *p):
        return broaden_curve(x, lambda g: fn(g, *p), fwhm)

    return broadened
