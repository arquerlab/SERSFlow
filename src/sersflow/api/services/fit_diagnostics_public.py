"""Serialize FitDiagnostics for API / export payloads."""

from __future__ import annotations

import math
from typing import Any

from sersflow.core.preprocess.fit_diagnostics import FitDiagnostics

_FIELDS = (
    "rmse",
    "r2",
    "r2_adj",
    "ssr",
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
    "n_at_bound",
    "bg_gt_data_frac",
    "resid_mean_edge_lo",
    "resid_mean_edge_hi",
    "resid_lag1_autocorr",
)


def _json_safe(v: Any) -> Any:
    """Non-finite floats are not valid JSON (Starlette renders with allow_nan=False)."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def diagnostics_to_public(diag: FitDiagnostics) -> dict[str, Any]:
    return {k: _json_safe(getattr(diag, k)) for k in _FIELDS}
