from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from sersflow.core.spectrum import XY


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float | None
    unit: str | None = None


_PEAK_HEIGHT_PATTERNS = [
    re.compile(r"^peak_(?P<center>\d+(\.\d+)?)_height$"),
    re.compile(r"^peak_height@(?P<center>\d+(\.\d+)?)$"),
]
_FWHM_PATTERNS = [
    re.compile(r"^fwhm_(?P<center>\d+(\.\d+)?)$"),
    re.compile(r"^fwhm@(?P<center>\d+(\.\d+)?)$"),
]


def _nearest_index(x: np.ndarray, center: float) -> int:
    return int(np.argmin(np.abs(x - center)))


def peak_height_at(xy: XY, *, center: float) -> float | None:
    if xy.x.size == 0:
        return None
    i = _nearest_index(xy.x, center)
    return float(xy.y[i])


def fwhm_at(xy: XY, *, center: float) -> float | None:
    """
    Approximate FWHM near a target center by looking for half-max crossings.

    This is a simple implementation intended for summary metrics; it assumes a single dominant peak near `center`.
    """
    x = xy.x
    y = xy.y
    if x.size < 3:
        return None

    peak_i = _nearest_index(x, center)
    peak_y = float(y[peak_i])
    half = peak_y / 2.0

    # Search left for crossing
    left_i = None
    for i in range(peak_i, 0, -1):
        if y[i] >= half and y[i - 1] < half:
            left_i = i - 1
            break
        if y[i] <= half and y[i - 1] > half:
            left_i = i - 1
            break

    # Search right for crossing
    right_i = None
    for i in range(peak_i, x.size - 1):
        if y[i] >= half and y[i + 1] < half:
            right_i = i + 1
            break
        if y[i] <= half and y[i + 1] > half:
            right_i = i + 1
            break

    if left_i is None or right_i is None:
        return None

    return float(abs(x[right_i] - x[left_i]))


def compute_metrics(xy: XY, metric_names: list[str]) -> list[MetricResult]:
    out: list[MetricResult] = []
    for name in metric_names:
        m = None
        for pat in _PEAK_HEIGHT_PATTERNS:
            mt = pat.match(name)
            if mt:
                center = float(mt.group("center"))
                out.append(MetricResult(name=name, value=peak_height_at(xy, center=center)))
                m = True
                break
        if m:
            continue

        for pat in _FWHM_PATTERNS:
            mt = pat.match(name)
            if mt:
                center = float(mt.group("center"))
                out.append(MetricResult(name=name, value=fwhm_at(xy, center=center), unit="cm^-1"))
                m = True
                break
        if m:
            continue

        out.append(MetricResult(name=name, value=None))
    return out

