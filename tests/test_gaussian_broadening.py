import numpy as np

from sersflow.core.preprocess.fitting import FitComponent, FitProblem, evaluate_fit_curves
from sersflow.core.preprocess.gaussian_broadening import FWHM_PER_SIGMA, broaden_curve


def _problem(g):
    x = np.linspace(525.0, 540.0, 601)
    comps = [FitComponent("gaussian", "p1")]
    return FitProblem(
        x=x, y=np.zeros_like(x), components=comps, p0=[532.0, 1.0, 1.0],
        bounds_lower=[None] * 3, bounds_upper=[None] * 3, technique_family="xps", gaussian_fwhm_eV=g,
    ), [532.0, 1.0, 1.0]


def test_broadening_adds_in_quadrature_and_keeps_area():
    p0, p = _problem(0.0)
    p1, _ = _problem(2.0)
    x = p0.x
    f0 = evaluate_fit_curves(p0, p).y_hat
    f1 = evaluate_fit_curves(p1, p).y_hat
    dx = x[1] - x[0]
    assert abs(f0.sum() * dx - f1.sum() * dx) / (f0.sum() * dx) < 1e-3
    half = x[f1 >= f1.max() / 2]
    fwhm = half.max() - half.min()
    assert abs(fwhm - np.hypot(1.0, 2.0)) < 0.06  # half-max read-off is quantised by the 0.025 eV data step


def test_zero_is_identity_and_curve_helper():
    x = np.linspace(0, 1, 11)
    assert np.allclose(broaden_curve(x, lambda g: g**2, 0.0), x**2)
    assert abs(FWHM_PER_SIGMA - 2.3548) < 1e-3
