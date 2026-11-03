from __future__ import annotations

import math

import numpy as np
import pytest

from sersflow.core.preprocess.fit_diagnostics import compute_fit_diagnostics


def test_perfect_fit_diagnostics() -> None:
    x = np.linspace(0.0, 1.0, 50)
    y = 2.0 * x + 1.0
    diag = compute_fit_diagnostics(y, y, n_vary=2, success=True)
    assert diag.rmse == pytest.approx(0.0, abs=1e-12)
    assert diag.ssr == pytest.approx(0.0, abs=1e-12)
    assert diag.r2 == pytest.approx(1.0)
    assert diag.success == 1.0
    assert diag.n_points == 50.0
    assert diag.n_vary == 2.0
    # SSR=0 → AIC/BIC undefined
    assert math.isnan(diag.aic)


def test_known_ssr_and_rmse() -> None:
    y = np.array([0.0, 1.0, 2.0, 3.0], dtype=float)
    y_hat = np.array([0.0, 1.0, 2.0, 2.0], dtype=float)
    diag = compute_fit_diagnostics(y, y_hat, n_vary=1)
    assert diag.ssr == pytest.approx(1.0)
    assert diag.rmse == pytest.approx(0.5)
    assert diag.max_abs_resid == pytest.approx(1.0)
    assert diag.chi2 == pytest.approx(1.0)
    assert diag.redchi == pytest.approx(1.0 / 3.0)


def test_r2_adj_dof_edge() -> None:
    y = np.array([1.0, 2.0], dtype=float)
    y_hat = np.array([1.1, 1.9], dtype=float)
    diag = compute_fit_diagnostics(y, y_hat, n_vary=1)
    # n - k - 1 = 0 → adj R² undefined
    assert math.isnan(diag.r2_adj)


def test_fit_health_bg_above_data_and_edges() -> None:
    from sersflow.core.preprocess.fit_diagnostics import fit_health_metrics

    x = np.linspace(800.0, 780.0, 100)  # descending BE axis
    y = np.full_like(x, 100.0)
    y_hat = y.copy()
    # model above data (negative residual) at the HIGH-BE end only
    y_hat[:10] += 30.0
    bg = y.copy()
    bg[:10] += 5.0  # background above data at the 10 highest-BE points
    h = fit_health_metrics(y, y_hat, x=x, bg_curve=bg)
    assert h["bg_gt_data_frac"] == pytest.approx(0.10)
    assert h["resid_mean_edge_hi"] == pytest.approx(-30.0)  # high-x end = start of this descending array
    assert h["resid_mean_edge_lo"] == pytest.approx(0.0)


def test_fit_health_edges_independent_of_array_orientation() -> None:
    from sersflow.core.preprocess.fit_diagnostics import fit_health_metrics

    x = np.linspace(780.0, 800.0, 100)
    y = np.full_like(x, 50.0)
    y_hat = y.copy()
    y_hat[-10:] += 20.0
    a = fit_health_metrics(y, y_hat, x=x)
    b = fit_health_metrics(y[::-1], y_hat[::-1], x=x[::-1])
    assert a["resid_mean_edge_hi"] == pytest.approx(b["resid_mean_edge_hi"])
    assert a["resid_mean_edge_lo"] == pytest.approx(b["resid_mean_edge_lo"])
    assert a["resid_lag1_autocorr"] == pytest.approx(b["resid_lag1_autocorr"])


def test_lag1_autocorr_structured_vs_noise() -> None:
    from sersflow.core.preprocess.fit_diagnostics import fit_health_metrics

    rng = np.random.default_rng(0)
    x = np.linspace(0.0, 1.0, 400)
    noise = rng.normal(0.0, 1.0, 400)
    structured = np.sin(2 * np.pi * 2 * x) * 5.0 + rng.normal(0.0, 0.1, 400)
    h_noise = fit_health_metrics(noise, np.zeros(400), x=x)
    h_struct = fit_health_metrics(structured, np.zeros(400), x=x)
    assert abs(h_noise["resid_lag1_autocorr"]) < 0.2
    assert h_struct["resid_lag1_autocorr"] > 0.9


def test_health_metrics_default_to_none_without_inputs() -> None:
    diag = compute_fit_diagnostics(np.arange(10.0), np.arange(10.0) + 0.1, n_vary=1)
    assert diag.bg_gt_data_frac is None
    assert diag.resid_mean_edge_lo is None
    assert diag.n_at_bound is None
    assert diag.resid_lag1_autocorr is not None  # needs no x


def test_diagnostics_to_public_is_json_safe() -> None:
    import json

    from sersflow.api.services.fit_diagnostics_public import diagnostics_to_public
    from sersflow.core.metrics.fitting_features import diagnostics_from_feature_gof

    diag = diagnostics_from_feature_gof({"rmse": 1.0, "success": 1.0, "n_points": 10.0})
    assert diag is not None
    payload = diagnostics_to_public(diag)  # ssr is NaN when rebuilt from stored features
    assert payload["ssr"] is None
    json.dumps(payload, allow_nan=False)
