from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.pipeline.steps import DEFAULT_STEPS
from sersflow.core.preprocess.fitting import (
    apply_fit_window_xy,
    expand_fit_curves_to_full,
    fit_problem_from_step_params,
    fit_window_mask,
    parse_fit_window,
)
from sersflow.core.spectrum import XY


def test_parse_fit_window_none() -> None:
    assert parse_fit_window({}) == (None, None)
    assert parse_fit_window({"fit_min_x": None, "fit_max_x": ""}) == (None, None)


def test_parse_fit_window_bounds_and_validation() -> None:
    assert parse_fit_window({"fit_min_x": 10, "fit_max_x": 20}) == (10.0, 20.0)
    assert parse_fit_window({"fit_min_x": 5}) == (5.0, None)
    with pytest.raises(ValueError, match="fit_min_x"):
        parse_fit_window({"fit_min_x": 30, "fit_max_x": 10})


def test_fit_window_mask_and_crop() -> None:
    x = np.linspace(0.0, 100.0, 101)
    y = x.copy()
    xy = XY(x=x, y=y)
    params = {"fit_min_x": 40.0, "fit_max_x": 60.0}
    mask = fit_window_mask(x, params)
    assert int(mask.sum()) == 21
    cropped, m2 = apply_fit_window_xy(xy, params)
    assert np.array_equal(mask, m2)
    assert cropped.x.size == 21
    assert float(cropped.x[0]) == 40.0
    assert float(cropped.x[-1]) == 60.0


def test_expand_fit_curves_passthrough_outside() -> None:
    x = np.linspace(0.0, 10.0, 11)
    y = np.arange(11, dtype=float)
    xy = XY(x=x, y=y)
    params = {"fit_min_x": 3.0, "fit_max_x": 7.0}
    mask = fit_window_mask(x, params)
    y_fit = np.full(int(mask.sum()), 99.0)
    comps = [np.full(int(mask.sum()), 5.0)]
    y_hat, comps_full = expand_fit_curves_to_full(xy, params, y_fit, comps)
    assert y_hat.shape == x.shape
    assert np.allclose(y_hat[~mask], y[~mask])
    assert np.allclose(y_hat[mask], 99.0)
    assert comps_full[0].shape == x.shape
    assert np.allclose(comps_full[0][~mask], 0.0)
    assert np.allclose(comps_full[0][mask], 5.0)


def test_fit_problem_from_step_params_applies_window() -> None:
    x = np.linspace(400.0, 600.0, 201)
    y = 100.0 * np.exp(-((x - 500.0) ** 2) / (8.0**2 / 4.0 / np.log(2.0))) + 5.0
    xy = XY(x=x, y=y)
    params = {
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [500.0, 80.0, 10.0],
        "bounds_lower": [480.0, 0.0, 1e-6],
        "bounds_upper": [520.0, None, 50.0],
        "fit_min_x": 480.0,
        "fit_max_x": 520.0,
    }
    prob = fit_problem_from_step_params(xy, params)
    assert prob is not None
    assert float(prob.x.min()) >= 480.0
    assert float(prob.x.max()) <= 520.0
    assert prob.x.size < xy.x.size


def test_fitting_pipeline_step_fit_window_passthrough() -> None:
    x = np.linspace(400.0, 600.0, 201)
    y = 100.0 * np.exp(-((x - 500.0) ** 2) / (8.0**2 / 4.0 / np.log(2.0))) + 5.0
    # Distinct outside values so passthrough is observable.
    y = y.copy()
    y[x < 480.0] = -123.0
    y[x > 520.0] = -456.0
    xy = XY(x=x, y=y)
    impl = DEFAULT_STEPS["fitting"]
    params = {
        "output_mode": "fit",
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [500.0, 80.0, 10.0],
        "bounds_lower": [480.0, 0.0, 1e-6],
        "bounds_upper": [520.0, None, 50.0],
        "fit_min_x": 480.0,
        "fit_max_x": 520.0,
    }
    out = impl.transform(xy, params)
    assert out.x.shape == xy.x.shape
    assert np.allclose(out.y[x < 480.0], -123.0)
    assert np.allclose(out.y[x > 520.0], -456.0)
    assert float(np.max(out.y[(x >= 480.0) & (x <= 520.0)])) > 50.0
