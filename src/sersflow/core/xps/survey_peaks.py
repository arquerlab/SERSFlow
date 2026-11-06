"""Peak finding on a survey spectrum and matching of the maxima to the library lines (X2)."""

from __future__ import annotations

from typing import Any

import numpy as np

from sersflow.core.xps.line_markers import element_line_markers


def _smooth(y: np.ndarray, window: int) -> np.ndarray:
    n = y.size
    window = max(3, min(int(window) | 1, n - (1 - n % 2)))
    if window < 5 or n < 7:
        return y.copy()
    from scipy.signal import savgol_filter

    return savgol_filter(y, window, 2)


def detect_survey_peaks(
    x: list[float] | np.ndarray,
    y: list[float] | np.ndarray,
    *,
    prominence_pct: float = 2.0,
    smooth_eV: float = 0.8,
    tolerance_eV: float = 2.0,
    photon_energy_eV: float | None = None,
    max_peaks: int = 60,
    max_alternatives: int = 3,
) -> dict[str, Any]:
    """
    Local maxima of the smoothed survey (Savitzky-Golay, ``smooth_eV`` wide) with a prominence of at least
    ``prominence_pct`` percent of the smoothed range, matched by POSITION ONLY to the derived element-line markers:
    a peak matches a line when it lies inside that line's library range (min-max of the tabulated energies) or within
    ``tolerance_eV`` of it. Candidates are ranked by distance to the range, then by offset from the marker energy
    (``delta_eV``); ``in_library_range`` tells whether the peak sits inside the tabulated range. Peaks with no marker
    stay unmatched. This is a labelling aid, not an identification (no intensity-ratio check).
    """
    from scipy.signal import find_peaks

    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    ok = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[ok], ya[ok]
    if xa.size < 10:
        raise ValueError("survey needs at least 10 points")
    order = np.argsort(xa)
    xa, ya = xa[order], ya[order]
    step = float(np.median(np.diff(xa)))
    if not np.isfinite(step) or step <= 0:
        raise ValueError("x values must be distinct")
    ys = _smooth(ya, int(round(smooth_eV / step)))
    rng = float(np.max(ys) - np.min(ys))
    if rng <= 0:
        return {"peaks": [], "count": 0, "step_eV": step}
    prom = max(rng * float(prominence_pct) / 100.0, 1e-12)
    idx, props = find_peaks(ys, prominence=prom)
    if idx.size > max_peaks:
        keep = np.argsort(props["prominences"])[::-1][:max_peaks]
        idx = idx[np.sort(keep)]
        props = {k: v[np.sort(keep)] for k, v in props.items()}
    # Wide window: a line's tabulated range can extend well past its marker energy (C 1s: ~281-297 eV).
    markers = element_line_markers(
        be_min=float(xa.min()) - 30.0, be_max=float(xa.max()) + 30.0, photon_energy_eV=photon_energy_eV
    )["markers"]
    peaks: list[dict[str, Any]] = []
    for k, i in enumerate(idx):
        be = float(xa[i])
        cands = []
        for m in markers:
            dist = max(0.0, m["be_min_eV"] - be, be - m["be_max_eV"])
            if dist > tolerance_eV:
                continue
            cands.append(
                {
                    "label": m["label"],
                    "element": m["element"],
                    "line": m["line"],
                    "kind": m["kind"],
                    "be_eV": m["be_eV"],
                    "delta_eV": be - m["be_eV"],
                    "range_distance_eV": dist,
                    "in_library_range": dist == 0.0,
                    "basis": m["basis"],
                }
            )
        cands.sort(key=lambda c: (c["range_distance_eV"], abs(c["delta_eV"])))
        peaks.append(
            {
                "be_eV": be,
                "height": float(ya[i]),
                "prominence": float(props["prominences"][k]),
                "prominence_pct": float(props["prominences"][k] / rng * 100.0),
                "match": cands[0] if cands else None,
                "alternatives": cands[1 : 1 + max_alternatives],
            }
        )
    return {"peaks": peaks, "count": len(peaks), "step_eV": step, "tolerance_eV": tolerance_eV, "prominence_pct": prominence_pct}
