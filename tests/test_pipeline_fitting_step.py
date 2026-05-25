from __future__ import annotations

import numpy as np

from sersflow.core.pipeline.steps import DEFAULT_STEPS
from sersflow.core.spectrum import XY


def test_fitting_pipeline_step_fit_mode() -> None:
    x = np.linspace(400.0, 600.0, 120)
    y = 100.0 * np.exp(-((x - 500.0) ** 2) / (8.0**2 / 4.0 / np.log(2.0))) + 5.0
    xy = XY(x=x, y=y)
    impl = DEFAULT_STEPS["fitting"]
    params = {
        "output_mode": "fit",
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [500.0, 80.0, 10.0],
        "bounds_lower": [480.0, 0.0, 1e-6],
        "bounds_upper": [520.0, None, 50.0],
    }
    out = impl.transform(xy, params)
    assert out.x.shape == xy.x.shape
    assert out.y.shape == xy.y.shape
    assert float(np.max(out.y)) > 50.0


def test_fitting_pipeline_step_ignores_fill_opacity_extra_key() -> None:
    """UI may persist fill_opacity; backend transform must ignore unknown keys."""
    x = np.linspace(400.0, 600.0, 80)
    y = 50.0 * np.exp(-((x - 500.0) ** 2) / (10.0**2 / 4.0 / np.log(2.0))) + 1.0
    xy = XY(x=x, y=y)
    impl = DEFAULT_STEPS["fitting"]
    params = {
        "output_mode": "fit",
        "fill_opacity": 0.42,
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [500.0, 40.0, 12.0],
        "bounds_lower": [400.0, 0.0, 1e-6],
        "bounds_upper": [600.0, None, 80.0],
    }
    out = impl.transform(xy, params)
    assert out.y.shape == xy.y.shape


def test_fitting_pipeline_step_pass_through_when_too_few_points() -> None:
    """Crop / range mismatch can leave too few points; batch must not error."""
    x = np.array([400.0, 401.0], dtype=float)
    y = np.array([1.0, 2.0], dtype=float)
    xy = XY(x=x, y=y)
    impl = DEFAULT_STEPS["fitting"]
    params = {
        "output_mode": "fit",
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [500.0, 80.0, 10.0],
        "bounds_lower": [480.0, 0.0, 1e-6],
        "bounds_upper": [520.0, None, 50.0],
    }
    out = impl.transform(xy, params)
    assert np.array_equal(out.x, xy.x)
    assert np.array_equal(out.y, xy.y)


def test_fitting_pipeline_step_residual_mode() -> None:
    x = np.linspace(400.0, 600.0, 120)
    y = 100.0 * np.exp(-((x - 500.0) ** 2) / (8.0**2 / 4.0 / np.log(2.0))) + 5.0
    xy = XY(x=x, y=y)
    impl = DEFAULT_STEPS["fitting"]
    params = {
        "output_mode": "residual",
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [500.0, 80.0, 10.0],
        "bounds_lower": [480.0, 0.0, 1e-6],
        "bounds_upper": [520.0, None, 50.0],
    }
    out = impl.transform(xy, params)
    assert out.x.shape == xy.x.shape
    assert float(np.max(np.abs(out.y))) < float(np.max(np.abs(y))) * 0.5
