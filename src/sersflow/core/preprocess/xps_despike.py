"""Counting-statistics spike removal for XPS (C3).

Detector glitches and X-ray/cosmic events show up in XPS as one or two channels far above the
local trend. Raman-style detection (global MAD of a median-filter residual, spike >= 2x local
background) does not suit them: the noise of pulse-counted data grows with sqrt(counts), so a
single global scale either floods the peak region with false positives or misses spikes in the
background.

Method (``xps_poisson``):
  * reference value of every channel = leave-one-out local quadratic prediction from its
    neighbours (follows curvature at peak tops, unlike a median filter);
  * normalised residual u = (y - ref) / sqrt(max(ref, local median, floor) * (1 + sum w^2)), the Poisson-shaped
    scale including the variance of the reference itself;
  * the noise gain g is estimated robustly from the data (1.4826 * MAD(u))^2, so it works for raw
    counts, counts/s and rescaled data alike; z = u / sqrt(g);
  * a channel is a spike when z > threshold (``direction`` = positive) or |z| > threshold (both)
    and it is the strongest candidate inside its window, so the neighbours that merely see the
    spike in their reference are not flagged (one sign per pass, the strongest first).
    Flagged channels are replaced by their reference value and
    the pass is repeated.

Edge channels (half-window at each end) use a one-sided quadratic through the nearest points.
The x spacing is assumed to be (nearly) uniform, as for XPS acquisitions.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

MIN_EXCESS = 0.01  # a spike is at least 1 % above the local level


def _loo_weights(half: int) -> np.ndarray:
    """Weights (length 2*half+1, centre 0) of the leave-one-out quadratic prediction at the centre."""
    offs = np.array([o for o in range(-half, half + 1) if o != 0], dtype=float)
    a = np.vander(offs, 3, increasing=True)  # columns 1, o, o^2
    # prediction at offset 0 is the constant coefficient: first row of pinv(a)
    w = np.linalg.pinv(a)[0]
    full = np.zeros(2 * half + 1)
    full[:half] = w[: half]
    full[half + 1 :] = w[half:]
    return full


def _reference(y: np.ndarray, half: int) -> tuple[np.ndarray, np.ndarray]:
    """Leave-one-out quadratic prediction and sqrt(1 + sum w^2) per channel."""
    n = y.size
    ref = np.empty(n, dtype=float)
    infl = np.empty(n, dtype=float)
    w = _loo_weights(half)
    if n > 2 * half:
        ref[half : n - half] = np.convolve(y, w[::-1], mode="valid")
        infl[half : n - half] = np.sqrt(1.0 + float(np.sum(w**2)))
    edge = list(range(min(half, n))) + list(range(max(n - half, half), n))
    for i in edge:
        lo = 0 if i < half else n - (2 * half + 1)
        lo = max(lo, 0)
        idx = np.array([j for j in range(lo, min(lo + 2 * half + 1, n)) if j != i], dtype=int)
        if idx.size < 3:
            ref[i] = y[i]
            infl[i] = np.inf
            continue
        a = np.vander((idx - i).astype(float), 3, increasing=True)
        pinv = np.linalg.pinv(a)[0]
        ref[i] = float(pinv @ y[idx])
        infl[i] = float(np.sqrt(1.0 + np.sum(pinv**2)))
    return ref, infl


def detect_spikes_poisson(
    y: np.ndarray,
    *,
    threshold: float = 5.0,
    window: int = 7,
    direction: str = "positive",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One detection pass. Returns (mask, reference, z)."""
    y = np.asarray(y, dtype=float)
    n = y.size
    half = max(int(window) // 2, 2)
    mask = np.zeros(n, dtype=bool)
    if n < 2 * half + 2:
        return mask, y.copy(), np.zeros(n)
    ref, infl = _reference(y, half)
    finite = y[np.isfinite(y)]
    floor = max(1e-3 * float(np.max(np.abs(finite))) if finite.size else 0.0, 1e-12)
    # Noise level from a spike-robust level estimate: the reference itself can be negative or
    # inflated next to a large spike (quadratic extrapolation weights are not all positive).
    level = np.maximum(np.maximum(ref, median_filter(y, size=2 * half + 1, mode="nearest")), floor)
    scale = np.sqrt(level) * infl
    u = (y - ref) / scale
    ok = np.isfinite(u)
    if not np.any(ok):
        return mask, ref, np.zeros(n)
    med = float(np.median(u[ok]))
    mad = float(np.median(np.abs(u[ok] - med)))
    sigma = 1.4826 * mad
    if sigma <= 0.0:
        return mask, ref, np.zeros(n)
    z = (u - med) / sigma
    z = np.where(ok, z, 0.0)
    # A spike must also stand out by at least MIN_EXCESS of the local level, so noise-free or
    # extremely smooth data (tiny estimated noise) does not flag extrapolation round-off.
    big = np.abs(y - ref) > MIN_EXCESS * level
    # One sign per pass: that of the strongest excursion. A large spike (dip) makes its neighbours
    # look like dips (spikes) through their own reference, so the weaker opposite-sign candidates
    # are left for the next pass, after the real one has been replaced.
    cand = (z > float(threshold)) & big
    sign = 1.0
    if direction == "both":
        both = (np.abs(z) > float(threshold)) & big
        if np.any(both):
            sign = 1.0 if z[np.argmax(np.where(both, np.abs(z), 0.0))] > 0 else -1.0
            cand = both & (sign * z > 0)
    # A candidate is accepted only when no STRONGER candidate lies within the window: weaker ones
    # (including channels whose reference merely contains a spike) are re-examined next pass.
    order = np.flatnonzero(cand)[np.argsort(-sign * z[cand])]
    for k, i in enumerate(order):
        if not np.any(np.abs(order[:k] - i) <= half):
            mask[i] = True
    # Replacement values: refit each accepted spike from the channels that are not spike
    # candidates themselves, so an adjacent unflagged spike does not contaminate it.
    if np.any(mask):
        bad = (np.abs(z) > float(threshold)) if direction == "both" else (z > float(threshold))
        ref = ref.copy()
        for i in np.flatnonzero(mask):
            lo, hi = max(0, i - half - 1), min(n, i + half + 2)
            idx = np.array([j for j in range(lo, hi) if j != i and not bad[j]], dtype=int)
            if idx.size >= 4:
                coef = np.polyfit(idx - i, y[idx], 2)
                ref[i] = float(coef[-1])
    return mask, ref, z


def remove_spikes_poisson(
    y: np.ndarray,
    *,
    threshold: float = 5.0,
    window: int = 7,
    direction: str = "positive",
    n_iterations: int = 10,
    max_width: int = 3,
) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Iteratively detect and replace spikes. Returns (corrected, mask, n_replaced).

    ``max_width``: a run of more than this many adjacent replaced channels is not a spike but
    an under-sampled peak (or a wrong window) being eroded, and is restored untouched.
    """
    if direction not in ("positive", "both"):
        raise ValueError("direction must be 'positive' or 'both'")
    corrected = np.asarray(y, dtype=float).copy()
    combined = np.zeros(corrected.size, dtype=bool)
    for _ in range(max(int(n_iterations), 1)):
        mask, ref, _ = detect_spikes_poisson(
            corrected, threshold=threshold, window=window, direction=direction
        )
        if not np.any(mask):
            break
        corrected[mask] = ref[mask]
        combined |= mask
    orig = np.asarray(y, dtype=float)
    i = 0
    n = combined.size
    while i < n:
        if combined[i]:
            j = i
            while j < n and combined[j]:
                j += 1
            if j - i > int(max_width):
                corrected[i:j] = orig[i:j]
                combined[i:j] = False
            i = j
        else:
            i += 1
    return corrected, combined, int(combined.sum())
