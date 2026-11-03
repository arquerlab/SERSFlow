"""Goodness-of-fit diagnostics shared by SciPy and lmfit fitting engines."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FitDiagnostics:
    rmse: float
    r2: float
    r2_adj: float
    ssr: float
    aic: float
    bic: float
    aicc: float
    chi2: float
    redchi: float
    resid_mad: float
    max_abs_resid: float
    success: float
    n_points: float
    n_vary: float
    nfev: float | None
    median_rel_stderr: float | None
    # Fit-health metrics (None when the inputs needed to compute them were not available).
    n_at_bound: float | None = None
    bg_gt_data_frac: float | None = None
    resid_mean_edge_lo: float | None = None
    resid_mean_edge_hi: float | None = None
    resid_lag1_autocorr: float | None = None


def _finite_or_nan(v: float) -> float:
    return float(v) if math.isfinite(v) else float("nan")


def median_rel_stderr(
    p_opt: np.ndarray | None,
    p_cov: np.ndarray | None,
) -> float | None:
    if p_opt is None or p_cov is None:
        return None
    p = np.asarray(p_opt, dtype=float).ravel()
    cov = np.asarray(p_cov, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        return None
    n = min(p.size, cov.shape[0])
    if n <= 0:
        return None
    ratios: list[float] = []
    for i in range(n):
        var = float(cov[i, i])
        if not math.isfinite(var) or var < 0:
            continue
        se = math.sqrt(var)
        den = abs(float(p[i]))
        if den <= 0 or not math.isfinite(den) or not math.isfinite(se):
            continue
        ratios.append(se / den)
    if not ratios:
        return None
    return float(np.median(np.asarray(ratios, dtype=float)))


def _edge_len(n: int) -> int:
    return int(max(3, min(n // 2, round(0.05 * n)))) if n >= 6 else max(1, n // 2)


def fit_health_metrics(
    y: np.ndarray,
    y_hat: np.ndarray,
    *,
    x: np.ndarray | None = None,
    bg_curve: np.ndarray | None = None,
) -> dict[str, float | None]:
    """
    Fit-health scalars: background above data, window-edge residual means, residual lag-1 autocorr.

    Edges are defined by x (low-BE / high-BE ends), never by array position, so the values are
    independent of the orientation the fitter used. Without ``x`` the edges are not computed.
    """
    yf = np.asarray(y, dtype=float).ravel()
    yh = np.asarray(y_hat, dtype=float).ravel()
    out: dict[str, float | None] = {
        "bg_gt_data_frac": None,
        "resid_mean_edge_lo": None,
        "resid_mean_edge_hi": None,
        "resid_lag1_autocorr": None,
    }
    n = int(yf.size)
    if n < 4 or yh.size != n:
        return out
    resid = yf - yh
    order = None
    if x is not None:
        xf = np.asarray(x, dtype=float).ravel()
        if xf.size == n and np.all(np.isfinite(xf)):
            order = np.argsort(xf)
    ro = resid[order] if order is not None else resid
    rc = ro - float(np.mean(ro))
    den = float(np.dot(rc, rc))
    if den > 0 and math.isfinite(den):
        out["resid_lag1_autocorr"] = float(np.dot(rc[1:], rc[:-1]) / den)
    if order is not None:
        k = _edge_len(n)
        out["resid_mean_edge_lo"] = float(np.mean(ro[:k]))
        out["resid_mean_edge_hi"] = float(np.mean(ro[-k:]))
    if bg_curve is not None:
        bg = np.asarray(bg_curve, dtype=float).ravel()
        if bg.size == n:
            ok = np.isfinite(bg) & np.isfinite(yf)
            if ok.any():
                out["bg_gt_data_frac"] = float(np.mean(bg[ok] > yf[ok]))
    return out


def compute_fit_diagnostics(
    y: np.ndarray,
    y_hat: np.ndarray,
    *,
    n_vary: int,
    p_cov: np.ndarray | None = None,
    p_opt: np.ndarray | None = None,
    nfev: int | None = None,
    success: bool = True,
    x: np.ndarray | None = None,
    bg_curve: np.ndarray | None = None,
    n_at_bound: int | None = None,
) -> FitDiagnostics:
    """
    Compute GoF scalars from observed y and model y_hat.

    Uses a unit-variance Gaussian residual model for AIC/BIC/AICc (k_ic = n_vary + 1).
    """
    yf = np.asarray(y, dtype=float).ravel()
    yh = np.asarray(y_hat, dtype=float).ravel()
    if yf.shape != yh.shape:
        raise ValueError("y and y_hat length mismatch")
    n = int(yf.size)
    k = max(0, int(n_vary))
    if n == 0:
        return FitDiagnostics(
            rmse=float("nan"),
            r2=float("nan"),
            r2_adj=float("nan"),
            ssr=float("nan"),
            aic=float("nan"),
            bic=float("nan"),
            aicc=float("nan"),
            chi2=float("nan"),
            redchi=float("nan"),
            resid_mad=float("nan"),
            max_abs_resid=float("nan"),
            success=1.0 if success else 0.0,
            n_points=0.0,
            n_vary=float(k),
            nfev=float(nfev) if nfev is not None and math.isfinite(float(nfev)) else None,
            median_rel_stderr=median_rel_stderr(p_opt, p_cov),
        )

    resid = yf - yh
    ssr = float(np.dot(resid, resid))
    rmse = math.sqrt(ssr / n) if n > 0 else float("nan")
    y_mean = float(np.mean(yf))
    sst = float(np.dot(yf - y_mean, yf - y_mean))
    if sst > 0 and math.isfinite(sst):
        r2 = 1.0 - (ssr / sst)
    else:
        r2 = float("nan")
    dof_adj = n - k - 1
    if math.isfinite(r2) and dof_adj > 0:
        r2_adj = 1.0 - (1.0 - r2) * (n - 1) / dof_adj
    else:
        r2_adj = float("nan")

    chi2 = ssr
    dof = max(n - k, 1)
    redchi = ssr / dof

    k_ic = k + 1
    if ssr > 0 and math.isfinite(ssr):
        aic = n * math.log(ssr / n) + 2.0 * k_ic
        bic = n * math.log(ssr / n) + k_ic * math.log(n)
        if n > k_ic + 1:
            aicc = aic + (2.0 * k_ic * (k_ic + 1)) / (n - k_ic - 1)
        else:
            aicc = float("nan")
    else:
        aic = bic = aicc = float("nan")

    med = float(np.median(resid))
    resid_mad = float(np.median(np.abs(resid - med)))
    max_abs_resid = float(np.max(np.abs(resid))) if n > 0 else float("nan")

    health = fit_health_metrics(yf, yh, x=x, bg_curve=bg_curve)
    return FitDiagnostics(
        rmse=_finite_or_nan(rmse),
        r2=_finite_or_nan(r2),
        r2_adj=_finite_or_nan(r2_adj),
        ssr=_finite_or_nan(ssr),
        aic=_finite_or_nan(aic),
        bic=_finite_or_nan(bic),
        aicc=_finite_or_nan(aicc),
        chi2=_finite_or_nan(chi2),
        redchi=_finite_or_nan(redchi),
        resid_mad=_finite_or_nan(resid_mad),
        max_abs_resid=_finite_or_nan(max_abs_resid),
        success=1.0 if success else 0.0,
        n_points=float(n),
        n_vary=float(k),
        nfev=float(nfev) if nfev is not None and math.isfinite(float(nfev)) else None,
        median_rel_stderr=median_rel_stderr(p_opt, p_cov),
        n_at_bound=float(n_at_bound) if n_at_bound is not None else None,
        **health,
    )


GOF_METRIC_KEYS: tuple[str, ...] = (
    "rmse",
    "r2",
    "r2_adj",
    "aic",
    "bic",
    "aicc",
    "chi2",
    "redchi",
    "resid_mad",
    "max_abs_resid",
    "success",
    "n_points",
    "n_vary",
    "nfev",
    "median_rel_stderr",
    # fit-health metrics (appended; old runs simply lack these columns)
    "n_at_bound",
    "bg_gt_data_frac",
    "resid_mean_edge_lo",
    "resid_mean_edge_hi",
    "resid_lag1_autocorr",
)


def diagnostics_as_feature_dict(diag: FitDiagnostics) -> dict[str, float | None]:
    """Map diagnostics to float|None feature values (None for missing optional fields)."""
    out: dict[str, float | None] = {
        "rmse": diag.rmse,
        "r2": diag.r2,
        "r2_adj": diag.r2_adj,
        "aic": diag.aic,
        "bic": diag.bic,
        "aicc": diag.aicc,
        "chi2": diag.chi2,
        "redchi": diag.redchi,
        "resid_mad": diag.resid_mad,
        "max_abs_resid": diag.max_abs_resid,
        "success": diag.success,
        "n_points": diag.n_points,
        "n_vary": diag.n_vary,
        "nfev": diag.nfev,
        "median_rel_stderr": diag.median_rel_stderr,
        "n_at_bound": diag.n_at_bound,
        "bg_gt_data_frac": diag.bg_gt_data_frac,
        "resid_mean_edge_lo": diag.resid_mean_edge_lo,
        "resid_mean_edge_hi": diag.resid_mean_edge_hi,
        "resid_lag1_autocorr": diag.resid_lag1_autocorr,
    }
    for k, v in list(out.items()):
        if v is not None and isinstance(v, float) and not math.isfinite(v):
            out[k] = None
    return out
