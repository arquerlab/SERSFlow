"""lmfit-backed nonlinear fitting for XPS technique pipelines."""

from __future__ import annotations

import re
from typing import Any, Callable

import numpy as np

from sersflow.core.preprocess.fit_diagnostics import FitDiagnostics, compute_fit_diagnostics
from sersflow.core.preprocess.fitting import (
    FitComponent,
    FitProblem,
    FitResult,
    _apply_auto_peak_amplitudes,
    _validate_vectors,
)
from sersflow.core.preprocess.fitting_specs import XPS_BACKGROUND_COMPONENT_TYPES, build_component_function

_SAFE = re.compile(r"[^0-9a-zA-Z_]+")


def _prefix_for(component_id: str) -> str:
    frag = _SAFE.sub("_", str(component_id).strip()) or "comp"
    if frag[0].isdigit():
        frag = f"c_{frag}"
    return f"{frag}_"


def _make_peak_model(fn: Callable[..., np.ndarray], keys: list[str], prefix: str):
    from lmfit import Model

    arg_list = ", ".join(keys)
    local: dict[str, Any] = {"fn": fn}
    exec(f"def _peak(x, {arg_list}):\n    return fn(x, {arg_list})\n", local)
    return Model(local["_peak"], independent_vars=["x"], prefix=prefix)


def _xps_bg_model(component_type: str, prefix: str, y0: float):
    from lmfitxps import models as xps_models  # type: ignore

    ct = component_type.strip().lower()
    if ct == "shirley_bg":
        return xps_models.ShirleyBG(independent_vars=["y"], prefix=prefix), ["k", "const"]
    if ct == "tougaard_bg":
        return xps_models.TougaardBG(independent_vars=["x", "y"], prefix=prefix), ["B", "C", "C_d", "D", "extend"]
    if ct == "slope_bg":
        return xps_models.SlopeBG(independent_vars=["y"], prefix=prefix), ["k"]
    raise ValueError(f"Unknown XPS background component: {component_type}")


def _apply_xps_fit_safeguards(
    problem: FitProblem,
    *,
    slices: list[tuple[int, int]],
    param_keys_per_comp: list[list[str]],
) -> tuple[list[float], list[float | None], list[float | None], bool]:
    """
    Harden XPS fits when recipes seed relative amplitudes (~1) and leave FWHM unbounded.

    Without this, the optimizer often inflates FWHM to ~10^5–10^6 and flattens peaks
    into constant offsets (R² near 0).

    Returns (p0, bounds_lower, bounds_upper, auto_amps_applied).
    """
    p0 = [float(v) for v in problem.p0]
    lo = list(problem.bounds_lower)
    hi = list(problem.bounds_upper)
    auto_applied = False

    x_span = float(np.ptp(problem.x))
    if not np.isfinite(x_span) or x_span <= 0:
        x_span = 10.0

    for keys, (s, _e) in zip(param_keys_per_comp, slices):
        for j, key in enumerate(keys):
            if not str(key).startswith("fwhm"):
                continue
            idx = s + j
            if hi[idx] is None:
                seed = abs(float(p0[idx])) if np.isfinite(p0[idx]) else 1.0
                # Prefer a few× recipe FWHM; never exceed the energy window.
                hi[idx] = float(min(x_span, max(8.0, 5.0 * max(seed, 1e-6))))

    yf = np.asarray(problem.y, dtype=float)
    y_scale = float(np.nanpercentile(yf, 95) - np.nanpercentile(yf, 5))
    if not np.isfinite(y_scale) or y_scale <= 0:
        y_scale = float(np.nanmax(yf) - np.nanmin(yf)) if yf.size else 1.0
    y_scale = max(y_scale, 1e-9)

    free_peak_amps: list[float] = []
    for comp, keys, (s, _e) in zip(problem.components, param_keys_per_comp, slices):
        ct = comp.component_type.strip().lower()
        if ct in XPS_BACKGROUND_COMPONENT_TYPES:
            continue
        if "amp" not in keys:
            continue
        amp_i = s + keys.index("amp")
        if problem.vary is not None and amp_i < len(problem.vary) and not problem.vary[amp_i]:
            continue
        free_peak_amps.append(abs(float(p0[amp_i])))

    max_free_amp = max(free_peak_amps) if free_peak_amps else 0.0
    # Relative recipes typically seed amp≈1 while counts are 10^3–10^5.
    caller_mode = str(problem.initial_guess_mode or "default").strip().lower()
    need_auto = caller_mode != "auto" and max_free_amp > 0 and max_free_amp < 0.02 * y_scale
    if need_auto:
        p0 = _apply_auto_peak_amplitudes(
            problem.x,
            problem.y,
            p0,
            problem.components,
            slices,
            param_keys_per_comp,
            lo,
            hi,
        )
        auto_applied = True

    # Shirley const ≈ intensity at the *low-BE* endpoint (not always y[-1]).
    # Ascending BE axes store low BE at index 0; descending (common after KE→BE)
    # store low BE at the last sample.
    xf = np.asarray(problem.x, dtype=float)
    low_be_y = 0.0
    if yf.size and xf.size == yf.size:
        low_be_y = float(yf[int(np.argmin(xf))])

    for comp, keys, (s, _e) in zip(problem.components, param_keys_per_comp, slices):
        if comp.component_type.strip().lower() != "shirley_bg":
            continue
        if "const" not in keys:
            continue
        ci = s + keys.index("const")
        if abs(float(p0[ci])) < 1e-9:
            p0[ci] = low_be_y

    return p0, lo, hi, auto_applied


