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
