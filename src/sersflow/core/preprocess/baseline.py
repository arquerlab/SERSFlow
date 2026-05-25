from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

ParamKind = Literal["number", "int", "boolean", "string", "json"]
UiRole = Literal["primary", "advanced", "hidden"]


@dataclass(frozen=True)
class BaselineCategorySpec:
    id: str
    label: str


@dataclass(frozen=True)
class BaselineParamSpec:
    key: str
    kind: ParamKind
    default: Any
    nullable: bool
    ui_role: UiRole
    description: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class BaselineMethodSpec:
    id: str
    category: str
    label: str
    params: tuple[BaselineParamSpec, ...]
    ui_enabled: bool = True


BASELINE_CATEGORIES: tuple[BaselineCategorySpec, ...] = (
    BaselineCategorySpec("whittaker", "Whittaker"),
    BaselineCategorySpec("smoothing", "Smoothing"),
    BaselineCategorySpec("splines", "Splines"),
    BaselineCategorySpec("polynomial", "Polynomial"),
    BaselineCategorySpec("morphological", "Morphological"),
    BaselineCategorySpec("miscellaneous", "Miscellaneous"),
)

_PARAM_DESCRIPTIONS: dict[str, str] = {
    "alpha": "Adaptive weighting parameter used by asymmetric methods.",
    "alpha_factor": "Factor used to update robust polynomial weights between iterations.",
    "asymmetric_coef": "Controls how strongly asymmetric weighting suppresses positive peaks.",
    "asymmetry": "BEADS asymmetry parameter; larger values penalize positive residuals more strongly.",
    "baseline_points": "Known baseline points used for interpolation.",
    "beta": "JBCD beta regularization parameter.",
    "beta_mult": "Multiplier applied to beta during JBCD iterations.",
    "conserve_memory": "Use a lower-memory LOESS implementation when possible.",
    "cost_function": "Robust loss function used by the algorithm.",
    "decreasing": "Run SNIP with decreasing clipping windows.",
    "delta": "LOESS shortcut distance for reusing local fits.",
    "diff_order": "Difference-penalty order; higher values enforce smoother curvature.",
    "eps": "Small numerical stabilization value.",
    "eps_0": "BEADS numerical stabilization parameter for the baseline term.",
    "eps_1": "BEADS numerical stabilization parameter for derivative terms.",
    "eta": "DRPLS weighting parameter that controls reweighting strength.",
    "filter_order": "SNIP filter order.",
    "filter_type": "BEADS filter type.",
    "fit_parabola": "Whether BEADS should remove a fitted parabola before correction.",
    "fraction": "Fraction of points used in each local LOESS regression.",
    "freq_cutoff": "BEADS cutoff frequency separating baseline from peaks.",
    "gamma": "JBCD gamma regularization parameter.",
    "gamma_mult": "Multiplier applied to gamma during JBCD iterations.",
    "half_window": "Local window radius used for morphological or smoothing operations.",
    "height_scale": "Ria peak-height scaling factor.",
    "interp_method": "Interpolation method used between known baseline points.",
    "k": "Exponential decay factor for peak weighting.",
    "lam": "Smoothness penalty; larger values produce smoother baselines.",
    "lam_0": "BEADS baseline sparsity penalty.",
    "lam_1": "First-derivative smoothness or sparsity penalty.",
    "lam_2": "Second-derivative smoothness or sparsity penalty.",
    "lam_smooth": "Smoothing penalty used by hybrid methods.",
    "mask_initial_peaks": "Mask likely peaks before iterative polynomial fitting.",
    "max_half_window": "Maximum local window radius used by iterative smoothing methods.",
    "max_iter": "Maximum number of refinement iterations.",
    "max_iter_2": "Secondary maximum iteration count for nested optimization.",
    "min_half_window": "Minimum local window radius.",
    "num_bins": "Number of histogram bins used by mixture-model fitting.",
    "num_knots": "Number of spline knots; higher values allow more flexible baselines.",
    "num_smooths": "Number of repeated smoothing passes.",
    "num_std": "Standard-deviation multiplier for robust peak rejection.",
    "normalize_weights": "Normalize weights during iterative reweighting.",
    "original_criteria": "Use the original IPSA stopping criteria.",
    "p": "Asymmetry or penalty balance; lower values suppress positive peaks more strongly.",
    "pad_kwargs": "Advanced padding options passed to pybaselines.",
    "peak_ratio": "Relative peak weighting ratio for Goldindec.",
    "poly_order": "Polynomial degree used to model the baseline.",
    "quantile": "Target quantile for quantile-based baseline fitting.",
    "return_coef": "Return fitted coefficients in the pybaselines metadata.",
    "robust_opening": "Use robust morphological opening in JBCD.",
    "roi": "Region of interest for the algorithm.",
    "scale": "LOESS robust weighting scale.",
    "sections": "Sections used for piecewise peak filling.",
    "side": "Side used for edge extension or peak modeling.",
    "sigma": "Noise scale estimate.",
    "sigma_scale": "Ria Gaussian-width scale factor.",
    "smooth_half_window": "Optional smoothing window radius.",
    "spline_degree": "Spline polynomial degree.",
    "symmetric": "Use symmetric weighting.",
    "symmetric_weights": "Use symmetric robust weights.",
    "threshold": "Residual threshold for robust weighting.",
    "tol": "Convergence tolerance; smaller values may run longer.",
    "tol_2": "Secondary convergence tolerance.",
    "tol_3": "Tertiary convergence tolerance.",
    "total_points": "Total points used by the local regression.",
    "use_original": "Use the original data during iterative fitting.",
    "use_threshold": "Use an explicit threshold for robust weighting.",
    "weights": "Optional per-point weights.",
    "width_scale": "Ria peak-width scaling factor.",
    "window_kwargs": "Advanced morphological window options passed to pybaselines.",
}

