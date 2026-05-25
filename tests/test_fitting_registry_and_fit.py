from __future__ import annotations

import numpy as np

from sersflow.core.preprocess.fitting import (
    FitComponent,
    FitProblem,
    _apply_auto_gaussian_amplitudes,
    _interp_y_at_x,
    fit_curve,
)
from sersflow.core.preprocess.fitting_specs import list_component_types


def test_fitting_models_registry_has_gaussian() -> None:
    specs = list_component_types()
    assert any(s.component_type == "gaussian" for s in specs)


def test_fit_component_curves_sum_to_total() -> None:
    rng = np.random.default_rng(1)
    x = np.linspace(400.0, 700.0, 200)
    y1 = 80.0 * np.exp(-((x - 520.0) ** 2) / (12.0**2 / 4.0 / np.log(2.0)))
    y2 = 40.0 * np.exp(-((x - 620.0) ** 2) / (15.0**2 / 4.0 / np.log(2.0)))
    y = y1 + y2 + rng.normal(0.0, 0.5, size=x.shape)
    components = [
        FitComponent(component_type="gaussian", component_id="a"),
        FitComponent(component_type="gaussian", component_id="b"),
    ]
    p0 = [520.0, 70.0, 14.0, 620.0, 35.0, 16.0]
    lo = [400.0, 0.0, 1e-6] * 2
    hi = [700.0, None, 80.0] * 2
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=components,
            p0=p0,
            bounds_lower=lo,
            bounds_upper=hi,
        )
    )
    s = np.zeros_like(x)
    for c in res.component_y_hat:
        s = s + c
    assert np.allclose(s, res.y_hat, rtol=1e-5, atol=1e-4)


def test_interp_y_at_x_unsorted_axis() -> None:
    x = np.array([3.0, 1.0, 2.0])
    y = np.array([30.0, 10.0, 20.0])
    assert abs(_interp_y_at_x(x, y, 2.0) - 20.0) < 1e-9


def test_apply_auto_gaussian_amplitudes_uses_intensity_at_pos() -> None:
    x = np.linspace(0.0, 10.0, 50)
    y = np.ones_like(x) * 42.0
    p0 = [5.0, 0.0, 1.0]
    comp = [FitComponent(component_type="gaussian", component_id="a")]
    slices = [(0, 3)]
    keys = [["pos", "amp", "fwhm"]]
    out = _apply_auto_gaussian_amplitudes(x, y, p0, comp, slices, keys)
    assert abs(out[1] - 42.0) < 1e-9


def test_fit_auto_gaussian_amplitude_clamps_to_bounds() -> None:
    x = np.linspace(0.0, 10.0, 80)
    y = np.ones_like(x) * 42.0
    components = [FitComponent(component_type="gaussian", component_id="a")]

    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=components,
            p0=[5.0, 0.0, 1.0],
            bounds_lower=[0.0, 0.0, 0.1],
            bounds_upper=[10.0, 10.0, 5.0],
            initial_guess_mode="auto",
        )
    )

    assert 0.0 <= float(res.p_opt[1]) <= 10.0


def test_fit_single_gaussian_with_bounds_smoke() -> None:
    rng = np.random.default_rng(0)
    x = np.linspace(480.0, 560.0, 400)
    true = {"pos": 520.0, "amp": 1000.0, "fwhm": 10.0}
    # same formula as fitting_models.gaussian
    y = true["amp"] * np.exp(-(np.power(x - true["pos"], 2) / (true["fwhm"] * true["fwhm"] / 4.0 / np.log(2.0))))
    y = y + rng.normal(0.0, 2.0, size=y.shape)

    components = [FitComponent(component_type="gaussian", component_id="p1")]
    # p0 order: pos, amp, fwhm
    p0 = [518.0, 900.0, 12.0]
    lo = [510.0, 0.0, 1e-6]
    hi = [530.0, None, 50.0]

    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=components,
            p0=p0,
            bounds_lower=lo,
            bounds_upper=hi,
        )
    )

    assert res.p_opt.shape == (3,)
    # bounded center should remain within bounds
    assert 510.0 <= float(res.p_opt[0]) <= 530.0
    assert len(res.component_y_hat) == 1
    assert np.allclose(res.component_y_hat[0], res.y_hat, rtol=1e-9)

