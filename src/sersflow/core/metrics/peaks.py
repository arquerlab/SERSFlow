from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import find_peaks

from sersflow.core.spectrum import XY


def nearest_peak_to_target(
    xy: XY,
    *,
    target_cm1: float,
    window_cm1: float | None,
    peak_find: dict[str, Any] | None,
) -> tuple[float | None, float | None]:
    """
    Detect peaks and return (intensity, peak_position_cm1) for the peak closest to target_cm1.

    If window_cm1 is set, restrict search to |x - target_cm1| <= window_cm1.
    Returns (None, None) if no peaks are found.
    """
    x = xy.x.astype(float, copy=False)
    y = xy.y.astype(float, copy=False)
    if x.size == 0 or y.size == 0:
        return None, None

    if window_cm1 is not None:
        w = float(window_cm1)
        mask = np.abs(x - float(target_cm1)) <= w
        if not np.any(mask):
            return None, None
        xs = np.asarray(x[mask], dtype=float)
        ys = np.asarray(y[mask], dtype=float)
    else:
        xs = np.asarray(x, dtype=float)
        ys = np.asarray(y, dtype=float)

    kwargs = _sanitize_find_peaks_kwargs(peak_find or {})
    peaks, _props = find_peaks(ys, **kwargs)
    if peaks.size == 0:
        return None, None

    peak_x = xs[peaks]
    dist = np.abs(peak_x - float(target_cm1))
    j = int(np.argmin(dist))
    idx = int(peaks[j])
    return float(ys[idx]), float(xs[idx])


def _sanitize_find_peaks_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    allowed = {
        "height",
        "threshold",
        "distance",
        "prominence",
        "width",
        "wlen",
        "rel_height",
        "plateau_size",
    }
    for k, v in raw.items():
        if k not in allowed:
            continue
        if v is None:
            continue
        out[k] = v
    return out