_INT_PARAMS = {
    "diff_order",
    "filter_order",
    "max_half_window",
    "max_iter",
    "max_iter_2",
    "min_half_window",
    "num_bins",
    "num_knots",
    "num_smooths",
    "poly_order",
    "sections",
    "spline_degree",
    "total_points",
}
_BOOLEAN_PARAMS = {
    "conserve_memory",
    "decreasing",
    "fit_parabola",
    "mask_initial_peaks",
    "normalize_weights",
    "original_criteria",
    "return_coef",
    "robust_opening",
    "symmetric",
    "symmetric_weights",
    "use_original",
    "use_threshold",
}
_STRING_PARAMS = {"interp_method", "side"}
_JSON_PARAMS = {"baseline_points", "pad_kwargs", "roi", "sections", "weights", "window_kwargs"}
_HIDDEN_PARAMS = _JSON_PARAMS | {"return_coef"}
_OPTIONS: dict[str, tuple[str, ...]] = {
    "side": ("both", "left", "right"),
    "interp_method": ("linear", "nearest", "zero", "slinear", "quadratic", "cubic"),
}


def _kind_for_param(key: str, default: Any) -> ParamKind:
    if key in _JSON_PARAMS:
        return "json"
    if key in _BOOLEAN_PARAMS or isinstance(default, bool):
        return "boolean"
    if key in _INT_PARAMS or (isinstance(default, int) and not isinstance(default, bool)):
        return "int"
    if key in _STRING_PARAMS or isinstance(default, str):
        return "string"
    return "number"


def _param(key: str, default: Any, primary: set[str]) -> BaselineParamSpec:
    ui_role: UiRole = "hidden" if key in _HIDDEN_PARAMS else "primary" if key in primary else "advanced"
    return BaselineParamSpec(
        key=key,
        kind=_kind_for_param(key, default),
        default=default,
        nullable=default is None,
        ui_role=ui_role,
        description=_PARAM_DESCRIPTIONS.get(key, f"pybaselines parameter `{key}`."),
        options=_OPTIONS.get(key, ()),
    )


def _method(
    method_id: str,
    category: str,
    params: list[tuple[str, Any]],
    *,
    primary: tuple[str, ...] = (),
    ui_enabled: bool = True,
) -> BaselineMethodSpec:
    primary_set = set(primary)
    return BaselineMethodSpec(
        id=method_id,
        category=category,
        label=method_id,
        params=tuple(_param(key, default, primary_set) for key, default in params),
        ui_enabled=ui_enabled,
    )


