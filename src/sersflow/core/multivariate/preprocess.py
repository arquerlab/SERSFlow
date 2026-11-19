"""Preprocessing of a spectrum matrix before PCA / NMF / MCR / correlation / 2D-COS.

Order of operations (fixed, reported in ``meta["steps"]``):
  1. window crop and exclusion on x
  2. binning along x
  3. smoothing (Savitzky-Golay) and derivative
  4. row normalisation
  5. transform (sqrt / log)
  6. non-negativity handling
  7. column centring and scaling (skipped when the method forbids centring)
"""

from __future__ import annotations

from typing import Any

import numpy as np

ROW_NORMS = ("none", "area", "max", "l2", "snv", "ref_band")
TRANSFORMS = ("none", "sqrt", "log")
NONNEG = ("none", "clip", "shift")
CENTERS = ("none", "mean", "median")
SCALES = ("none", "autoscale", "pareto", "range", "poisson")


def _in_window(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    a, b = (lo, hi) if lo <= hi else (hi, lo)
    return (x >= a) & (x <= b)


def _bin_columns(Y: np.ndarray, x: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    n_out = Y.shape[1] // k
    if n_out < 1:
        return Y, x
    cut = n_out * k
    Yb = Y[:, :cut].reshape(Y.shape[0], n_out, k).mean(axis=2)
    xb = x[:cut].reshape(n_out, k).mean(axis=1)
    return Yb, xb


def preprocess_matrix(
    Y: np.ndarray,
    x: np.ndarray,
    opts: dict[str, Any] | None = None,
    *,
    require_nonneg: bool = False,
    allow_center: bool = True,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Return ``(Y_processed, x_processed, meta)``. ``opts`` keys (all optional):

    crop [lo, hi]; exclude [[lo, hi], ...]; bin (int >= 1);
    smooth_window (odd int, 0 = off), smooth_poly, derivative (0/1/2);
    row_norm (see ROW_NORMS), ref_band [lo, hi]; transform; nonneg; center; scale.

    ``require_nonneg`` (NMF / MCR): centring is disabled and a negative minimum is
    shifted to zero when ``nonneg`` is ``none``. ``allow_center=False`` (2D-COS) disables
    centring only.
    """
    o = dict(opts or {})
    Yp = np.asarray(Y, dtype=np.float64).copy()
    xp = np.asarray(x, dtype=np.float64).copy()
    steps: list[str] = []
    warnings: list[str] = []

    # NaN / inf -> column median (keeps matrix usable)
    bad = ~np.isfinite(Yp)
    if bad.any():
        med = np.nanmedian(np.where(bad, np.nan, Yp), axis=0)
        med = np.where(np.isfinite(med), med, 0.0)
        Yp = np.where(bad, med[None, :], Yp)
        steps.append(f"non-finite replaced by column median ({int(bad.sum())} cells)")

    # 1. window selection
    keep = np.ones(xp.shape[0], dtype=bool)
    crop = o.get("crop")
    if crop and len(crop) == 2 and crop[0] is not None and crop[1] is not None:
        keep &= _in_window(xp, float(crop[0]), float(crop[1]))
        steps.append(f"crop {crop[0]}..{crop[1]}")
    for w in o.get("exclude") or []:
        if w and len(w) == 2:
            keep &= ~_in_window(xp, float(w[0]), float(w[1]))
            steps.append(f"exclude {w[0]}..{w[1]}")
    ref_band = o.get("ref_band")
    ref_cols = None
    if (o.get("row_norm") or "none") == "ref_band":
        if not ref_band or len(ref_band) != 2:
            raise ValueError("row_norm 'ref_band' needs ref_band=[lo, hi]")
        ref_cols = _in_window(xp, float(ref_band[0]), float(ref_band[1]))
        if not ref_cols.any():
            raise ValueError("ref_band does not overlap the x axis")
        ref_vals = Yp[:, ref_cols].mean(axis=1)  # before cropping, so the band can be excluded later
    if not keep.all():
        Yp, xp = Yp[:, keep], xp[keep]
    if Yp.shape[1] < 2:
        raise ValueError("fewer than 2 channels left after crop/exclude")

    # 2. binning
    b = int(o.get("bin") or 1)
    if b > 1:
        Yp, xp = _bin_columns(Yp, xp, b)
        steps.append(f"bin x{b}")

    # 3. smoothing / derivative
    sw = int(o.get("smooth_window") or 0)
    deriv = int(o.get("derivative") or 0)
    if sw or deriv:
        from scipy.signal import savgol_filter

        if sw == 0:
            sw = 7
        if sw % 2 == 0:
            sw += 1
        poly = int(o.get("smooth_poly") or 3)
        poly = max(deriv, min(poly, sw - 1))
        if sw > Yp.shape[1]:
            raise ValueError("smooth_window larger than number of channels")
        dx = float(np.median(np.diff(xp))) if xp.size > 1 else 1.0
        Yp = savgol_filter(Yp, sw, poly, deriv=deriv, delta=abs(dx) or 1.0, axis=1)
        steps.append(f"savgol window={sw} poly={poly} deriv={deriv}")

    # 4. row normalisation
    rn = o.get("row_norm") or "none"
    if rn not in ROW_NORMS:
        raise ValueError(f"unknown row_norm {rn!r}")
    if rn != "none":
        if rn == "area":
            d = np.trapezoid(np.abs(Yp), xp, axis=1) if hasattr(np, "trapezoid") else np.trapz(np.abs(Yp), xp, axis=1)
            d = np.abs(d)
        elif rn == "max":
            d = np.max(np.abs(Yp), axis=1)
        elif rn == "l2":
            d = np.linalg.norm(Yp, axis=1)
        elif rn == "ref_band":
            d = np.abs(ref_vals)
        if rn == "snv":
            mu = Yp.mean(axis=1, keepdims=True)
            sd = Yp.std(axis=1, ddof=1, keepdims=True)
            sd[sd == 0] = 1.0
            Yp = (Yp - mu) / sd
        else:
            d = np.where(d == 0, 1.0, d)
            Yp = Yp / d[:, None]
        steps.append(f"row_norm {rn}")

    # 5. transform
    tr = o.get("transform") or "none"
    if tr not in TRANSFORMS:
        raise ValueError(f"unknown transform {tr!r}")
    if tr != "none":
        lo = float(Yp.min())
        if lo < 0:
            Yp = Yp - lo
            warnings.append(f"{tr} transform: matrix shifted by {-lo:.6g} to be non-negative")
        Yp = np.sqrt(Yp) if tr == "sqrt" else np.log1p(Yp)
        steps.append(f"transform {tr}")

    # 6. non-negativity
    nn = o.get("nonneg") or "none"
    if nn not in NONNEG:
        raise ValueError(f"unknown nonneg {nn!r}")
    if require_nonneg and nn == "none" and float(Yp.min()) < 0:
        nn = "shift"
        warnings.append("negative values present: non-negativity 'shift' applied automatically")
    if nn == "clip":
        n_neg = int((Yp < 0).sum())
        Yp = np.clip(Yp, 0.0, None)
        steps.append(f"nonneg clip ({n_neg} cells)")
    elif nn == "shift":
        lo = float(Yp.min())
        if lo < 0:
            Yp = Yp - lo
            steps.append(f"nonneg shift by {-lo:.6g}")

    # 7. column centring and scaling
    meta_col: dict[str, Any] = {}
    centre = o.get("center") or "mean"
    scale = o.get("scale") or "none"
    if centre not in CENTERS:
        raise ValueError(f"unknown center {centre!r}")
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}")
    if scale == "poisson":
        if float(Yp.min()) < 0:
            raise ValueError("Poisson scaling needs non-negative data (set nonneg=clip/shift)")
        g = np.maximum(Yp.mean(axis=1), 1e-12)  # row means
        h = np.maximum(Yp.mean(axis=0), 1e-12)  # column means
        Yp = Yp / np.sqrt(g)[:, None] / np.sqrt(h)[None, :]
        steps.append("scale poisson (Keenan-Kotula)")
        scale_vec = None
    else:
        scale_vec = None
    if require_nonneg or not allow_center:
        if centre != "none":
            warnings.append("centring disabled for this method")
        centre = "none"
    if centre == "mean":
        mu = Yp.mean(axis=0)
        Yp = Yp - mu
        meta_col["center_vector"] = mu.tolist()
        steps.append("center mean")
    elif centre == "median":
        mu = np.median(Yp, axis=0)
        Yp = Yp - mu
        meta_col["center_vector"] = mu.tolist()
        steps.append("center median")
    if scale in ("autoscale", "pareto", "range"):
        if scale == "autoscale":
            scale_vec = Yp.std(axis=0, ddof=1)
        elif scale == "pareto":
            scale_vec = np.sqrt(Yp.std(axis=0, ddof=1))
        else:
            scale_vec = Yp.max(axis=0) - Yp.min(axis=0)
        scale_vec = np.where(scale_vec > 0, scale_vec, 1.0)
        Yp = Yp / scale_vec[None, :]
        steps.append(f"scale {scale}")

    meta = {
        "steps": steps,
        "warnings": warnings,
        "n_channels_in": int(np.asarray(x).shape[0]),
        "n_channels_out": int(xp.shape[0]),
        "options": {k: v for k, v in o.items() if v not in (None, [], "")},
        **meta_col,
    }
    return Yp, xp, meta
