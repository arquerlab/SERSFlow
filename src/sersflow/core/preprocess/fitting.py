from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import curve_fit
import inspect

from sersflow.core.preprocess.fit_diagnostics import FitDiagnostics, compute_fit_diagnostics
from sersflow.core.preprocess.fitting_specs import PEAK_COMPONENT_TYPES, build_component_function
from sersflow.core.spectrum import XY


@dataclass(frozen=True)
class FitComponent:
    component_type: str
    component_id: str
    degree: int | None = None


@dataclass(frozen=True)
class FitProblem:
    x: np.ndarray
    y: np.ndarray
    components: list[FitComponent]
    p0: list[float]
    bounds_lower: list[float | None]
    bounds_upper: list[float | None]
    initial_guess_mode: str = "default"
    technique_family: str = "vibrational"
    vary: list[bool] | None = None
    param_links: list[dict[str, Any]] | None = None
    xps_region: str | None = None
    """
    default: use client p0 as-is.
    auto: for each peak component (gaussian / lorentzian / pseudo_voigt / gl / voigt /
    ds / gds / la / lf / apv / asymmetric_voigt), set initial amplitude to the spectrum
    intensity linearly interpolated at the initial center position (p0 pos), per spectrum.
    """


@dataclass(frozen=True)
class FitResult:
    p_opt: np.ndarray
    p_cov: np.ndarray | None
    y_hat: np.ndarray
    """Total fitted curve (sum of components)."""
    component_y_hat: list[np.ndarray]
    """Per-component curves on the same x grid, same order as `components`."""
    mapping: list[dict[str, Any]]
    diagnostics: FitDiagnostics


def _interp_y_at_x(x: np.ndarray, y: np.ndarray, xq: float) -> float:
    """Linear interpolation of y(x) at xq; x may be unsorted (e.g. Raman axis)."""
    xf = np.asarray(x, dtype=float).ravel()
    yf = np.asarray(y, dtype=float).ravel()
    if xf.size == 0 or yf.size == 0 or xf.shape != yf.shape:
        return float("nan")
    order = np.argsort(xf)
    xs = xf[order]
    ys = yf[order]
    return float(
        np.interp(np.array([xq], dtype=float), xs, ys, left=float(ys[0]), right=float(ys[-1]))[0]
    )


def _apply_auto_peak_amplitudes(
    x: np.ndarray,
    y: np.ndarray,
    p0: list[float],
    components: list[FitComponent],
    slices: list[tuple[int, int]],
    param_keys_per_comp: list[list[str]],
    bounds_lower: list[float | None] | None = None,
    bounds_upper: list[float | None] | None = None,
) -> list[float]:
    out = list(p0)
    for comp, (s, _e), keys in zip(components, slices, param_keys_per_comp):
        if comp.component_type.strip().lower() not in PEAK_COMPONENT_TYPES:
            continue
        try:
            pos_i = keys.index("pos")
            amp_i = keys.index("amp")
        except ValueError:
            continue
        gpos = s + pos_i
        gamp = s + amp_i
        pos_val = float(out[gpos])
        amp = _interp_y_at_x(x, y, pos_val)
        if bounds_lower is not None and bounds_lower[gamp] is not None:
            amp = max(amp, float(bounds_lower[gamp]))
        if bounds_upper is not None and bounds_upper[gamp] is not None:
            amp = min(amp, float(bounds_upper[gamp]))
        out[gamp] = amp
    return out


# Backwards-compatible alias for older imports/tests.
_apply_auto_gaussian_amplitudes = _apply_auto_peak_amplitudes


