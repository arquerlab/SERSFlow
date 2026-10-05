from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import curve_fit
import inspect

from sersflow.core.preprocess.fit_diagnostics import FitDiagnostics, compute_fit_diagnostics
from sersflow.core.preprocess.fitting_specs import (
    PEAK_COMPONENT_TYPES,
    build_component_function,
    component_param_specs,
)
from sersflow.core.spectrum import XY


def parse_fit_window(params: dict[str, Any]) -> tuple[float | None, float | None]:
    """
    Optional internal fit window ``fit_min_x`` / ``fit_max_x``.

    When both are unset (or null), the full spectrum is used. When only one bound
    is set, the other is treated as unbounded on that side.
    """
    raw_lo = params.get("fit_min_x")
    raw_hi = params.get("fit_max_x")
    lo: float | None = None
    hi: float | None = None
    if raw_lo is not None and str(raw_lo).strip() != "":
        lo = float(raw_lo)
        if not np.isfinite(lo):
            raise ValueError(f"fit_min_x must be finite; got {raw_lo!r}")
    if raw_hi is not None and str(raw_hi).strip() != "":
        hi = float(raw_hi)
        if not np.isfinite(hi):
            raise ValueError(f"fit_max_x must be finite; got {raw_hi!r}")
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"fit_min_x ({lo}) must be <= fit_max_x ({hi})")
    return lo, hi