def _assemble_lmfit_model(
    problem: FitProblem,
) -> tuple[
    Any,
    list[Callable[..., np.ndarray] | None],
    list[tuple[int, int]],
    list[dict[str, Any]],
    list[str],
    list[list[str]],
    int,
    bool,
]:
    has_active_bg = any(
        c.component_type.strip().lower() in XPS_BACKGROUND_COMPONENT_TYPES for c in problem.components
    )

    peak_fns: list[Callable[..., np.ndarray] | None] = []
    slices: list[tuple[int, int]] = []
    mapping: list[dict[str, Any]] = []
    prefixes: list[str] = []
    cursor = 0
    model = None

    for comp in problem.components:
        ct = comp.component_type.strip().lower()
        prefix = _prefix_for(comp.component_id)
        prefixes.append(prefix)
        if ct in XPS_BACKGROUND_COMPONENT_TYPES:
            try:
                m, param_keys = _xps_bg_model(ct, prefix, float(np.min(problem.y)))
            except ImportError as e:
                raise ImportError("Active XPS backgrounds require lmfitxps>=4.2.0") from e
            peak_fns.append(None)
        else:
            f, param_specs = build_component_function(comp.component_type, degree=comp.degree)
            param_keys = [p.key for p in param_specs]
            m = _make_peak_model(f, param_keys, prefix)
            peak_fns.append(f)

        n = len(param_keys)
        start, end = cursor, cursor + n
        cursor = end
        slices.append((start, end))
        mapping.append(
            {
                "component_id": comp.component_id,
                "component_type": comp.component_type,
                "degree": comp.degree,
                "param_keys": param_keys,
                "index_range": [start, end],
            }
        )
        model = m if model is None else (model + m)

    assert model is not None
    param_keys_per_comp = [m["param_keys"] for m in mapping]
    return model, peak_fns, slices, mapping, prefixes, param_keys_per_comp, cursor, has_active_bg


def _apply_param_links(
    params: Any,
    problem: FitProblem,
    name_by_comp_key: dict[tuple[str, str], str],
) -> None:
    for link in problem.param_links or []:
        src = (str(link.get("source_component_id") or ""), str(link.get("source_key") or ""))
        tgt = (str(link.get("target_component_id") or ""), str(link.get("target_key") or ""))
        mode_l = str(link.get("mode") or "equal").strip().lower()
        if src not in name_by_comp_key or tgt not in name_by_comp_key:
            raise ValueError(f"Invalid param link: {link}")
        if src == tgt:
            raise ValueError("param link cannot target itself")
        src_name = name_by_comp_key[src]
        tgt_name = name_by_comp_key[tgt]
        if mode_l == "equal":
            expr = tgt_name
        elif mode_l == "scale":
            scale = float(link.get("scale", 1.0))
            if not np.isfinite(scale):
                raise ValueError(f"param link scale must be finite: {link}")
            expr = f"({scale})*{tgt_name}"
        elif mode_l == "offset":
            offset = float(link.get("offset", 0.0))
            if not np.isfinite(offset):
                raise ValueError(f"param link offset must be finite: {link}")
            expr = f"({tgt_name})+({offset})"
        else:
            raise ValueError(f"Unknown link mode: {mode_l}")
        params[src_name].set(expr=expr, vary=False)