BASELINE_METHOD_SPECS: tuple[BaselineMethodSpec, ...] = (
    # Whittaker
    _method("asls", "whittaker", [("lam", 1_000_000.0), ("p", 0.01), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "p")),
    _method("iasls", "whittaker", [("lam", 1_000_000.0), ("p", 0.01), ("lam_1", 0.0001), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("diff_order", 2)], primary=("lam", "p")),
    _method("airpls", "whittaker", [("lam", 1_000_000.0), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("normalize_weights", False)], primary=("lam",)),
    _method("arpls", "whittaker", [("lam", 100_000.0), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam",)),
    _method("drpls", "whittaker", [("lam", 100_000.0), ("eta", 0.5), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("diff_order", 2)], primary=("lam",)),
    _method("iarpls", "whittaker", [("lam", 100_000.0), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam",)),
    _method("aspls", "whittaker", [("lam", 100_000.0), ("diff_order", 2), ("max_iter", 100), ("tol", 0.001), ("weights", None), ("alpha", None), ("asymmetric_coef", 0.5)], primary=("lam",)),
    _method("psalsa", "whittaker", [("lam", 100_000.0), ("p", 0.5), ("k", None), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "p")),
    _method("derpsalsa", "whittaker", [("lam", 1_000_000.0), ("p", 0.01), ("k", None), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("smooth_half_window", None), ("num_smooths", 16), ("pad_kwargs", None)], primary=("lam", "p")),
    _method("brpls", "whittaker", [("lam", 100_000.0), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("max_iter_2", 50), ("tol_2", 0.001), ("weights", None)], primary=("lam",)),
    _method("lsrpls", "whittaker", [("lam", 100_000.0), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam",)),
    # Smoothing
    _method("noise_median", "smoothing", [("half_window", None), ("smooth_half_window", None), ("sigma", None), ("pad_kwargs", None)], primary=("half_window",)),
    _method("snip", "smoothing", [("max_half_window", None), ("decreasing", False), ("smooth_half_window", None), ("filter_order", 2), ("pad_kwargs", None)], primary=("max_half_window",)),
    _method("swima", "smoothing", [("min_half_window", 3), ("max_half_window", None), ("smooth_half_window", None), ("pad_kwargs", None)], primary=("min_half_window", "max_half_window")),
    _method("ipsa", "smoothing", [("half_window", None), ("max_iter", 500), ("tol", None), ("roi", None), ("original_criteria", False), ("pad_kwargs", None)], primary=("half_window",)),
    _method("ria", "smoothing", [("half_window", None), ("max_iter", 500), ("tol", 0.01), ("side", "both"), ("width_scale", 0.1), ("height_scale", 1.0), ("sigma_scale", 1.0 / 12.0), ("pad_kwargs", None)], primary=("half_window", "width_scale")),
    _method("peak_filling", "smoothing", [("half_window", None), ("sections", None), ("max_iter", 5), ("lam_smooth", None)], primary=("half_window",)),
    # Splines
    _method("mixture_model", "splines", [("lam", 100_000.0), ("p", 0.01), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 3), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("symmetric", False), ("num_bins", None)], primary=("lam", "p", "num_knots")),
    _method("irsqr", "splines", [("lam", 100), ("quantile", 0.05), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 3), ("max_iter", 100), ("tol", 1e-6), ("weights", None), ("eps", None)], primary=("lam", "num_knots")),
    _method("corner_cutting", "splines", [("max_iter", 100)], primary=("max_iter",)),
    _method("pspline_asls", "splines", [("lam", 1_000.0), ("p", 0.01), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "p", "num_knots")),
    _method("pspline_iasls", "splines", [("lam", 10.0), ("p", 0.01), ("lam_1", 0.0001), ("num_knots", 100), ("spline_degree", 3), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("diff_order", 2)], primary=("lam", "p", "num_knots")),
    _method("pspline_airpls", "splines", [("lam", 1_000.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("normalize_weights", False)], primary=("lam", "num_knots")),
    _method("pspline_arpls", "splines", [("lam", 1_000.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "num_knots")),
    _method("pspline_drpls", "splines", [("lam", 1_000.0), ("eta", 0.5), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "num_knots")),
    _method("pspline_iarpls", "splines", [("lam", 1_000.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "num_knots")),
    _method("pspline_aspls", "splines", [("lam", 10_000.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 100), ("tol", 0.001), ("weights", None), ("alpha", None), ("asymmetric_coef", 0.5)], primary=("lam", "num_knots")),
    _method("pspline_psalsa", "splines", [("lam", 1_000.0), ("p", 0.5), ("k", None), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "p", "num_knots")),
    _method("pspline_derpsalsa", "splines", [("lam", 100.0), ("p", 0.01), ("k", None), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None), ("smooth_half_window", None), ("num_smooths", 16), ("pad_kwargs", None)], primary=("lam", "p", "num_knots")),
    _method("pspline_mpls", "splines", [("half_window", None), ("lam", 1_000.0), ("p", 0.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("tol", None), ("max_iter", None), ("weights", None), ("window_kwargs", None)], primary=("half_window", "lam", "p", "num_knots")),
    _method("pspline_brpls", "splines", [("lam", 1_000.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("max_iter_2", 50), ("tol_2", 0.001), ("weights", None)], primary=("lam", "num_knots")),
    _method("pspline_lsrpls", "splines", [("lam", 1_000.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("max_iter", 50), ("tol", 0.001), ("weights", None)], primary=("lam", "num_knots")),
    # Polynomial
    _method("poly", "polynomial", [("poly_order", 2), ("weights", None), ("return_coef", False)], primary=("poly_order",)),
    _method("modpoly", "polynomial", [("poly_order", 2), ("tol", 0.001), ("max_iter", 250), ("weights", None), ("use_original", False), ("mask_initial_peaks", False), ("return_coef", False)], primary=("poly_order",)),
    _method("imodpoly", "polynomial", [("poly_order", 2), ("tol", 0.001), ("max_iter", 250), ("weights", None), ("use_original", False), ("mask_initial_peaks", True), ("return_coef", False), ("num_std", 1.0)], primary=("poly_order",)),
    _method("penalized_poly", "polynomial", [("poly_order", 2), ("tol", 0.001), ("max_iter", 250), ("weights", None), ("cost_function", "asymmetric_truncated_quadratic"), ("threshold", None), ("alpha_factor", 0.99), ("return_coef", False)], primary=("poly_order",)),
    _method("loess", "polynomial", [("fraction", 0.2), ("total_points", None), ("poly_order", 1), ("scale", 3.0), ("tol", 0.001), ("max_iter", 10), ("symmetric_weights", False), ("use_threshold", False), ("num_std", 1), ("use_original", False), ("weights", None), ("return_coef", False), ("conserve_memory", True), ("delta", None)], primary=("fraction", "poly_order")),
    _method("quant_reg", "polynomial", [("poly_order", 2), ("quantile", 0.05), ("tol", 1e-6), ("max_iter", 250), ("weights", None), ("eps", None), ("return_coef", False)], primary=("poly_order", "quantile")),
    _method("goldindec", "polynomial", [("poly_order", 2), ("tol", 0.001), ("max_iter", 250), ("weights", None), ("cost_function", "asymmetric_indec"), ("peak_ratio", 0.5), ("alpha_factor", 0.99), ("tol_2", 0.001), ("tol_3", 1e-6), ("max_iter_2", 100), ("return_coef", False)], primary=("poly_order",)),
    # Morphological
    _method("mpls", "morphological", [("half_window", None), ("lam", 1_000_000.0), ("p", 0.0), ("diff_order", 2), ("tol", None), ("max_iter", None), ("weights", None), ("window_kwargs", None)], primary=("half_window", "lam", "p")),
    _method("mor", "morphological", [("half_window", None), ("window_kwargs", None)], primary=("half_window",)),
    _method("imor", "morphological", [("half_window", None), ("tol", 0.001), ("max_iter", 200), ("window_kwargs", None)], primary=("half_window",)),
    _method("mormol", "morphological", [("half_window", None), ("tol", 0.001), ("max_iter", 250), ("smooth_half_window", None), ("pad_kwargs", None), ("window_kwargs", None)], primary=("half_window",)),
    _method("amormol", "morphological", [("half_window", None), ("tol", 0.001), ("max_iter", 200), ("pad_kwargs", None), ("window_kwargs", None)], primary=("half_window",)),
    _method("rolling_ball", "morphological", [("half_window", None), ("smooth_half_window", None), ("pad_kwargs", None), ("window_kwargs", None)], primary=("half_window",)),
    _method("mwmv", "morphological", [("half_window", None), ("smooth_half_window", None), ("pad_kwargs", None), ("window_kwargs", None)], primary=("half_window",)),
    _method("tophat", "morphological", [("half_window", None), ("window_kwargs", None)], primary=("half_window",)),
    _method("mpspline", "morphological", [("half_window", None), ("lam", 10_000.0), ("lam_smooth", 0.01), ("p", 0.0), ("num_knots", 100), ("spline_degree", 3), ("diff_order", 2), ("weights", None), ("pad_kwargs", None), ("window_kwargs", None)], primary=("half_window", "lam", "p")),
    _method("jbcd", "morphological", [("half_window", None), ("alpha", 0.1), ("beta", 10.0), ("gamma", 1.0), ("beta_mult", 1.1), ("gamma_mult", 0.909), ("diff_order", 1), ("max_iter", 20), ("tol", 0.01), ("tol_2", 0.001), ("robust_opening", True), ("window_kwargs", None)], primary=("half_window",)),
    # Miscellaneous
    _method("interp_pts", "miscellaneous", [("baseline_points", ()), ("interp_method", "linear")], ui_enabled=False),
    _method("beads", "miscellaneous", [("freq_cutoff", 0.005), ("lam_0", 1.0), ("lam_1", 1.0), ("lam_2", 1.0), ("asymmetry", 6.0), ("filter_type", 1), ("cost_function", 2), ("max_iter", 50), ("tol", 0.01), ("eps_0", 1e-6), ("eps_1", 1e-6), ("fit_parabola", True), ("smooth_half_window", None)], primary=("freq_cutoff",)),
)

BASELINE_METHODS: dict[str, BaselineMethodSpec] = {spec.id: spec for spec in BASELINE_METHOD_SPECS}


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return value


def baseline_method_metadata() -> dict[str, Any]:
    """Return JSON-safe baseline category/method metadata for API and frontend use."""
    return {
        "categories": [{"id": c.id, "label": c.label} for c in BASELINE_CATEGORIES],
        "methods": [
            {
                "id": m.id,
                "label": m.label,
                "category": m.category,
                "ui_enabled": m.ui_enabled,
                "params": [
                    {
                        "key": p.key,
                        "kind": p.kind,
                        "default": _json_safe(p.default),
                        "nullable": p.nullable,
                        "ui_role": p.ui_role,
                        "description": p.description,
                        "options": list(p.options),
                    }
                    for p in m.params
                ],
            }
            for m in BASELINE_METHOD_SPECS
        ],
    }


def _coerce_param_value(param: BaselineParamSpec, value: Any) -> Any:
    if value is None:
        if param.nullable or param.kind == "json":
            return None
        raise ValueError(f"baseline param {param.key!r} does not allow null")
    if param.kind == "json":
        return value
    if param.kind == "boolean":
        if isinstance(value, str):
            if value.lower() in {"true", "1", "yes", "on"}:
                return True
            if value.lower() in {"false", "0", "no", "off"}:
                return False
            raise ValueError(f"baseline param {param.key!r} must be boolean")
        return bool(value)
    if param.kind == "int":
        return int(value)
    if param.kind == "number":
        return float(value)
    return str(value)


def baseline_kwargs(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Filter and coerce params for a cataloged pybaselines method."""
    method_id = str(method or "derpsalsa").lower()
    spec = BASELINE_METHODS.get(method_id)
    if spec is None:
        raise ValueError(f"Unknown baseline correction method: {method}")
    supplied = dict(params or {})
    out: dict[str, Any] = {}
    for param in spec.params:
        value = supplied[param.key] if param.key in supplied else param.default
        out[param.key] = _coerce_param_value(param, value)
    return out


def baseline_signature_drift() -> list[str]:
    """Compare the curated catalog against the installed pybaselines signatures."""
    try:
        from pybaselines import Baseline  # type: ignore
    except Exception as e:
        return [f"pybaselines import failed: {e}"]

    issues: list[str] = []
    for spec in BASELINE_METHOD_SPECS:
        func = getattr(Baseline, spec.id, None)
        if func is None:
            issues.append(f"{spec.id}: missing from pybaselines.Baseline")
            continue
        sig = inspect.signature(func)
        actual = [
            name
            for name, p in sig.parameters.items()
            if name not in {"self", "data"} and p.kind is not inspect.Parameter.VAR_KEYWORD
        ]
        expected = [p.key for p in spec.params]
        if actual != expected:
            issues.append(f"{spec.id}: expected params {expected!r}, installed signature has {actual!r}")
    return issues


def correct_baseline(intensity: np.ndarray, method: str = "derpsalsa", **kwargs: Any) -> tuple[np.ndarray, dict]:
    """
    Apply pybaselines baseline correction to a spectrum using the SERSFlow baseline catalog.

    All supported baseline methods, including Whittaker, smoothing, spline, polynomial,
    morphological, and miscellaneous methods, dispatch through the same catalog-driven path.
    """
    try:
        from pybaselines import Baseline  # type: ignore
    except Exception as e:
        # Common on Windows when llvmlite/numba native libs are missing/incompatible.
        raise ImportError(
            "Baseline correction requires optional dependency 'pybaselines'. "
            "In this environment it failed to import (often due to numba/llvmlite native libraries). "
            "Either install a compatible pybaselines/numba/llvmlite stack, or disable the baseline step."
        ) from e

    method_id = str(method or "derpsalsa").lower()
    if method_id not in BASELINE_METHODS:
        raise ValueError(f"Unknown baseline correction method: {method}")

    fitter = Baseline()
    try:
        method_func = getattr(fitter, method_id)
    except AttributeError as e:
        raise ValueError(f"Baseline method {method_id!r} is not available in installed pybaselines") from e

    baseline, params = method_func(np.asarray(intensity, dtype=float), **baseline_kwargs(method_id, kwargs))
    corrected_int = np.asarray(intensity, dtype=float) - baseline
    params["baseline"] = baseline
    return corrected_int, params