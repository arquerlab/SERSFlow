"""Generalised two-dimensional correlation spectroscopy (Noda)."""

from __future__ import annotations

from typing import Any

import numpy as np

MAX_CHANNELS = 800


def twod_cos(
    Y: np.ndarray,
    x: np.ndarray,
    perturbation: np.ndarray,
    *,
    reference: str = "mean",
    perturbation_label: str = "sample order",
) -> dict[str, Any]:
    """Synchronous / asynchronous 2D correlation of the rows of ``Y``.

    ``perturbation`` has one value per row (sample index, time, potential, ...). Rows are sorted
    by it. When the sorted perturbation is not evenly spaced (relative tolerance 1e-3), the
    dynamic spectra are linearly interpolated onto an even grid of the same size so the
    Hilbert-Noda matrix is valid; this is reported in ``resampled``.
    """
    Y = np.asarray(Y, dtype=np.float64)
    t = np.asarray(perturbation, dtype=np.float64)
    if Y.shape[0] != t.shape[0]:
        raise ValueError("perturbation length must equal the number of spectra")
    p = Y.shape[1]
    if p > MAX_CHANNELS:
        raise ValueError(f"{p} channels exceed the 2D-COS limit of {MAX_CHANNELS}; bin or crop the matrix")
    ok = np.isfinite(t)
    Y, t = Y[ok], t[ok]
    m = Y.shape[0]
    if m < 3:
        raise ValueError("need at least 3 spectra with a perturbation value")
    order = np.argsort(t, kind="stable")
    Y, t = Y[order], t[order]
    if np.ptp(t) == 0:
        raise ValueError("perturbation values are all identical")

    d = np.diff(t)
    resampled = False
    if not np.allclose(d, d.mean(), rtol=1e-3, atol=0.0):
        tg = np.linspace(t[0], t[-1], m)
        Y = np.stack([np.interp(tg, t, Y[:, j]) for j in range(p)], axis=1)
        t = tg
        resampled = True

    if reference == "mean":
        ref = Y.mean(axis=0)
    elif reference == "first":
        ref = Y[0]
    elif reference == "last":
        ref = Y[-1]
    else:
        raise ValueError("reference must be mean, first or last")
    A = Y - ref[None, :]

    sync = (A.T @ A) / (m - 1)
    j = np.arange(m)
    diff = j[None, :] - j[:, None]  # k - j
    N = np.zeros((m, m))
    nz = diff != 0
    N[nz] = 1.0 / (np.pi * diff[nz])
    asyn = (A.T @ (N @ A)) / (m - 1)
    return {
        "kind": "cos2d",
        "x_cm1": np.asarray(x, dtype=float).tolist(),
        "synchronous": np.round(sync, 8).tolist(),
        "asynchronous": np.round(asyn, 8).tolist(),
        "autopower": np.diag(sync).tolist(),
        "reference_spectrum": ref.tolist(),
        "reference": reference,
        "perturbation": t.tolist(),
        "perturbation_label": perturbation_label,
        "n_spectra": int(m),
        "resampled": resampled,
        "note": (
            "Synchronous peaks (positive = in-phase change, negative = opposite). Asynchronous "
            "cross peaks give the order: for sync>0, async>0 means the band on the x axis changes "
            "before the band on the y axis (Noda rules)."
        ),
    }