def fit_problem_from_step_params(xy: XY, params: dict[str, Any]) -> FitProblem | None:
    """
    Build a FitProblem from pipeline fitting step params (same contract as the fitting transform).

    Returns None when x/y are empty (caller should pass through). Raises ValueError when params are invalid.
    """
    if xy.x.size == 0 or xy.y.size == 0:
        return None
    igm = str(params.get("initial_guess_mode", "default")).strip().lower()
    if igm not in ("default", "auto"):
        igm = "default"
    comps_raw = params.get("components")
    if not isinstance(comps_raw, list) or not comps_raw:
        raise ValueError("fitting step requires params.components (non-empty list)")
    p0 = params.get("p0")
    lo = params.get("bounds_lower")
    hi = params.get("bounds_upper")
    if not isinstance(p0, list):
        raise ValueError("fitting step requires params.p0 (list)")
    if not isinstance(lo, list) or not isinstance(hi, list):
        raise ValueError("fitting step requires params.bounds_lower and params.bounds_upper (lists)")

    components: list[FitComponent] = []
    for i, row in enumerate(comps_raw):
        if not isinstance(row, dict):
            raise ValueError(f"fitting.components[{i}] must be an object")
        cid = str(row.get("component_id") or "").strip()
        ctype = str(row.get("component_type") or "").strip()
        if not cid or not ctype:
            raise ValueError(f"fitting.components[{i}] requires component_id and component_type")
        deg = row.get("degree")
        degree = int(deg) if deg is not None else None
        components.append(FitComponent(component_type=ctype, component_id=cid, degree=degree))

    vary_raw = params.get("vary")
    vary: list[bool] | None = None
    if isinstance(vary_raw, list) and vary_raw:
        vary = [bool(v) for v in vary_raw]

    links_raw = params.get("param_links")
    param_links: list[dict[str, Any]] | None = None
    if isinstance(links_raw, list) and links_raw:
        param_links = [dict(x) for x in links_raw if isinstance(x, dict)]

    region = params.get("xps_region")
    xps_region = str(region).strip() if region is not None and str(region).strip() else None

    tech_raw = params.get("technique_family")
    if tech_raw is None or str(tech_raw).strip() == "":
        tech = "vibrational"
    else:
        tech = str(tech_raw).strip().lower()
        if tech not in ("vibrational", "xps"):
            raise ValueError(
                f"Invalid technique_family {tech_raw!r}; expected 'vibrational' or 'xps'"
            )

    return FitProblem(
        x=xy.x.astype(float, copy=False),
        y=xy.y.astype(float, copy=False),
        components=components,
        p0=[float(x) for x in p0],
        bounds_lower=[None if v is None else float(v) for v in lo],
        bounds_upper=[None if v is None else float(v) for v in hi],
        initial_guess_mode=igm,
        technique_family=tech,
        vary=vary,
        param_links=param_links,
        xps_region=xps_region,
    )


def _validate_vectors(n: int, p0: list[float], lo: list[float | None], hi: list[float | None]) -> None:
    if len(p0) != n:
        raise ValueError(f"p0 length mismatch: expected {n}, got {len(p0)}")
    if len(lo) != n or len(hi) != n:
        raise ValueError(f"bounds length mismatch: expected {n}, got lo={len(lo)}, hi={len(hi)}")
    for i, (l, u) in enumerate(zip(lo, hi)):
        if l is not None and u is not None and l > u:
            raise ValueError(f"invalid bounds at index {i}: lower > upper")


def fit_curve(problem: FitProblem) -> FitResult:
    """
    Fit a sum of components using technique-gated engines:
    - vibrational -> SciPy curve_fit
    - xps -> lmfit (always)
    """
    tech = str(problem.technique_family or "vibrational").strip().lower()
    if tech not in ("vibrational", "xps"):
        raise ValueError(
            f"Invalid technique_family {problem.technique_family!r}; expected 'vibrational' or 'xps'"
        )
    if tech == "xps":
        from sersflow.core.preprocess.fitting_lmfit import fit_curve_lmfit

        return fit_curve_lmfit(problem)

    from sersflow.core.preprocess.fitting_specs import XPS_LMFITXPS_COMPONENT_TYPES

    for comp in problem.components:
        if comp.component_type.strip().lower() in XPS_LMFITXPS_COMPONENT_TYPES:
            raise ValueError(
                f"XPS component {comp.component_type!r} requires an XPS pipeline (lmfit engine)"
            )
    if problem.param_links:
        raise ValueError("Parameter links require an XPS pipeline (lmfit engine)")

    return _fit_curve_scipy(problem)