def fit_curve_lmfit(problem: FitProblem) -> FitResult:
    try:
        from lmfit import Parameters  # noqa: F401
    except Exception as e:
        raise ImportError("XPS fitting requires lmfit (via lmfitxps). Install lmfitxps>=4.2.0.") from e

    if problem.x.ndim != 1 or problem.y.ndim != 1:
        raise ValueError("x and y must be 1D arrays")
    if problem.x.shape[0] != problem.y.shape[0]:
        raise ValueError("x and y length mismatch")
    if not problem.components:
        raise ValueError("components must not be empty")

    model, peak_fns, slices, mapping, prefixes, param_keys_per_comp, cursor, has_active_bg = (
        _assemble_lmfit_model(problem)
    )
    _validate_vectors(cursor, problem.p0, problem.bounds_lower, problem.bounds_upper)

    p0_list, lo_list, hi_list, auto_already = _apply_xps_fit_safeguards(
        problem, slices=slices, param_keys_per_comp=param_keys_per_comp
    )
    if str(problem.initial_guess_mode or "default").strip().lower() == "auto" and not auto_already:
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

    params = model.make_params()
    flat_names: list[str] = []
    name_by_comp_key: dict[tuple[str, str], str] = {}
    for comp, keys, (s, _e), prefix in zip(
        problem.components, param_keys_per_comp, slices, prefixes
    ):
        for j, key in enumerate(keys):
            idx = s + j
            name = f"{prefix}{key}"
            flat_names.append(name)
            name_by_comp_key[(comp.component_id, key)] = name
            lo = lo_list[idx]
            hi = hi_list[idx]
            vary = True
            if problem.vary is not None and idx < len(problem.vary):
                vary = bool(problem.vary[idx])
            if name not in params:
                params.add(name)
            params[name].set(
                value=float(p0_list[idx]),
                min=(-np.inf if lo is None else float(lo)),
                max=(np.inf if hi is None else float(hi)),
                vary=vary,
            )

    _apply_param_links(params, problem, name_by_comp_key)

    xf = problem.x.astype(float)
    yf = problem.y.astype(float)
    fit_kws: dict[str, Any] = {"x": xf}
    if has_active_bg:
        fit_kws["y"] = yf
    try:
        result = model.fit(yf, params, max_nfev=50_000, **fit_kws)
    except Exception as e:
        raise ValueError(f"lmfit fit failed: {e}") from e

    p_opt = np.array([float(result.params[n].value) for n in flat_names], dtype=float)
    try:
        cov = result.covar
        p_cov = np.asarray(cov, dtype=float) if cov is not None else None
    except Exception:
        p_cov = None

    y_hat = np.asarray(result.best_fit, dtype=float)
    comp_curves: list[np.ndarray] = []
    try:
        ev = result.eval_components(**fit_kws)
    except Exception:
        ev = {}
    for _comp, f, _keys, (s, e), prefix in zip(
        problem.components, peak_fns, param_keys_per_comp, slices, prefixes
    ):
        if f is not None:
            comp_curves.append(np.asarray(f(xf, *p_opt[s:e].tolist()), dtype=float))
            continue
        matched = None
        for k, arr in ev.items():
            if k.startswith(prefix) or prefix.rstrip("_") == k.rstrip("_"):
                matched = arr
                break
        comp_curves.append(np.asarray(matched if matched is not None else np.zeros_like(xf), dtype=float))

    n_vary = 0
    for name in flat_names:
        p = result.params.get(name)
        if p is not None and bool(getattr(p, "vary", False)) and not getattr(p, "expr", None):
            n_vary += 1
    nfev = None
    try:
        nv = getattr(result, "nfev", None)
        if nv is not None:
            nfev = int(nv)
    except Exception:
        nfev = None
    diag = compute_fit_diagnostics(
        yf,
        y_hat,
        n_vary=n_vary,
        p_cov=p_cov,
        p_opt=p_opt,
        nfev=nfev,
        success=bool(getattr(result, "success", True)),
    )
    return FitResult(
        p_opt=p_opt,
        p_cov=p_cov,
        y_hat=y_hat,
        component_y_hat=comp_curves,
        mapping=mapping,
        diagnostics=diag,
    )


