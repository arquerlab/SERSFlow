"""
Parameter uncertainties of a fit (F2).

Two estimates, as in CasaXPS:

* **Covariance** (every fit): 1-sigma standard errors from lmfit's covariance (scaled by the reduced chi2),
  propagated to peak areas and %area with a numerical Jacobian, so links (ratios, shared FWHM) are honoured.
* **Monte Carlo** (on demand): the best fit is taken as the truth, noise from the fit's own noise model is added
  ``n_replicates`` times, every replicate is refitted (backgrounds such as Shirley are recomputed each time) and
  the spread of each parameter, area and %area is reported. This also captures background and peak-overlap
  uncertainty that the linearised covariance misses.

``%area`` = component area / sum of the areas of all area-exporting peaks of the same fitting step x 100
(backgrounds and infinite-area tails such as DS are not part of the sum).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable

import numpy as np

from sersflow.core.preprocess.fitting import FitProblem, FitResult, fit_curve
from sersflow.core.preprocess.fitting_specs import AREA_EXPORT_COMPONENT_TYPES


def _component_param_dict(mapping_row: dict[str, Any], p: np.ndarray) -> dict[str, float]:
    keys = list(mapping_row.get("param_keys") or [])
    start, end = mapping_row.get("index_range", [0, 0])
    sl = np.asarray(p, dtype=float)[int(start) : int(end)]
    return {keys[j]: float(sl[j]) for j in range(min(len(keys), len(sl)))}


def component_areas(mapping: list[dict[str, Any]], p: np.ndarray) -> list[float | None]:
    """Area of each component (None for components without a finite area export)."""
    from sersflow.core.metrics.fitting_features import _derived_peak_area

    out: list[float | None] = []
    for m in mapping:
        ctype = str(m.get("component_type", "")).strip().lower()
        if ctype not in AREA_EXPORT_COMPONENT_TYPES:
            out.append(None)
            continue
        out.append(_derived_peak_area(ctype, _component_param_dict(m, p)))
    return out


def area_percentages(areas: list[float | None]) -> list[float | None]:
    """%area of each area-exporting component within the step (None where no area)."""
    vals = [a for a in areas if a is not None and math.isfinite(a)]
    total = float(sum(vals)) if vals else 0.0
    if not vals or total == 0.0 or not math.isfinite(total):
        return [None for _ in areas]
    return [None if a is None or not math.isfinite(a) else 100.0 * float(a) / total for a in areas]


@dataclass(frozen=True)
class AreaUncertainty:
    area: list[float | None]
    area_stderr: list[float | None]
    area_pct: list[float | None]
    area_pct_stderr: list[float | None]


def area_uncertainty(mapping: list[dict[str, Any]], p_opt: np.ndarray, p_cov: np.ndarray | None) -> AreaUncertainty:
    """Areas, %area and their covariance-propagated 1-sigma errors (J C J^T, central differences)."""
    p = np.asarray(p_opt, dtype=float).ravel()
    areas = component_areas(mapping, p)
    pct = area_percentages(areas)
    n_c = len(areas)
    none: list[float | None] = [None] * n_c
    if p_cov is None:
        return AreaUncertainty(areas, list(none), pct, list(none))
    cov = np.asarray(p_cov, dtype=float)
    if cov.shape != (p.size, p.size):
        return AreaUncertainty(areas, list(none), pct, list(none))
    active = [i for i in range(p.size) if math.isfinite(cov[i, i]) and cov[i, i] > 0]
    if not active:
        return AreaUncertainty(areas, list(none), pct, list(none))

    def g(pp: np.ndarray) -> np.ndarray:
        a = component_areas(mapping, pp)
        pc = area_percentages(a)
        return np.array(
            [np.nan if v is None else float(v) for v in a] + [np.nan if v is None else float(v) for v in pc],
            dtype=float,
        )

    jac = np.zeros((2 * n_c, len(active)), dtype=float)
    for j, i in enumerate(active):
        h = 1e-5 * max(abs(p[i]), math.sqrt(cov[i, i]), 1e-9)
        hi_p, lo_p = p.copy(), p.copy()
        hi_p[i] += h
        lo_p[i] -= h
        jac[:, j] = (g(hi_p) - g(lo_p)) / (2.0 * h)
    c = cov[np.ix_(active, active)]
    var = np.einsum("ij,jk,ik->i", jac, c, jac)

    def se(k: int, base: list[float | None]) -> float | None:
        if base[k % n_c] is None:
            return None
        v = float(var[k])
        return math.sqrt(v) if math.isfinite(v) and v >= 0 else None

    return AreaUncertainty(
        area=areas,
        area_stderr=[se(k, areas) for k in range(n_c)],
        area_pct=pct,
        area_pct_stderr=[se(n_c + k, pct) for k in range(n_c)],
    )


def _fin(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def component_uncertainty_rows(res: FitResult) -> list[dict[str, Any]]:
    """Per component: ``stderr`` {param: 1-sigma}, ``area``, ``area_stderr``, ``area_pct``, ``area_pct_stderr``."""
    unc = area_uncertainty(res.mapping, res.p_opt, res.p_cov)
    se = res.p_stderr
    rows: list[dict[str, Any]] = []
    for ci, m in enumerate(res.mapping):
        keys = list(m.get("param_keys") or [])
        s, _e = m.get("index_range", [0, 0])
        rows.append(
            {
                "stderr": {
                    k: (_fin(se[int(s) + j]) if se is not None and int(s) + j < len(se) else None)
                    for j, k in enumerate(keys)
                },
                "area": _fin(unc.area[ci]),
                "area_stderr": _fin(unc.area_stderr[ci]),
                "area_pct": _fin(unc.area_pct[ci]),
                "area_pct_stderr": _fin(unc.area_pct_stderr[ci]),
            }
        )
    return rows


# --------------------------------------------------------------------------------------------- Monte Carlo


def monte_carlo_noise_sigma(problem: FitProblem, res: FitResult) -> tuple[np.ndarray, str]:
    """
    Per-point noise sigma for Monte Carlo replicates, following the fit's own noise model (user decision F2).

    poisson: sigma = sqrt(raw counting variance); poisson_relative: sqrt(g * y) with the fitted gain g;
    unweighted: constant sigma = RMSE of the fit. Gaussian draws approximate Poisson (fine above ~20 counts).
    """
    d = res.diagnostics
    n = int(np.asarray(problem.y).size)
    w = str(getattr(d, "weighting", "none") or "none")
    if w == "poisson" and problem.sigma is not None:
        return np.asarray(problem.sigma, dtype=float), "Poisson: sigma = sqrt(raw counts)"
    if w == "poisson_relative" and problem.sigma is not None:
        g_raw = getattr(d, "poisson_gain", None)
        g = float(g_raw) if g_raw is not None and math.isfinite(float(g_raw)) and float(g_raw) > 0 else 1.0
        return math.sqrt(g) * np.asarray(problem.sigma, dtype=float), f"relative Poisson: sigma^2 = g*y, g = {g:.4g}"
    rmse = float(getattr(d, "rmse", float("nan")))
    if not math.isfinite(rmse) or rmse <= 0:
        raise ValueError("cannot build a Monte Carlo noise model: fit RMSE is not finite")
    return np.full(n, rmse, dtype=float), f"unweighted: constant sigma = RMSE = {rmse:.4g}"


@dataclass
class MonteCarloResult:
    n_requested: int
    n_ok: int
    seed: int
    noise_model: str
    p_opt: np.ndarray
    p_stderr: np.ndarray | None
    params: np.ndarray
    """(n_ok, n_params) refitted parameter vectors."""
    areas: np.ndarray
    """(n_ok, n_components) areas (NaN where a component has no area)."""
    area_pct: np.ndarray
    errors: list[str] = field(default_factory=list)


def spread(values: np.ndarray) -> dict[str, float | None]:
    """Mean, SD (ddof=1) and 2.5/50/97.5 percentiles of the finite values."""
    v = np.asarray(values, dtype=float).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"mean": None, "sd": None, "p2_5": None, "p50": None, "p97_5": None}
    q = np.percentile(v, [2.5, 50.0, 97.5])
    return {
        "mean": float(np.mean(v)),
        "sd": float(np.std(v, ddof=1)) if v.size > 1 else None,
        "p2_5": float(q[0]),
        "p50": float(q[1]),
        "p97_5": float(q[2]),
    }


def run_monte_carlo(
    problem: FitProblem,
    res: FitResult,
    *,
    n_replicates: int = 100,
    seed: int = 0,
    progress: Callable[[int, int], None] | None = None,
) -> MonteCarloResult:
    """Refit ``n_replicates`` noisy copies of the best-fit curve and collect the parameter spread."""
    n_rep = int(n_replicates)
    if n_rep < 2:
        raise ValueError("n_replicates must be at least 2")
    sigma, note = monte_carlo_noise_sigma(problem, res)
    rng = np.random.default_rng(int(seed))
    y_hat = np.asarray(res.y_hat, dtype=float)
    base = replace(
        problem, p0=[float(v) for v in res.p_opt], initial_guess_mode="default", initial_area_ratios=None
    )
    rows_p: list[np.ndarray] = []
    rows_a: list[list[float]] = []
    rows_pct: list[list[float]] = []
    errors: list[str] = []
    for k in range(n_rep):
        y_star = y_hat + rng.normal(0.0, 1.0, size=y_hat.shape) * sigma
        try:
            r = fit_curve(replace(base, y=y_star))
            p = np.asarray(r.p_opt, dtype=float)
            a = component_areas(r.mapping, p)
            pc = area_percentages(a)
            rows_p.append(p)
            rows_a.append([np.nan if v is None else float(v) for v in a])
            rows_pct.append([np.nan if v is None else float(v) for v in pc])
        except Exception as e:  # one bad replicate must not kill the run
            errors.append(f"replicate {k}: {type(e).__name__}: {e}")
        if progress is not None:
            progress(k + 1, n_rep)
    n_par = int(np.asarray(res.p_opt).size)
    n_c = len(res.mapping)
    return MonteCarloResult(
        n_requested=n_rep,
        n_ok=len(rows_p),
        seed=int(seed),
        noise_model=note,
        p_opt=np.asarray(res.p_opt, dtype=float),
        p_stderr=None if res.p_stderr is None else np.asarray(res.p_stderr, dtype=float),
        params=np.vstack(rows_p) if rows_p else np.zeros((0, n_par)),
        areas=np.asarray(rows_a, dtype=float) if rows_a else np.zeros((0, n_c)),
        area_pct=np.asarray(rows_pct, dtype=float) if rows_pct else np.zeros((0, n_c)),
        errors=errors,
    )