def evaluate_fit_curves(
    problem: FitProblem,
    p_opt: np.ndarray | list[float],
    *,
    diagnostics: FitDiagnostics | None = None,
) -> FitResult:
    """
    Evaluate component + total curves from an already-optimized parameter vector.

    Does not run an optimizer. Used by Analyze Plots / fit-curve exports so analysis
    runs are not re-fit when rendering residuals and components.
    """
    tech = str(problem.technique_family or "vibrational").strip().lower()
    if tech not in ("vibrational", "xps"):
        raise ValueError(
            f"Invalid technique_family {problem.technique_family!r}; expected 'vibrational' or 'xps'"
        )
    p = np.asarray(p_opt, dtype=float).ravel()
    if tech == "xps":
        from sersflow.core.preprocess.fitting_lmfit import evaluate_curve_lmfit

        return evaluate_curve_lmfit(problem, p, diagnostics=diagnostics)

    from sersflow.core.preprocess.fitting_specs import XPS_LMFITXPS_COMPONENT_TYPES

    for comp in problem.components:
        if comp.component_type.strip().lower() in XPS_LMFITXPS_COMPONENT_TYPES:
            raise ValueError(
                f"XPS component {comp.component_type!r} requires an XPS pipeline (lmfit engine)"
            )
    return _evaluate_curve_scipy(problem, p, diagnostics=diagnostics)


def _build_scipy_component_model(
    problem: FitProblem,
) -> tuple[
    list[tuple[FitComponent, Any, list[Any]]],
    list[tuple[int, int]],
    list[dict[str, Any]],
    int,
]:
    funcs = []
    slices: list[tuple[int, int]] = []
    mapping: list[dict[str, Any]] = []
    cursor = 0
    for comp in problem.components:
        f, params = build_component_function(comp.component_type, degree=comp.degree)
        n = len(params)
        start, end = cursor, cursor + n
        cursor = end
        funcs.append((comp, f, params))
        slices.append((start, end))
        mapping.append(
            {
                "component_id": comp.component_id,
                "component_type": comp.component_type,
                "degree": comp.degree,
                "param_keys": [p.key for p in params],
                "index_range": [start, end],
            }
        )
    return funcs, slices, mapping, cursor


def _evaluate_curve_scipy(
    problem: FitProblem,
    p_opt: np.ndarray,
    *,
    diagnostics: FitDiagnostics | None = None,
) -> FitResult:
    if problem.x.ndim != 1 or problem.y.ndim != 1:
        raise ValueError("x and y must be 1D arrays")
    if problem.x.shape[0] != problem.y.shape[0]:
        raise ValueError("x and y length mismatch")
    if not problem.components:
        raise ValueError("components must not be empty")

    funcs, slices, mapping, cursor = _build_scipy_component_model(problem)
    if p_opt.size != cursor:
        raise ValueError(f"p_opt length mismatch: expected {cursor}, got {p_opt.size}")

    xf = problem.x.astype(float)
    yf = problem.y.astype(float)
    p_list = p_opt.tolist()
    yhat = np.zeros_like(xf, dtype=float)
    comp_curves: list[np.ndarray] = []
    for (_comp, f, _params), (s, e) in zip(funcs, slices):
        yc = np.asarray(f(xf, *p_list[s:e]), dtype=float)
        comp_curves.append(yc)
        yhat = yhat + yc

    if diagnostics is None:
        if problem.vary is not None and len(problem.vary) >= cursor:
            n_vary = sum(1 for v in problem.vary[:cursor] if v)
        else:
            n_vary = cursor
            if problem.vary is not None:
                for i, vflag in enumerate(problem.vary):
                    if i < cursor and not vflag:
                        n_vary -= 1
        diagnostics = compute_fit_diagnostics(
            yf,
            yhat,
            n_vary=max(0, int(n_vary)),
            p_cov=None,
            p_opt=p_opt,
            nfev=None,
            success=True,
        )
    return FitResult(
        p_opt=p_opt,
        p_cov=None,
        y_hat=yhat,
        component_y_hat=comp_curves,
        mapping=mapping,
        diagnostics=diagnostics,
    )


