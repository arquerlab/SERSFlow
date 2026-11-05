"""Peak and background model functions for nonlinear fitting.

Amplitude parameters are peak heights at the characteristic center (`pos`),
not areas (except where noted for DS/GDS: value at `pos` after scaling).

Asymmetric XPS-style models (DS, GDS, LA, LF, APV, asymmetric Voigt) use the
same x-axis units as the spectrum (e.g. Raman shift). For DS, the arctangent
sign follows the standard higher-binding-energy tail convention with
arctan((pos - x) / gamma); flip your axis or reinterpret asymmetry if your
energy convention differs.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy.signal import fftconvolve
from scipy.special import erfcx, voigt_profile

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
    """Linear mix of Lorentzian (eta) and Gaussian (1 - eta) with shared FWHM.

    eta is a fraction in [0, 1]. This is not the same parameterization as CasaXPS GL(m).
    """
    pos = params[0]
    amp = params[1]
    fwhm = params[2]
    eta = params[3]
    g = gaussian(x, pos, amp, fwhm)
    lor = lorentzian(x, pos, amp, fwhm)
    return eta * lor + (1.0 - eta) * g


def sgl(x, *params):
    """
    CasaXPS SGL(m): Gaussian–Lorentzian SUM form (CasaXPS Cookbook 2026 p.67).

    SGL(x) = (m/100) * L(x) + (1 - m/100) * G(x)
    with shared center and FWHM; m is percent Lorentzian in [0, 100].
    This was SpecFlow's ``gl`` before the K1 change (pipeline schema v2); stored
    pipelines were migrated from ``gl`` to ``sgl`` so their results are unchanged.
    """
    pos = params[0]
    amp = params[1]
    fwhm = params[2]
    m = params[3]
    return pseudo_voigt(x, pos, amp, fwhm, float(m) / 100.0)


def _gl_p(m: float) -> float:
    """Lorentzian fraction p = m/100 clipped to [0, 1]."""
    return min(max(float(m), 0.0), 100.0) / 100.0


@lru_cache(maxsize=4096)
def _gl_product_fwhm_scale_cached(p: float) -> float:
    # Half maximum of exp(-ln2 (1-p) t) / (1 + p t) with t = 4 u^2, u = x / F:
    #   f(t) = ln2 - ln2 (1-p) t - ln(1 + p t) = 0,  f(0) = ln2 > 0,  f(1) = p ln2 - ln(1+p) <= 0.
    # f is strictly decreasing on [0, 1]; FWHM / F = sqrt(t*).
    if p <= 0.0 or p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        f = math.log(2.0) - math.log(2.0) * (1.0 - p) * mid - math.log1p(p * mid)
        if f > 0.0:
            lo = mid
        else:
            hi = mid
    return math.sqrt(0.5 * (lo + hi))


def gl_product_fwhm_scale(m: float) -> float:
    """
    True FWHM of the CasaXPS product GL(m) in units of its width parameter F.

    1.0 at m = 0 and m = 100, slightly below 1 in between.
    """
    return _gl_product_fwhm_scale_cached(round(_gl_p(m), 12))


@lru_cache(maxsize=4096)
def _gl_product_area_k_cached(p: float) -> float:
    s = _gl_product_fwhm_scale_cached(p)
    if p <= 0.0:
        integral_f1 = math.sqrt(math.pi / (4.0 * math.log(2.0)))  # Gaussian, F = 1
    elif p >= 1.0:
        integral_f1 = math.pi / 2.0  # Lorentzian, F = 1
    else:
        # ∫ exp(-a u²) / (1 + b u²) du = (π / √b) · erfcx(√(a/b)),  a = 4 ln2 (1-p), b = 4p.
        a = 4.0 * math.log(2.0) * (1.0 - p)
        b = 4.0 * p
        integral_f1 = math.pi / math.sqrt(b) * float(erfcx(math.sqrt(a / b)))
    return integral_f1 / s


def gl_product_area_k(m: float) -> float:
    """Area / (height · true FWHM) of the CasaXPS product GL(m) (closed form via erfcx)."""
    return _gl_product_area_k_cached(round(_gl_p(m), 12))


def _unit_height_gl_product(dx: np.ndarray, fwhm: float, m: float) -> np.ndarray:
    """Unit-height CasaXPS product GL(m) whose TRUE full width at half maximum is ``fwhm``."""
    p = _gl_p(m)
    f_param = max(float(fwhm), 1e-12) / gl_product_fwhm_scale(m)
    u2 = np.power(np.asarray(dx, dtype=float) / f_param, 2)
    return np.exp(-4.0 * _LN2 * (1.0 - p) * u2) / (1.0 + 4.0 * p * u2)


def gl(x, *params):
    """
    CasaXPS GL(m): Gaussian–Lorentzian PRODUCT form (CasaXPS Cookbook 2026 p.67).

        GL(x, m) = exp(-(1 - m/100) 4 ln2 u²) / (1 + 4 (m/100) u²),   u = (x - pos) / F

    m is percent Lorentzian in [0, 100] (GL(30): m = 30). ``fwhm`` is the TRUE full width at half
    maximum (as Biesinger and the CasaXPS component table report it); F is derived from it, so
    F = fwhm / gl_product_fwhm_scale(m). ``amp`` is the peak height.
    """
    pos = float(params[0])
    amp = float(params[1])
    fwhm = float(params[2])
    m = float(params[3])
    return amp * _unit_height_gl_product(_as_1d(x) - pos, fwhm, m)


def gl_gauss(x, *params):
    """
    CasaXPS GL(m, n) = GL(x, m) ⊗ G(n): product GL convolved with a Gaussian (Cookbook p.67).

    Params: pos, amp, fwhm, m, fwhm_g. ``fwhm`` is the true FWHM of the GL(m) core (before
    convolution); ``fwhm_g`` is the FWHM of the convolving Gaussian in energy units (0 = plain
    GL(m)), the same convention as LA/LF. ``amp`` is the height of the convolved profile at pos.
    """
    pos = float(params[0])
    amp = float(params[1])
    fwhm = max(float(params[2]), 1e-12)
    m = float(params[3])
    fwhm_g = max(float(params[4]) if len(params) > 4 else 0.0, 0.0)
    xf = _as_1d(x)
    if fwhm_g <= 0:
        return amp * _unit_height_gl_product(xf - pos, fwhm, m)
    return amp * _unit_height_gl_gauss(xf - pos, fwhm, m, fwhm_g)


def _unit_height_gl_gauss(dx: np.ndarray, fwhm: float, m: float, fwhm_g: float) -> np.ndarray:
    """
    Unit-height GL(m) ⊗ G(fwhm_g) evaluated on a local grid centred on the peak.

    The grid step follows the narrowest width (not the spectrum's x range), so the shape is the same
    whatever x range the caller asks for. Far outside the grid the convolution is negligible and the
    GL(m) core (rescaled to the same height normalisation) is used.
    """
    sigma = fwhm_g * _GAUSS_FWHM_TO_SIGMA
    half = max(30.0 * fwhm, 10.0 * fwhm_g)
    step = min(fwhm, fwhm_g) / 40.0
    n_half = int(min(max(half / step, 256), 1 << 15))
    step = half / n_half
    grid = np.arange(-n_half, n_half + 1, dtype=float) * step
    core = _unit_height_gl_product(grid, fwhm, m)
    k = np.arange(-int(np.ceil(6 * sigma / step)), int(np.ceil(6 * sigma / step)) + 1, dtype=float) * step
    kern = np.exp(-0.5 * (k / sigma) ** 2)
    kern /= kern.sum()
    conv = fftconvolve(core, kern, mode="same")
    peak = float(conv[n_half])
    if not np.isfinite(peak) or peak <= 0:
        return np.zeros_like(np.asarray(dx, dtype=float))
    dxf = np.asarray(dx, dtype=float)
    out = _unit_height_gl_product(dxf, fwhm, m)  # outside the grid: unconvolved core
    inside = np.abs(dxf) <= half
    if np.any(inside):
        out = out.copy()
        out[inside] = np.interp(dxf[inside], grid, conv)
    return out / peak


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


# ---------------------------------------------------------------------------
# Helpers for asymmetric / convolved models
# ---------------------------------------------------------------------------


def _as_1d(x) -> np.ndarray:
    return np.asarray(x, dtype=float).ravel()


def _clip_alpha(alpha: float) -> float:
    a = float(alpha)
    if not np.isfinite(a):
        return 0.0
    return float(np.clip(a, 0.0, 0.999))


def _unit_height_pseudo_voigt(dx: np.ndarray, fwhm: float, eta: float) -> np.ndarray:
    fwhm = max(float(fwhm), 1e-12)
    eta = float(np.clip(eta, 0.0, 1.0))
    g = np.exp(-(dx * dx) / (fwhm * fwhm / 4.0 / _LN2))
    lor = 1.0 / (1.0 + 4.0 * np.power(dx / fwhm, 2))
    return eta * lor + (1.0 - eta) * g


def _unit_height_voigt(dx: np.ndarray, fwhm_g: float, fwhm_l: float) -> np.ndarray:
    sigma = max(float(fwhm_g), 1e-12) * _GAUSS_FWHM_TO_SIGMA
    gamma = max(float(fwhm_l), 0.0) * 0.5
    y0 = float(voigt_profile(0.0, sigma, gamma))
    if not np.isfinite(y0) or y0 <= 0.0:
        return np.zeros_like(dx, dtype=float)
    return voigt_profile(dx, sigma, gamma) / y0


def _ds_kernel(x: np.ndarray, pos: float, gamma: float, alpha: float) -> np.ndarray:
    """Unnormalized Doniach–Šunjić lineshape (prefactor A = 1)."""
    gamma = max(float(gamma), 1e-12)
    alpha = _clip_alpha(alpha)
    dx = x - pos
    num = np.cos(np.pi * alpha / 2.0 + (1.0 - alpha) * np.arctan((pos - x) / gamma))
    den = np.power(dx * dx + gamma * gamma, (1.0 - alpha) / 2.0)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = num / den
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _scale_at_pos(y: np.ndarray, x: np.ndarray, pos: float, amp: float) -> np.ndarray:
    """Scale so the profile equals ``amp`` at ``pos`` (interpolated if needed)."""
    xf = np.asarray(x, dtype=float).ravel()
    yf = np.asarray(y, dtype=float).ravel()
    if xf.size == 0:
        return yf
    order = np.argsort(xf)
    y_at = float(np.interp(pos, xf[order], yf[order]))
    if not np.isfinite(y_at) or abs(y_at) < 1e-30:
        return np.zeros_like(yf)
    return amp * yf / y_at


def _gaussian_kernel_1d(dx: float, sigma: float, n_sigma: float = 6.0) -> np.ndarray:
    sigma = max(float(sigma), 1e-12)
    dx = abs(float(dx))
    if dx <= 0:
        return np.array([1.0], dtype=float)
    half = max(1, int(np.ceil(n_sigma * sigma / dx)))
    t = np.arange(-half, half + 1, dtype=float) * dx
    g = np.exp(-0.5 * (t / sigma) ** 2)
    s = float(g.sum())
    if s <= 0:
        return np.array([1.0], dtype=float)
    return g / s


def _fft_convolve_gaussian(xu: np.ndarray, yu: np.ndarray, sigma: float) -> np.ndarray:
    if sigma is None or not np.isfinite(sigma) or float(sigma) <= 0.0:
        return yu
    if xu.size < 2:
        return yu
    dx = float(xu[1] - xu[0])
    if dx <= 0:
        return yu
    kern = _gaussian_kernel_1d(dx, float(sigma))
    return fftconvolve(yu, kern, mode="same")


def _padded_uniform_grid(x: np.ndarray, *, pad_widths: float, n_points: int) -> np.ndarray:
    xmin = float(np.min(x))
    xmax = float(np.max(x))
    span = max(xmax - xmin, 1e-6)
    pad = max(float(pad_widths), span * 0.5)
    n = max(int(n_points), 256)
    return np.linspace(xmin - pad, xmax + pad, n)


def _eval_convolved_on_x(
    x: np.ndarray,
    y_on_grid,
    *,
    sigma: float,
    pad_widths: float,
    n_points: int = 1024,
) -> np.ndarray:
    """
    Evaluate ``y_on_grid(xu)``, optionally Gaussian-convolve on a padded uniform
    grid, then interpolate back to ``x``.
    """
    xf = _as_1d(x)
    if xf.size == 0:
        return xf
    span = float(np.max(xf) - np.min(xf))
    pad = max(pad_widths, 6.0 * max(float(sigma), 0.0) + span)
    xu = _padded_uniform_grid(xf, pad_widths=pad, n_points=n_points)
    yu = np.asarray(y_on_grid(xu), dtype=float)
    yu = _fft_convolve_gaussian(xu, yu, sigma)
    order = np.argsort(xu)
    return np.interp(xf, xu[order], yu[order])


def _unit_lorentzian(x: np.ndarray, pos: float, fwhm: float) -> np.ndarray:
    fwhm = max(float(fwhm), 1e-12)
    return 1.0 / (1.0 + 4.0 * np.power((x - pos) / fwhm, 2))


def _la0(x: np.ndarray, pos: float, fwhm: float, alpha: float, beta: float) -> np.ndarray:
    """
    CasaXPS LA(α, β) core on a binding-energy axis (larger x = higher BE).

    α applies on the **high-BE** side (``x >= pos``); β on the **low-BE** side
    (``x < pos``). Smaller exponent ⇒ longer tail.
    """
    L = np.clip(_unit_lorentzian(x, pos, fwhm), 0.0, None)
    alpha = max(float(alpha), 1e-6)
    beta = max(float(beta), 1e-6)
    high_be = x >= pos
    out = np.empty_like(L)
    out[high_be] = np.power(L[high_be], alpha)
    out[~high_be] = np.power(L[~high_be], beta)
    return out


LF_EXPONENT_LIMIT = 3.0  # a_s: far-tail exponent of the finite Lorentzian


def _lf0(
    x: np.ndarray,
    pos: float,
    fwhm: float,
    alpha: float,
    beta: float,
    w: float,
    *,
    p_lim: float = LF_EXPONENT_LIMIT,
) -> np.ndarray:
    """
    Finite asymmetric Lorentzian core (CasaXPS LF without the Gaussian).

    ``L(x)^p(x)`` with a distance-dependent exponent that rises from alpha/beta at
    the centre to ``p_lim`` (= 3) far away, which makes the area finite::

        p(x) = p_lim - (p_lim - a) / (1 + 4 ((x - pos) / w)^2),   a = alpha | beta

    ``w`` is in the energy units of ``x`` (Lorentzian-shaped envelope, as in the
    published LF definition, e.g. Avval et al. / Appendix B of arXiv:2608.09041).
    CasaXPS BE convention: α on high BE (``x >= pos``), β on low BE.
    """
    L = np.clip(_unit_lorentzian(x, pos, fwhm), 1e-300, None)
    alpha = max(float(alpha), 1e-6)
    beta = max(float(beta), 1e-6)
    w = max(float(w), 1e-12)
    p_lim = float(p_lim)
    env = 1.0 / (1.0 + 4.0 * np.power((x - pos) / w, 2))
    p = np.where(x >= pos, p_lim - (p_lim - alpha) * env, p_lim - (p_lim - beta) * env)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = np.power(L, p)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


# ---------------------------------------------------------------------------
# Asymmetric peak models
# ---------------------------------------------------------------------------


def ds(x, *params):
    """
    Doniach–Šunjić (physically motivated metallic core-level asymmetry).

    Params: pos (E0), amp (height at pos), gamma (intrinsic width), alpha in [0, 1).

    When alpha=0 this is a Lorentzian-like profile (up to normalization).
    For alpha > 0 the ideal DS tail has infinite integrated area — do not use
    for quantitative area analysis without a justified cutoff.
    """
    pos = float(params[0])
    amp = float(params[1])
    gamma = float(params[2])
    alpha = float(params[3])
    xf = _as_1d(x)
    raw = _ds_kernel(xf, pos, gamma, alpha)
    return _scale_at_pos(raw, xf, pos, amp)


def gds(x, *params):
    """
    Gaussian-convoluted Doniach–Šunjić (DS ⊗ G).

    Params: pos, amp, gamma, alpha, sigma (Gaussian std. deviation).

    When alpha=0 the result is a Voigt-like profile. Convolution uses FFT on a
    padded uniform grid. Infinite-area caveat of DS remains for alpha > 0.
    """
    pos = float(params[0])
    amp = float(params[1])
    gamma = float(params[2])
    alpha = float(params[3])
    sigma = float(params[4])
    xf = _as_1d(x)
    pad = max(40.0 * max(gamma, 1e-6), 8.0 * max(sigma, 0.0))

    def y_on_grid(xu: np.ndarray) -> np.ndarray:
        return _ds_kernel(xu, pos, gamma, alpha)

    yu = _eval_convolved_on_x(xf, y_on_grid, sigma=sigma, pad_widths=pad, n_points=2048)
    return _scale_at_pos(yu, xf, pos, amp)


def la(x, *params):
    """
    Asymmetric Lorentzian (LA), CasaXPS-style LA(alpha, beta) with optional Gaussian.

    Params: pos, amp, fwhm, alpha, beta, fwhm_g

    On a binding-energy axis (larger x = higher BE):
    LA0 = L^alpha (x >= pos, high BE), L^beta (x < pos, low BE).
    Smaller exponent => longer tail. ``fwhm_g`` is Gaussian FWHM in the same
    energy units (0 disables convolution). CasaXPS integer ``m`` must be mapped
    separately (see ``peak_area.casaxps_la_m_to_fwhm_g``).
    """
    pos = float(params[0])
    amp = float(params[1])
    fwhm = float(params[2])
    alpha = float(params[3])
    beta = float(params[4])
    fwhm_g = float(params[5]) if len(params) > 5 else 0.0
    sigma = max(fwhm_g, 0.0) * _GAUSS_FWHM_TO_SIGMA
    xf = _as_1d(x)
    pad = max(30.0 * max(fwhm, 1e-6), 8.0 * sigma)

    def y_on_grid(xu: np.ndarray) -> np.ndarray:
        return _la0(xu, pos, fwhm, alpha, beta)

    if sigma > 0:
        yu = _eval_convolved_on_x(xf, y_on_grid, sigma=sigma, pad_widths=pad, n_points=2048)
    else:
        yu = _la0(xf, pos, fwhm, alpha, beta)
    return _scale_at_pos(yu, xf, pos, amp)


def lf(x, *params):
    """
    Finite Lorentzian (LF) — LA with damped distant tails.

    Params: pos, amp, fwhm, alpha, beta, w, fwhm_g

    Exponents rise from alpha/beta at the centre to 3 in the far tails with a
    Lorentzian envelope of width ``w`` (same units as ``x``); see ``_lf0``. The
    Gaussian width ``fwhm_g`` is in energy units; the CasaXPS integer ``m`` index
    is not translated (its eV scale is not documented).
    """
    pos = float(params[0])
    amp = float(params[1])
    fwhm = float(params[2])
    alpha = float(params[3])
    beta = float(params[4])
    w = float(params[5])
    fwhm_g = float(params[6]) if len(params) > 6 else 0.0
    sigma = max(fwhm_g, 0.0) * _GAUSS_FWHM_TO_SIGMA
    xf = _as_1d(x)
    pad = max(30.0 * max(fwhm, 1e-6), 8.0 * sigma)

    def y_on_grid(xu: np.ndarray) -> np.ndarray:
        return _lf0(xu, pos, fwhm, alpha, beta, w)

    if sigma > 0:
        yu = _eval_convolved_on_x(xf, y_on_grid, sigma=sigma, pad_widths=pad, n_points=2048)
    else:
        yu = _lf0(xf, pos, fwhm, alpha, beta, w)
    return _scale_at_pos(yu, xf, pos, amp)


def apv(x, *params):
    """
    Asymmetric (split) pseudo-Voigt / asymmetric Gaussian–Lorentzian.

    Params: pos, amp, fwhm_l, fwhm_r, eta_l, eta_r

    Different FWHM and Lorentzian fraction on each side of ``pos``. Both
    branches are peak-height normalized so the profile is continuous at ``pos``.
    """
    pos = float(params[0])
    amp = float(params[1])
    fwhm_l = float(params[2])
    fwhm_r = float(params[3])
    eta_l = float(params[4])
    eta_r = float(params[5])
    xf = _as_1d(x)
    left = xf < pos
    out = np.empty_like(xf)
    if np.any(left):
        out[left] = _unit_height_pseudo_voigt(xf[left] - pos, fwhm_l, eta_l)
    if np.any(~left):
        out[~left] = _unit_height_pseudo_voigt(xf[~left] - pos, fwhm_r, eta_r)
    return amp * out


def a_gl(x, *params):
    """
    CasaXPS-style asymmetric GL: A(a, n, m_asym)GL(m) on the PRODUCT GL(m) base (K1).

    Same parameters and asymmetry approximation as :func:`a_sgl`; only the base line shape is the
    CasaXPS product GL(m) (true FWHM) instead of the sum form.
    """
    return _a_gl_impl(x, params, _unit_height_gl_product)


def a_sgl(x, *params):
    """
    Legacy asymmetric GL on the SUM base: A(a, n, m_asym)SGL(m).

    Params: pos, amp, fwhm, m, a, n, m_asym

    Approximate model used for Biesinger/CasaXPS legacy metal packs (SpecFlow ``a_gl`` before K1):
    - Base shape is SGL(m) (percent Lorentzian, sum form).
    - High-BE side (``x >= pos``) uses a stretched FWHM ``fwhm*(1+a)``.
    - Low-BE side uses mild stretch from ``n``: ``fwhm*(1+0.5*n)``.
    - Optional Gaussian convolution width from CasaXPS ``m_asym`` via
      ``fwhm_g = fwhm * m_asym/100`` (same mapping as LA ``m``).
    """
    return _a_gl_impl(x, params, lambda dx, fwhm, m: _unit_height_pseudo_voigt(dx, fwhm, _gl_p(m)))


def _a_gl_impl(x, params, unit_fn) -> np.ndarray:
    """Shared A(a, n, m_asym) asymmetry on a unit-height base ``unit_fn(dx, fwhm, m)``."""
    pos = float(params[0])
    amp = float(params[1])
    fwhm = max(float(params[2]), 1e-12)
    m = float(params[3])
    a = max(float(params[4]), 0.0)
    n = max(float(params[5]), 0.0)
    m_asym = max(float(params[6]) if len(params) > 6 else 0.0, 0.0)
    fwhm_low = fwhm * (1.0 + 0.5 * n)
    fwhm_high = fwhm * (1.0 + a)
    xf = _as_1d(x)
    high = xf >= pos
    out = np.empty_like(xf)
    if np.any(~high):
        out[~high] = unit_fn(xf[~high] - pos, fwhm_low, m)
    if np.any(high):
        out[high] = unit_fn(xf[high] - pos, fwhm_high, m)
    fwhm_g = fwhm * (m_asym / 100.0)
    sigma = max(fwhm_g, 0.0) * _GAUSS_FWHM_TO_SIGMA
    if sigma > 0:
        pad = max(30.0 * fwhm_high, 8.0 * sigma)

        def y_on_grid(xu: np.ndarray) -> np.ndarray:
            hh = xu >= pos
            yy = np.empty_like(xu)
            if np.any(~hh):
                yy[~hh] = unit_fn(xu[~hh] - pos, fwhm_low, m)
            if np.any(hh):
                yy[hh] = unit_fn(xu[hh] - pos, fwhm_high, m)
            return yy

        out = _eval_convolved_on_x(xf, y_on_grid, sigma=sigma, pad_widths=pad, n_points=2048)
    return _scale_at_pos(out, xf, pos, amp)


def asymmetric_voigt(x, *params):
    """
    Asymmetric (split) Voigt — empirical piecewise model.

    Params: pos, amp, fwhm_g_l, fwhm_l_l, fwhm_g_r, fwhm_l_r

    Different Gaussian/Lorentzian FWHM on each side; unit-height branches meet
    at ``pos``. Not a single physical Voigt convolution.
    """
    pos = float(params[0])
    amp = float(params[1])
    fwhm_g_l = float(params[2])
    fwhm_l_l = float(params[3])
    fwhm_g_r = float(params[4])
    fwhm_l_r = float(params[5])
    xf = _as_1d(x)
    left = xf < pos
    out = np.empty_like(xf)
    if np.any(left):
        out[left] = _unit_height_voigt(xf[left] - pos, fwhm_g_l, fwhm_l_l)
    if np.any(~left):
        out[~left] = _unit_height_voigt(xf[~left] - pos, fwhm_g_r, fwhm_l_r)
    return amp * out


def polynomial_background(x, *params):
    return np.polyval(params, x)


def combined_models(*models):
    return sum(models)
