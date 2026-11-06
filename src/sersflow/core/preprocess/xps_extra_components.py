"""
Backgrounds and components added for CasaXPS parity (B1, L1, M1).

* Endpoint levels with CasaXPS "Av Width" (+-N channels averaged at each region end) and percentage offsets that lower
  the background at the low-x / high-x end (CasaXPS Start/End Offset; Cookbook p.68, 171).
* Static iterative Shirley and linear endpoint backgrounds using those levels.
* ``erfc_step_bg``: erfc step (CasaXPS Step backgrounds, Cookbook p.98): B = height/2 * erfc((pos - x)/a) + const,
  a = FWHM / (2 sqrt(ln 2)); positive height = intensity rises with x (with BE, e.g. a Fermi edge seen in BE).
  ``pos`` is the inflection (CasaXPS "Step"); the "Edge" position is pos - a*sqrt(pi)/2 (tangent at the inflection
  meets the low level ``const``).
* ``linear_bg``: straight line between the levels at the two ends of the fitted window.
* ``tougaard_u4_bg``: Tougaard background with the general cross-section K(T) = B T / ((C + C' T^2)^2 + D T^2) for
  T > T0 (0 below), integrated over the signal at lower binding energy. U2 universal: B 2866, C 1643, C' 1, D 0.
* ``shirley_of_bg``: CasaXPS SB(0)X: Shirley-shaped background of one peak component X (scale k, energy shift),
  fitted together with the peaks (Cookbook p.71). Also gives a "Shirley of selected components".
* Finite DS / GDS area: integrated over the fit window (user decision L1).
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
from scipy.special import erfc

_SQRT_LN2 = math.sqrt(math.log(2.0))


# --------------------------------------------------------------------------------------------- endpoint levels


def resolve_avg_width(n: int, avg_width: Any) -> int:
    """Channels averaged on EACH side of an end channel; 'auto'/None = max(3, min(10, n/20)) total (legacy)."""
    if avg_width is None or (isinstance(avg_width, str) and avg_width.strip().lower() in ("", "auto")):
        return -1
    w = int(avg_width)
    if w < 0:
        raise ValueError("avg_width must be >= 0 channels (or 'auto')")
    return w


def endpoint_levels(
    x: np.ndarray,
    y: np.ndarray,
    *,
    avg_width: Any = None,
    offset_low_pct: float = 0.0,
    offset_high_pct: float = 0.0,
) -> tuple[float, float]:
    """(level at the low-x end, level at the high-x end) after averaging and percentage offsets."""
    xf = np.asarray(x, dtype=float)
    yf = np.asarray(y, dtype=float)
    if xf.size == 0:
        raise ValueError("empty spectrum")
    order = np.argsort(xf)
    ys = yf[order]
    n = ys.size
    w = resolve_avg_width(n, avg_width)
    if w < 0:
        n_end = int(max(3, min(10, n // 20)))
        lo_v, hi_v = float(np.median(ys[:n_end])), float(np.median(ys[-n_end:]))
    else:
        k = w if 2 * w + 1 <= n // 2 else 0  # CasaXPS: no averaging when the window does not fit
        lo_v, hi_v = float(np.mean(ys[: k + 1])), float(np.mean(ys[n - 1 - k :]))
    lo_v *= 1.0 - float(offset_low_pct or 0.0) / 100.0
    hi_v *= 1.0 - float(offset_high_pct or 0.0) / 100.0
    return lo_v, hi_v


def shirley_static(
    x: np.ndarray,
    y: np.ndarray,
    *,
    avg_width: Any = None,
    offset_low_pct: float = 0.0,
    offset_high_pct: float = 0.0,
    tol: float = 1e-6,
    maxit: int = 50,
) -> np.ndarray:
    """Iterative Shirley: B(x) = I_lo + (I_hi - I_lo) * A(<x) / A_total, A = area of (y - B)."""
    xf = np.asarray(x, dtype=float)
    yf = np.asarray(y, dtype=float)
    order = np.argsort(xf)
    xs, ys = xf[order], yf[order]
    lo_v, hi_v = endpoint_levels(xs, ys, avg_width=avg_width, offset_low_pct=offset_low_pct, offset_high_pct=offset_high_pct)
    bg = np.full_like(ys, lo_v)
    for _ in range(int(maxit)):
        sig = ys - bg
        dx = np.diff(xs)
        seg = 0.5 * (sig[1:] + sig[:-1]) * dx
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = cum[-1]
        if not np.isfinite(total) or total == 0.0:
            break
        new = lo_v + (hi_v - lo_v) * cum / total
        if np.max(np.abs(new - bg)) <= tol * max(1.0, abs(hi_v - lo_v)):
            bg = new
            break
        bg = new
    out = np.empty_like(bg)
    out[order] = bg
    return out


def linear_static(
    x: np.ndarray,
    y: np.ndarray,
    *,
    avg_width: Any = None,
    offset_low_pct: float = 0.0,
    offset_high_pct: float = 0.0,
) -> np.ndarray:
    xf = np.asarray(x, dtype=float)
    lo_v, hi_v = endpoint_levels(xf, y, avg_width=avg_width, offset_low_pct=offset_low_pct, offset_high_pct=offset_high_pct)
    return linear_bg(xf, lo_v, hi_v)


# --------------------------------------------------------------------------------------------- fit components


def erfc_step_bg(x: np.ndarray, *params: float) -> np.ndarray:
    """Params: pos (inflection), height, fwhm (Gaussian FWHM of the edge), const (level on the low-x side)."""
    pos, height, fwhm, const = (float(v) for v in params[:4])
    a = max(abs(fwhm), 1e-9) / (2.0 * _SQRT_LN2)
    xf = np.asarray(x, dtype=float)
    return 0.5 * height * erfc((pos - xf) / a) + const


def erfc_edge_position(pos: float, fwhm: float) -> float:
    """CasaXPS 'Edge' position: the tangent at the inflection meets the low level (pos - a sqrt(pi)/2)."""
    a = max(abs(float(fwhm)), 1e-9) / (2.0 * _SQRT_LN2)
    return float(pos) - a * math.sqrt(math.pi) / 2.0


def linear_bg(x: np.ndarray, *params: float) -> np.ndarray:
    """Params: low (value at the low-x end of x), high (value at the high-x end)."""
    low, high = float(params[0]), float(params[1])
    xf = np.asarray(x, dtype=float)
    if xf.size == 0:
        return xf.copy()
    x0, x1 = float(np.min(xf)), float(np.max(xf))
    if x1 <= x0:
        return np.full_like(xf, low)
    return low + (high - low) * (xf - x0) / (x1 - x0)


def tougaard_u4_bg(x: np.ndarray, y: np.ndarray, B: float, C: float, C_d: float, D: float, T0: float) -> np.ndarray:
    """
    Tougaard background on a binding-energy axis: B(E) = I_lo + sum_{E' < E} K(E - E') (y(E') - I_lo) dE'.

    K(T) = B T / ((C + C' T^2)^2 + D T^2) for T > T0, else 0 (U4 with band-gap onset T0; U2: C' = 1, D = 0).
    """
    xf = np.asarray(x, dtype=float)
    yf = np.asarray(y, dtype=float)
    order = np.argsort(xf)
    xs, ys = xf[order], yf[order]
    n = xs.size
    if n < 3:
        return np.full_like(yf, float(np.min(yf)) if yf.size else 0.0)
    i_lo = float(np.median(ys[: max(3, min(10, n // 20))]))
    sig = ys - i_lo
    dx = np.gradient(xs)
    T = xs[:, None] - xs[None, :]  # E - E'
    with np.errstate(divide="ignore", invalid="ignore"):
        K = float(B) * T / ((float(C) + float(C_d) * T**2) ** 2 + float(D) * T**2)
    K = np.where((T > max(float(T0), 0.0)) & np.isfinite(K), K, 0.0)
    bg = i_lo + K @ (sig * dx)
    out = np.empty_like(bg)
    out[order] = bg
    return out


def shirley_profile(x: np.ndarray, peak: np.ndarray, k: float) -> np.ndarray:
    """k * cumulative integral of ``peak`` toward increasing x (higher BE): the Shirley step of that peak."""
    xf = np.asarray(x, dtype=float)
    pf = np.asarray(peak, dtype=float)
    order = np.argsort(xf)
    xs, ps = xf[order], pf[order]
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (ps[1:] + ps[:-1]) * np.diff(xs))]) if xs.size > 1 else np.zeros_like(xs)
    out = np.empty_like(cum)
    out[order] = float(k) * cum
    return out


# --------------------------------------------------------------------------------------------- finite DS area


def windowed_area_per_height(fn: Callable[..., np.ndarray], values: list[float], window: tuple[float, float] | None, pos: float, width: float) -> float:
    """Area / height of a unit-height peak integrated over the fit window (DS/GDS, L1 user decision)."""
    if window is None or not all(math.isfinite(float(w)) for w in window):
        lo, hi = pos - 50.0 * max(width, 1e-3), pos + 50.0 * max(width, 1e-3)
    else:
        lo, hi = min(window), max(window)
    n = 4001
    xx = np.linspace(lo, hi, n)
    vals = list(values)
    vals[1] = 1.0  # unit height
    yy = np.asarray(fn(xx, *vals), dtype=float)
    trap = getattr(np, "trapezoid", None) or np.trapz
    return max(float(trap(yy, xx)), 1e-12)
