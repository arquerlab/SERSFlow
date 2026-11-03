"""Edge-step normalization for XAS / NEXAFS spectra (pre-edge subtraction, post-edge scaling)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.signal import savgol_filter

# Default windows as fractions of the available energy range (used when no explicit bounds).
_PRE_FRACTION_BELOW_E0 = 0.6  # pre-edge: lowest 60 % of the span below E0
_POST_FRACTION_ABOVE_E0 = 0.5  # post-edge: upper 50 % of the span above E0


@dataclass(frozen=True)
class XasNormalization:
    y: np.ndarray
    e0: float
    edge_step: float
    pre_range: tuple[float, float]
    post_range: tuple[float, float]


def find_e0(x: np.ndarray, y: np.ndarray) -> float:
    """Energy of the steepest rise of the lightly smoothed spectrum (central 80 % of the range)."""
    n = x.size
    win = max(5, (n // 50) | 1)
    if win % 2 == 0:
        win += 1
    ys = savgol_filter(y, win, 3) if n > win else y
    dy = np.gradient(ys, x)
    lo, hi = x[0] + 0.1 * (x[-1] - x[0]), x[-1] - 0.1 * (x[-1] - x[0])
    mask = (x >= lo) & (x <= hi)
    if not np.any(mask):
        mask = np.ones_like(x, dtype=bool)
    idx = np.flatnonzero(mask)
    return float(x[idx[np.argmax(dy[idx])]])


def _window(x: np.ndarray, lo: float, hi: float, need: int, label: str) -> np.ndarray:
    m = (x >= lo) & (x <= hi)
    if int(m.sum()) < need:
        raise ValueError(
            f"xas_normalize: {label} window [{lo:.2f}, {hi:.2f}] eV holds {int(m.sum())} points; "
            f"need at least {need}. Widen the window or lower the polynomial degree."
        )
    return m


def normalize_edge_step(
    x: np.ndarray,
    y: np.ndarray,
    *,
    e0: float | None = None,
    pre_min: float | None = None,
    pre_max: float | None = None,
    post_min: float | None = None,
    post_max: float | None = None,
    pre_degree: int = 1,
    post_degree: int = 1,
    flatten: bool = False,
) -> XasNormalization:
    """
    Subtract a polynomial pre-edge line and divide by the edge step at ``e0``
    (``post(e0) - pre(e0)``), so the pre-edge is 0 and the post-edge level is 1.

    ``e0`` and the fit windows default to automatic choices (see module constants).
    With ``flatten`` the post-edge slope is also removed above ``e0`` (Athena-style).
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    if x.size != y.size:
        raise ValueError("xas_normalize: x and y must have the same length")
    if not (0 <= pre_degree <= 3 and 0 <= post_degree <= 3):
        raise ValueError("xas_normalize: pre_degree and post_degree must be between 0 and 3")
    order = np.argsort(x, kind="stable")
    xs, ys = x[order], y[order]
    finite = np.isfinite(xs) & np.isfinite(ys)
    xs, ys = xs[finite], ys[finite]
    if xs.size < 8:
        raise ValueError("xas_normalize: need at least 8 finite points")

    e0_v = float(e0) if e0 is not None else find_e0(xs, ys)
    x_lo, x_hi = float(xs[0]), float(xs[-1])
    if not (x_lo < e0_v < x_hi):
        raise ValueError(f"xas_normalize: E0={e0_v:.2f} eV lies outside the data range [{x_lo:.2f}, {x_hi:.2f}]")
    pre_lo = x_lo if pre_min is None else float(pre_min)
    pre_hi = (x_lo + _PRE_FRACTION_BELOW_E0 * (e0_v - x_lo)) if pre_max is None else float(pre_max)
    post_lo = (e0_v + (1.0 - _POST_FRACTION_ABOVE_E0) * (x_hi - e0_v)) if post_min is None else float(post_min)
    post_hi = x_hi if post_max is None else float(post_max)
    if pre_hi >= e0_v or post_lo <= e0_v:
        raise ValueError("xas_normalize: the pre-edge window must end below E0 and the post-edge window start above it")

    pre_m = _window(xs, pre_lo, pre_hi, pre_degree + 2, "pre-edge")
    post_m = _window(xs, post_lo, post_hi, post_degree + 2, "post-edge")
    pre_c = np.polyfit(xs[pre_m] - e0_v, ys[pre_m], pre_degree)
    post_c = np.polyfit(xs[post_m] - e0_v, ys[post_m], post_degree)
    step = float(np.polyval(post_c, 0.0) - np.polyval(pre_c, 0.0))
    scale = float(max(np.max(np.abs(ys)), np.ptp(ys)))
    if not np.isfinite(step) or abs(step) <= 1e-9 * max(scale, np.finfo(float).tiny):
        raise ValueError("xas_normalize: edge step is zero or undefined; adjust E0 or the fit windows")

    xr = np.asarray(x, dtype=float) - e0_v
    pre_curve = np.polyval(pre_c, xr)
    out = (y - pre_curve) / step
    if flatten:
        post_norm = (np.polyval(post_c, xr) - pre_curve) / step
        above = np.asarray(x, dtype=float) > e0_v
        out = np.where(above, out - (post_norm - 1.0), out)
    return XasNormalization(
        y=out,
        e0=e0_v,
        edge_step=step,
        pre_range=(pre_lo, pre_hi),
        post_range=(post_lo, post_hi),
    )


def params_to_kwargs(params: dict[str, Any]) -> dict[str, Any]:
    def opt(key: str) -> float | None:
        v = params.get(key)
        return None if v is None or (isinstance(v, str) and not v.strip()) else float(v)

    return {
        "e0": opt("e0"),
        "pre_min": opt("pre_min"),
        "pre_max": opt("pre_max"),
        "post_min": opt("post_min"),
        "post_max": opt("post_max"),
        "pre_degree": int(params.get("pre_degree", 1)),
        "post_degree": int(params.get("post_degree", 1)),
        "flatten": bool(params.get("flatten", False)),
    }
