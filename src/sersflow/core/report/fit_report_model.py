"""
Pure helpers for the publication fit report (R1): line-shape strings, parameter status, constraint text, checklist.

The report items follow the CasaXPS gap analysis R1 list (ISO 19830 clauses 5 and 10 as summarised there; MAJOR et
al. 2020 section J): provenance, acquisition, charge correction, processing history, per-region background and
components with line shape, values with uncertainties and constraint status, fit statistics, quantification and a
figure.
"""

from __future__ import annotations

import math
from typing import Any

REPORT_SCHEMA = "specflow-fit-report/1"


def _f(v: Any, nd: int = 3) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "?"
    if not math.isfinite(x):
        return "?"
    return f"{x:.{nd}g}" if abs(x) >= 1e4 or (x != 0 and abs(x) < 1e-3) else f"{x:.{nd}f}".rstrip("0").rstrip(".")


def casaxps_lineshape(component_type: str, p: dict[str, float]) -> str:
    """
    Line shape in CasaXPS notation where an exact equivalent exists; otherwise a plain description.

    GL(m) = product Gaussian-Lorentzian (K1), SGL(m) = sum form, gaussian = GL(0), lorentzian = GL(100).
    """
    ct = str(component_type or "").strip().lower()
    m = p.get("m")
    if ct == "gl":
        return f"GL({_f(m, 1)})"
    if ct == "sgl":
        return f"SGL({_f(m, 1)})"
    if ct == "gaussian":
        return "GL(0)"
    if ct == "lorentzian":
        return "GL(100)"
    if ct == "pseudo_voigt":
        eta = p.get("eta")
        return f"SGL({_f(100.0 * float(eta), 1)})" if eta is not None else "SGL(?)"
    if ct == "gl_gauss":
        return f"GL({_f(m, 1)}) convolved with Gaussian FWHM {_f(p.get('fwhm_g'))} eV"
    if ct == "la":
        fg = p.get("fwhm_g")
        base = f"LA({_f(p.get('alpha'), 2)},{_f(p.get('beta'), 2)})"
        return base + (f" convolved with Gaussian FWHM {_f(fg)} eV" if fg else "")
    if ct == "lf":
        fg = p.get("fwhm_g")
        base = f"LF({_f(p.get('alpha'), 2)},{_f(p.get('beta'), 2)},{_f(p.get('w'), 3)})"
        return base + (f" convolved with Gaussian FWHM {_f(fg)} eV" if fg else "") + " (SpecFlow LF; w in eV)"
    if ct in ("a_gl", "a_sgl"):
        form = "GL" if ct == "a_gl" else "SGL"
        return f"A({_f(p.get('a'), 2)},{_f(p.get('n'), 2)},{_f(p.get('m_asym'), 1)}){form}({_f(m, 1)})"
    if ct == "voigt":
        return f"Voigt (Gaussian FWHM {_f(p.get('fwhm_g'))} eV, Lorentzian FWHM {_f(p.get('fwhm_l'))} eV)"
    if ct == "ds":
        return f"DS({_f(p.get('alpha'), 3)}) (Doniach-Sunjic)"
    if ct == "gds":
        return f"Gaussian-convolved DS({_f(p.get('alpha'), 3)})"
    if ct == "apv":
        return "asymmetric pseudo-Voigt (APV)"
    if ct == "asymmetric_voigt":
        return "asymmetric Voigt"
    if ct == "shirley_bg":
        return "Shirley (active, fitted)"
    if ct == "tougaard_bg":
        return "Tougaard (active, fitted)"
    if ct == "slope_bg":
        return "slope background (active)"
    if ct == "polynomial_background":
        return "polynomial background"
    if ct == "erfc_step_bg":
        return "erfc step (Step/Edge background, fitted)"
    if ct == "linear_bg":
        return "linear background (endpoints)"
    if ct == "tougaard_u4_bg":
        return (
            f"Tougaard (B {_f(p.get('B'), 4)}, C {_f(p.get('C'), 4)}, C' {_f(p.get('C_d'), 2)}, "
            f"D {_f(p.get('D'), 4)}, T0 {_f(p.get('T0'), 3)} eV)"
        )
    if ct == "shirley_of_bg":
        return "SB(0): Shirley profile of a peak (fitted)"
    if ct == "reference_spectrum":
        return "measured reference spectrum (unit area)"
    return ct or "?"


