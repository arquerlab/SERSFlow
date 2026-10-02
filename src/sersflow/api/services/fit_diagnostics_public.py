"""Serialize FitDiagnostics for API / export payloads."""

from __future__ import annotations

from typing import Any

from sersflow.core.preprocess.fit_diagnostics import FitDiagnostics


def diagnostics_to_public(diag: FitDiagnostics) -> dict[str, Any]:
    return {
        "rmse": diag.rmse,
        "r2": diag.r2,
        "r2_adj": diag.r2_adj,
        "ssr": diag.ssr,
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
    }
