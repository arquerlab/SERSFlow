from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.pipeline.steps import _align_resample
from sersflow.core.spectrum import XY


def test_align_descending_axis_strictly_increasing_x_and_interp():
    x = np.arange(1200.0, 399.0, -40.0)
    y = x.copy()
    out = _align_resample(XY(x=x, y=y), {"grid_mode": "step", "step": 50.0, "interp": "linear"})
    assert np.all(np.diff(out.x) > 0)
    assert np.allclose(out.y, out.x, rtol=0.0, atol=1e-9)


def test_two_native_spacings_identical_x_under_matrix_tolerance():
    x_lo, x_hi = 400.0, 2000.0
    x_a = np.linspace(x_lo, x_hi, 50)
    x_b = np.linspace(x_lo, x_hi, 200)
    y_a = np.sin(x_a / 200.0)
    y_b = np.sin(x_b / 200.0)
    params = {"grid_mode": "step", "step": 25.0, "interp": "linear"}
    out_a = _align_resample(XY(x=x_a, y=y_a), params)
    out_b = _align_resample(XY(x=x_b, y=y_b), params)
    assert out_a.x.shape == out_b.x.shape
    assert np.allclose(out_a.x, out_b.x, rtol=0.0, atol=1e-3)


def test_points_mode_matching_n_points_recovers_same_x():
    x_a = np.linspace(100, 500, 33)
    x_b = np.geomspace(100, 500, 48)
    params = {"grid_mode": "points", "n_points": 64, "interp": "linear"}
    out_a = _align_resample(XY(x=x_a, y=np.ones_like(x_a)), params)
    out_b = _align_resample(XY(x=x_b, y=np.ones_like(x_b)), params)
    assert np.allclose(out_a.x, out_b.x, rtol=0.0, atol=1e-3)


def test_explicit_min_max_forces_identical_grid_even_if_native_edges_differ():
    # Simulate different post-crop edges (native grids start/end on different values).
    x_a = np.linspace(180.7, 1198.9, 1019)
    x_b = np.linspace(181.2, 1199.1, 1003)
    y_a = np.cos(x_a / 123.0)
    y_b = np.cos(x_b / 123.0)
    params = {"grid_mode": "step", "step": 1.0, "interp": "linear", "min_x": 180.0, "max_x": 1200.0}
    out_a = _align_resample(XY(x=x_a, y=y_a), params)
    out_b = _align_resample(XY(x=x_b, y=y_b), params)
    assert np.allclose(out_a.x, out_b.x, rtol=0.0, atol=1e-12)


@pytest.mark.parametrize(
    "params,match",
    [
        ({"grid_mode": "step", "step": 0.0}, "step must be positive"),
        ({"grid_mode": "step", "step": -1.0}, "step must be positive"),
        ({"grid_mode": "points", "n_points": 1}, "n_points must be at least 2"),
        ({"grid_mode": "fft"}, "unknown grid_mode"),
        ({"grid_mode": "step", "step": 1.0, "interp": "spline"}, "unknown interp"),
        ({"grid_mode": "step", "step": 1.0, "min_x": 2.0, "max_x": 1.0}, "max_x must be > min_x"),
    ],
)
def test_invalid_params_raise(params: dict, match: str):
    x = np.linspace(0, 10, 20)
    y = x**2
    merged = {"grid_mode": "step", "step": 1.0, "interp": "linear", **params}
    with pytest.raises(ValueError, match=match):
        _align_resample(XY(x=x, y=y), merged)
