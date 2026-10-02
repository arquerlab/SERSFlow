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


def test_fitting_models_registry_has_peak_shapes() -> None:
    specs = list_component_types()
    types = {s.component_type for s in specs}
    assert "gaussian" in types
    assert "lorentzian" in types
    assert "pseudo_voigt" in types
    assert "gl" in types
    assert "voigt" in types
    assert "ds" in types
    assert "gds" in types
    assert "la" in types
    assert "lf" in types
    assert "apv" in types
    assert "asymmetric_voigt" in types
    assert "polynomial_background" in types


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


def test_fit_single_lorentzian_smoke() -> None:
    rng = np.random.default_rng(2)
    x = np.linspace(480.0, 560.0, 400)
    true = {"pos": 520.0, "amp": 800.0, "fwhm": 12.0}
    y = true["amp"] / (1.0 + 4.0 * ((x - true["pos"]) / true["fwhm"]) ** 2)
    y = y + rng.normal(0.0, 2.0, size=y.shape)

    components = [FitComponent(component_type="lorentzian", component_id="p1")]
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=components,
            p0=[518.0, 700.0, 14.0],
            bounds_lower=[510.0, 0.0, 1e-6],
            bounds_upper=[530.0, None, 50.0],
        )
    )
    assert abs(float(res.p_opt[0]) - 520.0) < 1.0
    assert abs(float(res.p_opt[1]) - 800.0) < 50.0


def test_fit_single_pseudo_voigt_smoke() -> None:
    rng = np.random.default_rng(3)
    x = np.linspace(480.0, 560.0, 400)
    from sersflow.core.preprocess.fitting_models import pseudo_voigt

    y = pseudo_voigt(x, 520.0, 900.0, 14.0, 0.4)
    y = y + rng.normal(0.0, 2.0, size=y.shape)

    components = [FitComponent(component_type="pseudo_voigt", component_id="p1")]
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=components,
            p0=[518.0, 800.0, 16.0, 0.5],
            bounds_lower=[510.0, 0.0, 1e-6, 0.0],
            bounds_upper=[530.0, None, 50.0, 1.0],
        )
    )
    assert abs(float(res.p_opt[0]) - 520.0) < 1.5
    assert 0.0 <= float(res.p_opt[3]) <= 1.0


def test_gl_matches_pseudo_voigt_at_equivalent_mix() -> None:
    from sersflow.core.preprocess.fitting_models import gl, pseudo_voigt

    x = np.linspace(400.0, 600.0, 500)
    # CasaXPS GL(30) <=> eta = 0.30
    y_gl = gl(x, 500.0, 100.0, 20.0, 30.0)
    y_pv = pseudo_voigt(x, 500.0, 100.0, 20.0, 0.30)
    assert np.allclose(y_gl, y_pv, rtol=1e-12, atol=1e-12)


def test_fit_single_gl_smoke() -> None:
    rng = np.random.default_rng(5)
    x = np.linspace(480.0, 560.0, 400)
    from sersflow.core.preprocess.fitting_models import gl

    y = gl(x, 520.0, 900.0, 14.0, 30.0)
    y = y + rng.normal(0.0, 2.0, size=y.shape)

    components = [FitComponent(component_type="gl", component_id="p1")]
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=components,
            p0=[518.0, 800.0, 16.0, 40.0],
            bounds_lower=[510.0, 0.0, 1e-6, 0.0],
            bounds_upper=[530.0, None, 50.0, 100.0],
        )
    )
    assert abs(float(res.p_opt[0]) - 520.0) < 1.5
    assert 0.0 <= float(res.p_opt[3]) <= 100.0


