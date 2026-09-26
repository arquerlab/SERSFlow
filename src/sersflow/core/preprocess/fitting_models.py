"""Peak and background model functions for nonlinear fitting.

Amplitude parameters are peak heights (intensity at the center), not areas.
"""

from __future__ import annotations

import numpy as np
from scipy.special import voigt_profile


_LN2 = np.log(2.0)
_GAUSS_FWHM_TO_SIGMA = 1.0 / (2.0 * np.sqrt(2.0 * _LN2))


def gaussian(x, *params):
    pos = params[0]
    amp = params[1]
    fwhm = params[2]
    return amp * np.exp(-(np.power(x - pos, 2) / (fwhm * fwhm / 4.0 / _LN2)))


def lorentzian(x, *params):
    pos = params[0]
    amp = params[1]
    fwhm = params[2]
    return amp / (1.0 + 4.0 * np.power((x - pos) / fwhm, 2))


def pseudo_voigt(x, *params):
    """Linear mix of Lorentzian (eta) and Gaussian (1 - eta) with shared FWHM."""
    pos = params[0]
    amp = params[1]
    fwhm = params[2]
    eta = params[3]
    g = gaussian(x, pos, amp, fwhm)
    lor = lorentzian(x, pos, amp, fwhm)
    return eta * lor + (1.0 - eta) * g


def voigt(x, *params):
    """
    True Voigt profile with peak-height amplitude.

    fwhm_g / fwhm_l are the Gaussian and Lorentzian FWHM contributions.
    """
    pos = params[0]
    amp = params[1]
    fwhm_g = params[2]
    fwhm_l = params[3]
    sigma = max(float(fwhm_g), 1e-12) * _GAUSS_FWHM_TO_SIGMA
    gamma = max(float(fwhm_l), 0.0) * 0.5
    y0 = float(voigt_profile(0.0, sigma, gamma))
    if not np.isfinite(y0) or y0 <= 0.0:
        return np.zeros_like(np.asarray(x, dtype=float), dtype=float)
    return amp * voigt_profile(np.asarray(x, dtype=float) - pos, sigma, gamma) / y0


def polynomial_background(x, *params):
    return np.polyval(params, x)


def combined_models(*models):
    return sum(models)
