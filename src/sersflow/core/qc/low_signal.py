from __future__ import annotations

from typing import Literal

import numpy as np

from sersflow.core.spectrum import XY


LowSignalMetric = Literal["mean", "median", "integrated", "max", "percentile"]


def low_signal_metric_value(
    xy: XY,
    *,
    metric: LowSignalMetric,
    percentile: float | None = None,
) -> float:
    """
    Compute a robust whole-spectrum signal metric.

    Rules:
    - Empty spectrum -> NaN
    - Non-finite values are ignored; if nothing finite remains -> NaN
    """
    y = np.asarray(xy.y, dtype=np.float64).ravel()
    x = np.asarray(xy.x, dtype=np.float64).ravel()
    if y.size == 0 or x.size == 0 or x.size != y.size:
        return float("nan")
    mask = np.isfinite(y)
    if not np.any(mask):
        return float("nan")
    yv = y[mask]
    xv = x[mask]

    if metric == "mean":
        return float(np.mean(yv))
    if metric == "median":
        return float(np.median(yv))
    if metric == "max":
        return float(np.max(yv))
    if metric == "integrated":
        # Integrate intensity over x using trapezoidal rule.
        # Sorting is defensive; most spectra are already monotonic in x.
        order = np.argsort(xv)
        xv_s = xv[order]
        yv_s = yv[order]
        if xv_s.size < 2:
            return float("nan")
        return float(np.trapezoid(yv_s, xv_s))
    if metric == "percentile":
        q = float(percentile if percentile is not None else 10.0)
        if not np.isfinite(q):
            return float("nan")
        q = max(0.0, min(100.0, q))
        return float(np.percentile(yv, q))

    raise ValueError(f"Unknown low-signal metric: {metric}")