def test_fit_single_voigt_smoke() -> None:
    rng = np.random.default_rng(4)
    x = np.linspace(480.0, 560.0, 400)
    from sersflow.core.preprocess.fitting_models import voigt

    y = voigt(x, 520.0, 700.0, 8.0, 6.0)
    y = y + rng.normal(0.0, 2.0, size=y.shape)

    components = [FitComponent(component_type="voigt", component_id="p1")]
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=components,
            p0=[518.0, 600.0, 10.0, 8.0],
            bounds_lower=[510.0, 0.0, 1e-6, 1e-6],
            bounds_upper=[530.0, None, 40.0, 40.0],
        )
    )
    assert abs(float(res.p_opt[0]) - 520.0) < 2.0


def test_ds_alpha0_is_finite_and_symmetric_peak() -> None:
    from sersflow.core.preprocess.fitting_models import ds

    x = np.linspace(400.0, 600.0, 801)
    y = ds(x, 500.0, 100.0, 8.0, 0.0)
    assert abs(float(y[400]) - 100.0) < 1e-6  # center sample at 500
    assert np.all(np.isfinite(y))
    # Symmetric about center when alpha=0
    assert np.allclose(y[:400], y[401:][::-1], rtol=1e-5, atol=1e-5)


def test_fit_ds_smoke() -> None:
    rng = np.random.default_rng(6)
    x = np.linspace(480.0, 560.0, 400)
    from sersflow.core.preprocess.fitting_models import ds

    y = ds(x, 520.0, 800.0, 6.0, 0.15)
    y = y + rng.normal(0.0, 2.0, size=y.shape)
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[FitComponent(component_type="ds", component_id="p1")],
            p0=[518.0, 700.0, 8.0, 0.1],
            bounds_lower=[510.0, 0.0, 1e-6, 0.0],
            bounds_upper=[530.0, None, 40.0, 0.5],
        )
    )
    assert abs(float(res.p_opt[0]) - 520.0) < 3.0


def test_fit_la_smoke() -> None:
    rng = np.random.default_rng(7)
    x = np.linspace(480.0, 560.0, 400)
    from sersflow.core.preprocess.fitting_models import la

    y = la(x, 520.0, 900.0, 12.0, 2.0, 1.0, 0.0)
    assert abs(float(np.interp(520.0, x, y)) - 900.0) < 1e-6
    y = y + rng.normal(0.0, 2.0, size=y.shape)
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[FitComponent(component_type="la", component_id="p1")],
            p0=[520.0, 900.0, 12.0, 2.0, 1.0, 0.0],
            bounds_lower=[515.0, 0.0, 8.0, 1.5, 0.5, 0.0],
            bounds_upper=[525.0, None, 16.0, 2.5, 1.5, 1e-3],
        )
    )
    assert abs(float(res.p_opt[0]) - 520.0) < 2.0


def test_fit_apv_smoke() -> None:
    rng = np.random.default_rng(8)
    x = np.linspace(480.0, 560.0, 400)
    from sersflow.core.preprocess.fitting_models import apv

    y = apv(x, 520.0, 850.0, 8.0, 16.0, 0.2, 0.7)
    y = y + rng.normal(0.0, 2.0, size=y.shape)
    res = fit_curve(
        FitProblem(
            x=x,
            y=y,
            components=[FitComponent(component_type="apv", component_id="p1")],
            p0=[518.0, 800.0, 10.0, 14.0, 0.3, 0.6],
            bounds_lower=[510.0, 0.0, 1e-6, 1e-6, 0.0, 0.0],
            bounds_upper=[530.0, None, 40.0, 40.0, 1.0, 1.0],
        )
    )
    assert abs(float(res.p_opt[0]) - 520.0) < 2.0


def test_gds_alpha0_approaches_voigt_like() -> None:
    from sersflow.core.preprocess.fitting_models import gds

    x = np.linspace(450.0, 550.0, 500)
    y = gds(x, 500.0, 100.0, 5.0, 0.0, 2.0)
    assert np.all(np.isfinite(y))
    assert abs(float(np.max(y)) - 100.0) < 5.0  # near amp after scaling at pos

