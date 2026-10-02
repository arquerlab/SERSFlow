"""Analytical / approximate peak areas for height-parameterized XPS/vibrational models.

Fitting components use peak **height** (``amp``) as the free amplitude. Recipes often
specify relative **areas** (``area_pct``). Convert with::

    Area = amp * factor(shape, widths, …)
    amp_i / amp_0 = (Area_i / Area_0) * (factor_0 / factor_i)
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from sersflow.core.preprocess.fitting_models import _la0, la

_LN2 = math.log(2.0)
# Area = height * FWHM * k for unit-height G / L
_GAUSS_K = math.sqrt(math.pi / (4.0 * _LN2))  # ≈ 1.064467
_LORENTZ_K = math.pi / 2.0  # ≈ 1.570796
_SQRT_PI = math.sqrt(math.pi)


def gaussian_area_per_height(fwhm: float) -> float:
    return max(float(fwhm), 1e-12) * _GAUSS_K


def lorentzian_area_per_height(fwhm: float) -> float:
    return max(float(fwhm), 1e-12) * _LORENTZ_K


def gl_area_per_height(fwhm: float, m: float) -> float:
    """CasaXPS GL(m): linear mix of Lorentzian (m%) and Gaussian ((100-m)%)."""
    eta = max(0.0, min(100.0, float(m))) / 100.0
    w = max(float(fwhm), 1e-12)
    return w * (eta * _LORENTZ_K + (1.0 - eta) * _GAUSS_K)


def voigt_area_per_height(fwhm_g: float, fwhm_l: float) -> float:
    """
    Approximate Voigt area/height via the pseudo-Voigt mixing fraction.

    Uses the common linear approximation for the Lorentzian weight; accurate enough
    for relative multiplet amplitude links.
    """
    fg = max(float(fwhm_g), 0.0)
    fl = max(float(fwhm_l), 0.0)
    fwhm = fg + fl
    if fwhm <= 0:
        return 1e-12
    eta = fl / fwhm
    return fwhm * (eta * _LORENTZ_K + (1.0 - eta) * _GAUSS_K)


def _half_powered_lorentz_integral(p: float) -> float:
    """
    H(p) = ∫_0^∞ (1+u²)^{-p} du = (√π / 2) · Γ(p − ½) / Γ(p) for p > ½.
    """
    p = max(float(p), 0.5000001)
    # exp(lgamma(p-0.5) - lgamma(p)) * sqrt(pi)/2
    return 0.5 * _SQRT_PI * math.exp(math.lgamma(p - 0.5) - math.lgamma(p))


def la_area_per_height_analytical(
    fwhm: float,
    alpha: float,
    beta: float,
    fwhm_g: float = 0.0,
) -> float:
    """
    Closed-form / approx Area/amp for unit-height CasaXPS LA(α, β[, m]).

    With u = 2(x−pos)/FWHM, unit-height L^p halves integrate to H(p).
    α applies on high-BE (x ≥ pos), β on low-BE::

        F ≈ (FWHM / 2) · [H(α) + H(β)]

    When ``fwhm_g > 0``, use ``FWHM_eff = √(FWHM_L² + FWHM_G²)`` (common Voigt-like approx).
    """
    w = max(float(fwhm), 1e-12)
    fg = max(float(fwhm_g), 0.0)
    if fg > 0:
        w = math.sqrt(w * w + fg * fg)
    a = max(float(alpha), 0.5000001)
    b = max(float(beta), 0.5000001)
    return max((w / 2.0) * (_half_powered_lorentz_integral(a) + _half_powered_lorentz_integral(b)), 1e-12)


def la_area_per_height_numeric(
    fwhm: float,
    alpha: float,
    beta: float,
    fwhm_g: float = 0.0,
    *,
    n_points: int = 4096,
    pad_widths: float | None = None,
) -> float:
    """Numeric integrate unit-height LA (test oracle for the analytical form)."""
    w = max(float(fwhm), 1e-12)
    fg = max(float(fwhm_g), 0.0)
    pad = float(pad_widths) if pad_widths is not None else max(40.0 * w, 12.0 * fg, 20.0)
    x = np.linspace(-pad, pad, int(max(256, n_points)), dtype=float)
    if fg > 0:
        y = la(x, 0.0, 1.0, w, float(alpha), float(beta), fg)
    else:
        y = _la0(x, 0.0, w, float(alpha), float(beta))
        y0 = float(_la0(np.asarray([0.0]), 0.0, w, float(alpha), float(beta))[0])
        if y0 > 0:
            y = y / y0
    trap = getattr(np, "trapezoid", None) or np.trapz
    return max(float(trap(y, x)), 1e-12)


def la_area_per_height(
    fwhm: float,
    alpha: float,
    beta: float,
    fwhm_g: float = 0.0,
    **_kwargs: Any,
) -> float:
    """Default LA area factor: analytical Γ form (see ``la_area_per_height_analytical``)."""
    return la_area_per_height_analytical(fwhm, alpha, beta, fwhm_g)


def apv_area_per_height(fwhm_l: float, fwhm_r: float, eta_l: float, eta_r: float) -> float:
    """Split pseudo-Voigt: integrate left/right half analytically via GL factors / 2."""
    left = 0.5 * gl_area_per_height(fwhm_l, max(0.0, min(1.0, float(eta_l))) * 100.0)
    right = 0.5 * gl_area_per_height(fwhm_r, max(0.0, min(1.0, float(eta_r))) * 100.0)
    return max(left + right, 1e-12)


def a_gl_area_per_height(fwhm: float, m: float, a: float, n: float, m_asym: float = 0.0) -> float:
    """
    Approximate Area/amp for CasaXPS A(a,n,m_asym)GL(m).

    Maps to an effective LA-like / split-GL factor: stretch high-BE FWHM by ``(1+a)``
    and mix with GL(m); optional ``m_asym`` adds Gaussian width like LA ``m``.
    """
    w = max(float(fwhm), 1e-12)
    a = max(float(a), 0.0)
    w_high = w * (1.0 + a)
    w_low = w * (1.0 + 0.5 * max(float(n), 0.0))  # mild low-side sensitivity to n
    # Average of GL areas on each half
    f = 0.5 * gl_area_per_height(w_low, m) + 0.5 * gl_area_per_height(w_high, m)
    fg = casaxps_la_m_to_fwhm_g(m_asym, w) if float(m_asym) > 0 else 0.0
    if fg > 0:
        # Inflate effective width slightly when asymmetric Gaussian convolution is present
        f *= math.sqrt(1.0 + (fg / w) ** 2)
    return max(f, 1e-12)


def area_per_height(
    component_type: str,
    values: dict[str, Any],
) -> float:
    """
    Return Area/amp for a component given its parameter seed dict.

    Falls back to a Gaussian approximation on unknown shapes.
    """
    ct = str(component_type or "").strip().lower()
    fwhm = float(values.get("fwhm") or 1.0)
    if ct in ("gaussian", "g"):
        return gaussian_area_per_height(fwhm)
    if ct in ("lorentzian", "l"):
        return lorentzian_area_per_height(fwhm)
    if ct == "gl":
        return gl_area_per_height(fwhm, float(values.get("m") or 30.0))
    if ct == "pseudo_voigt":
        eta = float(values.get("eta") or 0.3)
        return gl_area_per_height(fwhm, eta * 100.0)
    if ct == "voigt":
        return voigt_area_per_height(
            float(values.get("fwhm_g") or fwhm),
            float(values.get("fwhm_l") or 0.0),
        )
    if ct == "la":
        return la_area_per_height(
            fwhm,
            float(values.get("alpha") or 1.0),
            float(values.get("beta") or 1.0),
            float(values.get("fwhm_g") or 0.0),
        )
    if ct == "lf":
        return la_area_per_height(
            fwhm,
            float(values.get("alpha") or 1.0),
            float(values.get("beta") or 1.0),
            float(values.get("fwhm_g") or 0.0),
        )
    if ct in ("a_gl", "agl"):
        return a_gl_area_per_height(
            fwhm,
            float(values.get("m") or 30.0),
            float(values.get("a") or 0.4),
            float(values.get("n") or 0.55),
            float(values.get("m_asym") or 0.0),
        )
    if ct == "apv":
        return apv_area_per_height(
            float(values.get("fwhm_l") or fwhm),
            float(values.get("fwhm_r") or fwhm),
            float(values.get("eta_l") or 0.3),
            float(values.get("eta_r") or 0.3),
        )
    if ct == "asymmetric_voigt":
        left = voigt_area_per_height(
            float(values.get("fwhm_g_l") or fwhm),
            float(values.get("fwhm_l_l") or 0.0),
        )
        right = voigt_area_per_height(
            float(values.get("fwhm_g_r") or fwhm),
            float(values.get("fwhm_l_r") or 0.0),
        )
        return 0.5 * (left + right)
    if ct in ("ds", "gds"):
        gamma = float(values.get("gamma") or fwhm)
        return lorentzian_area_per_height(max(2.0 * gamma, 1e-12))
    return gaussian_area_per_height(fwhm)


def height_scale_for_area_ratio(
    *,
    area_i: float,
    area_0: float,
    factor_i: float,
    factor_0: float,
) -> float:
    """amp_i = amp_0 * scale, with Areas proportional to area_pct."""
    a0 = max(float(area_0), 1e-12)
    f_i = max(float(factor_i), 1e-12)
    f_0 = max(float(factor_0), 1e-12)
    return (float(area_i) / a0) * (f_0 / f_i)


def casaxps_la_m_to_fwhm_g(m: float, fwhm_l: float) -> float:
    """
    Map CasaXPS LA(α, β, m) integer ``m`` to Gaussian FWHM (eV).

    CasaXPS ``m`` is a convolution-width index, **not** eV. Treat it on a
    percent-like scale relative to the Lorentzian FWHM (common practical mapping)::

        fwhm_g = fwhm_L * (m / 100)

    so LA(…, 10) with FWHM 1 eV → 0.1 eV Gaussian seed, not a 10 eV blob.
    """
    m = max(0.0, float(m))
    return max(0.0, max(float(fwhm_l), 0.0) * (m / 100.0))