def fit_window_mask(x: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    """Boolean mask of points included in the optional fit window."""
    lo, hi = parse_fit_window(params)
    xf = np.asarray(x, dtype=float).ravel()
    if lo is None and hi is None:
        return np.ones(xf.shape, dtype=bool)
    mask = np.ones(xf.shape, dtype=bool)
    if lo is not None:
        mask &= xf >= lo
    if hi is not None:
        mask &= xf <= hi
    return mask


def apply_fit_window_xy(xy: XY, params: dict[str, Any]) -> tuple[XY, np.ndarray]:
    """
    Crop ``xy`` to the optional fit window.

    Returns ``(cropped_xy, mask)`` where ``mask`` indexes into the original arrays.
    When no window is set, returns the original ``xy`` and an all-True mask.
    """
    mask = fit_window_mask(xy.x, params)
    if bool(np.all(mask)):
        return xy, mask
    return XY(x=xy.x[mask], y=xy.y[mask]), mask


def expand_fit_curves_to_full(
    xy: XY,
    params: dict[str, Any],
    y_hat: np.ndarray,
    component_y_hats: list[np.ndarray] | None = None,
) -> tuple[np.ndarray, list[np.ndarray]]:
    """
    Stitch windowed fit curves back onto the full spectrum length.

    Outside the fit window: total ``y_hat`` keeps the original ``y`` (passthrough);
    per-component curves are zero. Residual is then zero outside the window.
    """
    mask = fit_window_mask(xy.x, params)
    y_fit = np.asarray(y_hat, dtype=float).ravel()
    n = int(xy.x.size)
    if bool(np.all(mask)) and y_fit.size == n:
        comps = (
            [np.asarray(c, dtype=float).ravel() for c in component_y_hats]
            if component_y_hats is not None
            else []
        )
        return y_fit, comps

    if int(np.count_nonzero(mask)) != y_fit.size:
        raise ValueError(
            f"fit curve length {y_fit.size} does not match fit window "
            f"({int(np.count_nonzero(mask))} points)"
        )

    y_full = np.asarray(xy.y, dtype=float).ravel().copy()
    y_full[mask] = y_fit
    comps_full: list[np.ndarray] = []
    if component_y_hats is not None:
        for cy in component_y_hats:
            c_arr = np.asarray(cy, dtype=float).ravel()
            if c_arr.size != y_fit.size:
                raise ValueError(
                    f"component curve length {c_arr.size} does not match fit window "
                    f"({y_fit.size} points)"
                )
            c_full = np.zeros(n, dtype=float)
            c_full[mask] = c_arr
            comps_full.append(c_full)
    return y_full, comps_full


def _migrate_fitting_param_vectors(
    components: list[FitComponent],
    p0: list[float],
    lo: list[float | None],
    hi: list[float | None],
    vary: list[bool] | None,
) -> tuple[list[float], list[float | None], list[float | None], list[bool] | None]:
    """
    Pad legacy per-component vectors when the catalog gained trailing parameters.

    Notably: ``fermi_edge`` used to be amplitude/center/sigma/temperature_K (4);
    it now includes a trailing ``const`` intensity floor (5). Old saved pipelines
    omit that slot — pad with auto-sentinel 0 / default bounds so fits still run.
    """
    out_p0: list[float] = []
    out_lo: list[float | None] = []
    out_hi: list[float | None] = []
    out_vary: list[bool] | None = [] if vary is not None else None
    src = 0
    for comp in components:
        specs = component_param_specs(comp.component_type, degree=comp.degree)
        n = len(specs)
        remaining = len(p0) - src
        take = n
        pad_keys: list[str] = []
        # Legacy fermi_edge without const (exactly one trailing param missing).
        if (
            comp.component_type.strip().lower() == "fermi_edge"
            and n >= 1
            and specs[-1].key == "const"
            and remaining == n - 1
        ):
            take = n - 1
            pad_keys = ["const"]
        elif remaining < n:
            raise ValueError(
                f"p0 length mismatch for component {comp.component_id!r} "
                f"({comp.component_type}): need {n} params, have {remaining} remaining"
            )
        for i in range(take):
            out_p0.append(float(p0[src + i]))
            out_lo.append(None if lo[src + i] is None else float(lo[src + i]))
            out_hi.append(None if hi[src + i] is None else float(hi[src + i]))
            if out_vary is not None:
                if vary is None or src + i >= len(vary):
                    out_vary.append(True)
                else:
                    out_vary.append(bool(vary[src + i]))
        src += take
        for key in pad_keys:
            spec = next(s for s in specs if s.key == key)
            out_p0.append(float(spec.default if spec.default is not None else 0.0))
            out_lo.append(spec.lower_default)
            out_hi.append(spec.upper_default)
            if out_vary is not None:
                vary_default = True
                ui = spec.ui or {}
                if ui.get("vary_default") is False:
                    vary_default = False
                out_vary.append(vary_default)
    if src != len(p0):
        raise ValueError(f"p0 length mismatch: consumed {src}, got {len(p0)}")
    if len(lo) < src or len(hi) < src:
        raise ValueError(
            f"bounds length mismatch: expected at least {src}, got lo={len(lo)}, hi={len(hi)}"
        )
    return out_p0, out_lo, out_hi, out_vary


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
    default: use client p0; amp ≤ 0 on peaks is auto-estimated (intensity at center).
    auto (legacy): force auto amplitude for every peak component.
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
    *,
    only_nonpositive: bool = False,
) -> list[float]:
    """
    Set peak amplitudes from spectrum intensity at the center (pos).

    When ``only_nonpositive`` is True (default path for per-peak Auto checkboxes),
    only amplitudes with seed ≤ 0 are replaced. When False, all peak amplitudes
    are replaced (legacy ``initial_guess_mode="auto"``).
    """
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
        if only_nonpositive and float(out[gamp]) > 0:
            continue
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

    Applies optional ``fit_min_x`` / ``fit_max_x`` so the optimizer (and XPS backgrounds)
    see only the fit window. Returns None when x/y are empty after cropping (caller should
    pass through). Raises ValueError when params are invalid.
    """
    if xy.x.size == 0 or xy.y.size == 0:
        return None
    xy_fit, _mask = apply_fit_window_xy(xy, params)
    if xy_fit.x.size == 0 or xy_fit.y.size == 0:
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

    p0_f = [float(x) for x in p0]
    lo_f = [None if v is None else float(v) for v in lo]
    hi_f = [None if v is None else float(v) for v in hi]
    p0_f, lo_f, hi_f, vary = _migrate_fitting_param_vectors(components, p0_f, lo_f, hi_f, vary)

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
        x=xy_fit.x.astype(float, copy=False),
        y=xy_fit.y.astype(float, copy=False),
        components=components,
        p0=p0_f,
        bounds_lower=lo_f,
        bounds_upper=hi_f,
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
    # Per-peak Auto (UI) sends amp ≤ 0; legacy initial_guess_mode="auto" forces all.
    p0_list = _apply_auto_peak_amplitudes(
        problem.x,
        problem.y,
        p0_list,
        problem.components,
        slices,
        param_keys_per_comp,
        lo_list,
        hi_list,
        only_nonpositive=(mode != "auto"),
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