def link_relation_text(link: dict[str, Any]) -> str:
    """Human-readable relation of a ``param_links`` entry (the dependent parameter is implied)."""
    mode = str(link.get("mode") or "equal").strip().lower()
    tgt = f"{link.get('target_component_id')}.{link.get('target_key')}"
    if mode == "equal":
        return f"= {tgt}"
    if mode == "scale":
        return f"= {_f(link.get('scale'), 4)} x {tgt}"
    if mode == "offset":
        off = float(link.get("offset") or 0.0)
        return f"= {tgt} {'+' if off >= 0 else '-'} {_f(abs(off), 4)}"
    if mode == "area_ratio":
        return f"area = {_f(link.get('ratio'), 4)} x area({link.get('target_component_id')})"
    if mode == "expr":
        lhs = "area = " if str(link.get("defines") or "") == "area" else "= "
        return lhs + str(link.get("expr") or "")
    return mode


def parameter_status(
    *,
    vary: bool,
    lower: float | None,
    upper: float | None,
    link: dict[str, Any] | None,
) -> dict[str, Any]:
    """``{"status": fixed | bounded | free | linked, "bounds": [lo, hi] | None, "relation": str | None}``."""
    if link is not None:
        return {"status": "linked", "bounds": None, "relation": link_relation_text(link)}
    if not vary:
        return {"status": "fixed", "bounds": None, "relation": None}
    lo = lower if lower is not None and math.isfinite(float(lower)) else None
    hi = upper if upper is not None and math.isfinite(float(upper)) else None
    if lo is None and hi is None:
        return {"status": "free", "bounds": None, "relation": None}
    return {"status": "bounded", "bounds": [lo, hi], "relation": None}


def status_text(st: dict[str, Any]) -> str:
    s = st.get("status")
    if s == "linked":
        return f"linked {st.get('relation')}"
    if s == "bounded":
        lo, hi = st.get("bounds") or [None, None]
        return f"bounded [{'-inf' if lo is None else _f(lo, 4)}, {'+inf' if hi is None else _f(hi, 4)}]"
    return str(s)


def optimiser_text(technique_family: str | None) -> str:
    tech = str(technique_family or "").lower()
    if tech in ("xps", "xas"):
        return "lmfit Model.fit, Levenberg-Marquardt (leastsq); covariance scaled by reduced chi2"
    return "SciPy curve_fit, trust-region reflective (bounded)"


# Items the report must contain (gap analysis R1 list; ISO 19830 cl. 5/10 as summarised there).
CHECKLIST: list[tuple[str, str]] = [
    ("raw_file", "Raw data file name, block and SHA-256"),
    ("software", "Software name, version and git commit"),
    ("pipeline_hash", "Pipeline hash"),
    ("acquisition", "Acquisition: instrument/source, excitation energy, pass energy, step, dwell, scans"),
    ("max_channel", "Counts and count rate at the maximum channel"),
    ("charge_correction", "Charge-correction method, reference and applied shift"),
    ("processing_history", "Ordered processing steps with parameters"),
    ("background", "Background type, parameters and fit window"),
    ("lineshape", "Line shape of every component"),
    ("values_with_errors", "Position, FWHM, area, %area and height with uncertainties"),
    ("constraints", "Status of every parameter (fixed / bounded / linked + relation)"),
    ("fit_statistics", "Optimiser, N points, free parameters, chi2, reduced chi2, normalised residual STD"),
    ("quantification", "Quantification table (or why it was not performed)"),
    ("figure", "Figure of data, envelope, components, background and residual"),
]