def _fit_curve_scipy(problem: FitProblem) -> FitResult:
    """Fit a sum of components using bounded SciPy curve_fit."""
    if problem.x.ndim != 1 or problem.y.ndim != 1:
        raise ValueError("x and y must be 1D arrays")
    if problem.x.shape[0] != problem.y.shape[0]:
        raise ValueError("x and y length mismatch")
    if not problem.components:
        raise ValueError("components must not be empty")

    funcs, slices, mapping, cursor = _build_scipy_component_model(problem)

    _validate_vectors(cursor, problem.p0, problem.bounds_lower, problem.bounds_upper)

    lo_list = list(problem.bounds_lower)
    hi_list = list(problem.bounds_upper)
    p0_list = [float(v) for v in problem.p0]
    if problem.vary is not None:
        for i, vflag in enumerate(problem.vary):
            if i < len(p0_list) and not vflag:
                lo_list[i] = p0_list[i]
                hi_list[i] = p0_list[i]

    param_keys_per_comp = [m["param_keys"] for m in mapping]
    mode = str(problem.initial_guess_mode or "default").strip().lower()
    if mode == "auto":
        p0_list = _apply_auto_peak_amplitudes(
            problem.x,
            problem.y,
            p0_list,
            problem.components,
            slices,
            param_keys_per_comp,
            lo_list,
            hi_list,
        )

    n_data = int(problem.x.shape[0])
    if n_data < cursor + 1:
        raise ValueError(
            f"Insufficient points for fit: {n_data} data point(s) but {cursor} model parameter(s) "
            "(need at least one more point than parameters). Widen the crop range or simplify the model."
        )

    def model_sum(x: np.ndarray, *p: float) -> np.ndarray:
        yhat = np.zeros_like(x, dtype=float)
        for (_comp, f, _params), (s, e) in zip(funcs, slices):
            yhat = yhat + f(x, *p[s:e])
        return yhat

    lo = np.array([(-np.inf if v is None else float(v)) for v in lo_list], dtype=float)
    hi = np.array([(np.inf if v is None else float(v)) for v in hi_list], dtype=float)

    p0 = np.array(p0_list, dtype=float)
    xf = problem.x.astype(float)
    yf = problem.y.astype(float)
    try:
        sig = inspect.signature(curve_fit)
        if "max_nfev" in sig.parameters:
            max_kwargs = {"max_nfev": 50_000}
        elif "maxfev" in sig.parameters:
            max_kwargs = {"maxfev": 50_000}
        else:
            max_kwargs = {}
        popt, pcov = curve_fit(
            model_sum,
            xf,
            yf,
            p0=p0,
            bounds=(lo, hi),
            **max_kwargs,
        )
    except RuntimeError as e:
        msg = str(e)
        if "Optimal parameters not found" in msg:
            raise ValueError(
                "Nonlinear fit did not converge. Try adjusting initial parameters (p0) and bounds, "
                "widening the crop range, or simplifying the model. "
                f"Details: {msg}"
            ) from e
        raise
    yhat = model_sum(xf, *popt.tolist())
    comp_curves: list[np.ndarray] = []
    for (_comp, f, _params), (s, e) in zip(funcs, slices):
        comp_curves.append(np.asarray(f(xf, *popt[s:e].tolist()), dtype=float))
    if problem.vary is not None and len(problem.vary) >= cursor:
        n_vary = sum(1 for v in problem.vary[:cursor] if v)
    else:
        n_vary = cursor
        if problem.vary is not None:
            for i, vflag in enumerate(problem.vary):
                if i < cursor and not vflag:
                    n_vary -= 1
    diag = compute_fit_diagnostics(
        yf,
        yhat,
        n_vary=max(0, int(n_vary)),
        p_cov=pcov,
        p_opt=popt,
        nfev=None,
        success=True,
    )
    return FitResult(
        p_opt=popt,
        p_cov=pcov,
        y_hat=yhat,
        component_y_hat=comp_curves,
        mapping=mapping,
        diagnostics=diag,
    )