def evaluate_curve_lmfit(
    problem: FitProblem,
    p_opt: np.ndarray,
    *,
    diagnostics: FitDiagnostics | None = None,
) -> FitResult:
    """Evaluate XPS model curves from stored parameters (no optimization)."""
    try:
        from lmfit import Parameters  # noqa: F401
    except Exception as e:
        raise ImportError("XPS fitting requires lmfit (via lmfitxps). Install lmfitxps>=4.2.0.") from e

    if problem.x.ndim != 1 or problem.y.ndim != 1:
        raise ValueError("x and y must be 1D arrays")
    if problem.x.shape[0] != problem.y.shape[0]:
        raise ValueError("x and y length mismatch")
    if not problem.components:
        raise ValueError("components must not be empty")

    model, peak_fns, slices, mapping, prefixes, param_keys_per_comp, cursor, has_active_bg = (
        _assemble_lmfit_model(problem)
    )
    p = np.asarray(p_opt, dtype=float).ravel()
    if p.size != cursor:
        raise ValueError(f"p_opt length mismatch: expected {cursor}, got {p.size}")

    params = model.make_params()
    flat_names: list[str] = []
    name_by_comp_key: dict[tuple[str, str], str] = {}
    for comp, keys, (s, _e), prefix in zip(
        problem.components, param_keys_per_comp, slices, prefixes
    ):
        for j, key in enumerate(keys):
            idx = s + j
            name = f"{prefix}{key}"
            flat_names.append(name)
            name_by_comp_key[(comp.component_id, key)] = name
            if name not in params:
                params.add(name)
            params[name].set(value=float(p[idx]), vary=False)

    _apply_param_links(params, problem, name_by_comp_key)

    xf = problem.x.astype(float)
    yf = problem.y.astype(float)
    fit_kws: dict[str, Any] = {"x": xf}
    if has_active_bg:
        fit_kws["y"] = yf
    try:
        y_hat = np.asarray(model.eval(params=params, **fit_kws), dtype=float)
    except Exception as e:
        raise ValueError(f"lmfit evaluate failed: {e}") from e

    comp_curves: list[np.ndarray] = []
    try:
        ev = model.eval_components(params=params, **fit_kws)
    except Exception:
        ev = {}
    for _comp, f, _keys, (s, e), prefix in zip(
        problem.components, peak_fns, param_keys_per_comp, slices, prefixes
    ):
        if f is not None:
            comp_curves.append(np.asarray(f(xf, *p[s:e].tolist()), dtype=float))
            continue
        matched = None
        for k, arr in ev.items():
            if k.startswith(prefix) or prefix.rstrip("_") == k.rstrip("_"):
                matched = arr
                break
        comp_curves.append(np.asarray(matched if matched is not None else np.zeros_like(xf), dtype=float))

    if diagnostics is None:
        n_vary = 0
        if problem.vary is not None:
            n_vary = sum(1 for i, v in enumerate(problem.vary) if i < cursor and v)
        else:
            n_vary = cursor
        diagnostics = compute_fit_diagnostics(
            yf,
            y_hat,
            n_vary=max(0, int(n_vary)),
            p_cov=None,
            p_opt=p,
            nfev=None,
            success=True,
        )
    return FitResult(
        p_opt=p,
        p_cov=None,
        y_hat=y_hat,
        component_y_hat=comp_curves,
        mapping=mapping,
        diagnostics=diagnostics,
    )
