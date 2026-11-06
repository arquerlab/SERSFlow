"""Fit one spectrum under one design cell: patches, multi-start, diagnostics, common-window score.

``fit_cell`` returns a JSON-serialisable record (parameters, fit mapping, responses, diagnostics, start spread), so a
study can be re-analysed (other responses, filters, ANOVA order) from the records alone, without refitting.

Multi-start
    Start 0 is the nominal p0 of the cell; starts 1..K-1 jitter the free parameters inside their bounds (seeded from
    ``(seed, spectrum_id, cell_id)``, so the result does not depend on worker scheduling). The start with the lowest
    chi2 is kept. Other starts whose chi2 is within ``cost_tol`` (relative) of the best but whose response differs by
    more than ``max(resp_tol_abs, resp_tol_rel*|best|)`` mark the cell ``degenerate``: the data cannot decide between
    those solutions (e.g. two oxidation states trading area).

Common-window score
    BIC / rmse / chi2 recomputed on the residuals restricted to the window shared by ALL cells of the study. Fits of
    different fit windows have different numbers of points, so their native BIC is not comparable; the common-window
    score is. It is also only comparable between cells whose input y is the same (same ``upstream_key``): an upstream
    baseline or normalisation change rescales y, which ``comparability_group`` makes explicit.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import replace
from typing import Any

import numpy as np

from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params, parse_fit_window
from sersflow.core.robustness.patches import apply_fit_patches, _keys, _n_params
from sersflow.core.robustness.responses import evaluate_responses


def _fin(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def mapping_to_json(mapping: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in mapping:
        row = {
            "component_id": str(m.get("component_id")),
            "component_type": str(m.get("component_type")),
            "param_keys": [str(k) for k in (m.get("param_keys") or [])],
            "index_range": [int(v) for v in (m.get("index_range") or [0, 0])],
        }
        if m.get("x_window"):
            row["x_window"] = [float(v) for v in m["x_window"]]
        out.append(row)
    return out


def window_of(step_params: dict[str, Any]) -> tuple[float, float]:
    """(lo, hi) of the fit window; unbounded sides are -inf / +inf."""
    lo, hi = parse_fit_window(step_params)
    return (-math.inf if lo is None else lo, math.inf if hi is None else hi)


def common_window(base_params: dict[str, Any], cells_fit_patches: list[tuple[dict[str, Any], ...]]) -> tuple[float, float]:
    """Intersection of the fit windows of every cell (after its fit patches)."""
    lo, hi = -math.inf, math.inf
    for patches in cells_fit_patches:
        w_lo, w_hi = window_of(apply_fit_patches(base_params, list(patches)))
        lo, hi = max(lo, w_lo), min(hi, w_hi)
    return lo, hi


def jitter_params(step_params: dict[str, Any], rng: np.random.Generator, frac: float) -> dict[str, Any]:
    """Copy of the step params with the free parameters displaced inside their bounds."""
    out = dict(step_params)
    comps = out.get("components") or []
    p0 = [float(v) for v in out["p0"]]
    lo = out.get("bounds_lower") or [None] * len(p0)
    hi = out.get("bounds_upper") or [None] * len(p0)
    vary = out.get("vary") or [True] * len(p0)
    off = 0
    for c in comps:
        keys = _keys(c)
        for j, key in enumerate(keys):
            i = off + j
            if not vary[i]:
                continue
            lo_i = None if lo[i] is None else float(lo[i])
            hi_i = None if hi[i] is None else float(hi[i])
            if lo_i is not None and hi_i is not None and hi_i > lo_i:
                v = p0[i] + rng.normal(0.0, frac * (hi_i - lo_i))
            elif p0[i] != 0.0:
                v = p0[i] * (1.0 + rng.normal(0.0, frac))
            else:
                v = p0[i] + rng.normal(0.0, frac)
            if lo_i is not None:
                v = max(v, lo_i)
            if hi_i is not None:
                v = min(v, hi_i)
            p0[i] = float(v)
        off += _n_params(c)
    out["p0"] = p0
    return out


def _common_window_score(
    x: np.ndarray, y: np.ndarray, y_hat: np.ndarray, sigma: np.ndarray | None, n_vary: int, window: tuple[float, float]
) -> dict[str, float | None]:
    m = (x >= window[0]) & (x <= window[1]) & np.isfinite(y_hat) & np.isfinite(y)
    n = int(m.sum())
    if n < 3:
        return {"n_common": n, "rmse_common": None, "chi2_common": None, "bic_common": None, "aic_common": None}
    r = (y - y_hat)[m]
    if sigma is not None and np.all(np.asarray(sigma)[m] > 0):
        r = r / np.asarray(sigma)[m]
    chi2 = float(r @ r)
    rmse = float(np.sqrt(np.mean(((y - y_hat)[m]) ** 2)))
    if chi2 <= 0:
        return {"n_common": n, "rmse_common": rmse, "chi2_common": chi2, "bic_common": None, "aic_common": None}
    k = max(int(n_vary), 1)
    return {
        "n_common": n,
        "rmse_common": rmse,
        "chi2_common": chi2,
        "bic_common": float(n * math.log(chi2 / n) + k * math.log(n)),
        "aic_common": float(n * math.log(chi2 / n) + 2 * k),
    }


def fit_cell(
    xy: Any,
    base_params: dict[str, Any],
    fit_patches: list[dict[str, Any]],
    *,
    spectrum_id: str,
    cell_id: str,
    responses: list[dict[str, Any]],
    n_starts: int = 1,
    seed: int = 0,
    window: tuple[float, float] | None = None,
    jitter_frac: float = 0.15,
    cost_tol: float = 0.005,
    resp_tol_rel: float = 0.02,
    resp_tol_abs: float = 1e-3,
) -> dict[str, Any]:
    """Fit ``xy`` with ``base_params`` + ``fit_patches``; JSON-safe record (never raises)."""
    rec: dict[str, Any] = {"spectrum_id": spectrum_id, "cell_id": cell_id, "error": None}
    try:
        params = apply_fit_patches(base_params, list(fit_patches))
        prob = fit_problem_from_step_params(xy, params)
        if prob is None:
            raise ValueError("empty spectrum / fit window")
        n_starts = max(1, int(n_starts))
        ss = np.random.SeedSequence([int(seed) & 0xFFFFFFFF, zlib.crc32(spectrum_id.encode()), zlib.crc32(cell_id.encode())])
        rng = np.random.default_rng(ss)
        starts: list[dict[str, Any]] = []
        best = None
        for k in range(n_starts):
            try:
                pk = params if k == 0 else jitter_params(params, rng, jitter_frac)
                pr = prob if k == 0 else replace(prob, p0=[float(v) for v in pk["p0"]])
                res = fit_curve(pr)
                chi2 = _fin(res.diagnostics.chi2)
                ok = chi2 is not None
                resp = evaluate_responses(responses, res.mapping, res.p_opt) if ok else {}
                starts.append({"start": k, "chi2": chi2, "responses": resp, "success": bool(res.diagnostics.success)})
                if ok and (best is None or chi2 < best[1]):
                    best = (res, chi2, k, pr)
            except Exception as e:  # a failed start must not lose the others
                starts.append({"start": k, "chi2": None, "responses": {}, "error": f"{type(e).__name__}: {e}"})
        if best is None:
            raise ValueError("; ".join(s.get("error", "no finite chi2") for s in starts)[:300])
        res, chi2_best, k_best, pr = best
        d = res.diagnostics
        n_vary = int(d.n_vary) if d.n_vary is not None else 0
        resp_best = starts[k_best]["responses"]

        # Degeneracy: near-equal cost, different answer.
        equiv = [
            s
            for s in starts
            if s["chi2"] is not None and s["start"] != k_best and s["chi2"] <= chi2_best * (1.0 + cost_tol) + 1e-300
        ]
        degenerate_on: list[str] = []
        spread: dict[str, float] = {}
        for name, vb in resp_best.items():
            if vb is None:
                continue
            vals = [vb] + [s["responses"].get(name) for s in equiv if s["responses"].get(name) is not None]
            sp = float(max(vals) - min(vals))
            spread[name] = sp
            if sp > max(resp_tol_abs, resp_tol_rel * abs(vb)):
                degenerate_on.append(name)

        x = np.asarray(pr.x, dtype=float)
        y = np.asarray(pr.y, dtype=float)
        y_hat = np.asarray(res.y_hat, dtype=float)
        rec.update(
            {
                "p_opt": [float(v) for v in np.asarray(res.p_opt, dtype=float)],
                "mapping": mapping_to_json(res.mapping),
                "responses": resp_best,
                "best_start": k_best,
                "n_starts": n_starts,
                "n_starts_ok": sum(1 for s in starts if s["chi2"] is not None),
                "n_equivalent_starts": len(equiv),
                "degenerate": bool(degenerate_on),
                "degenerate_responses": degenerate_on,
                "start_spread": spread,
                "start_chi2": [s["chi2"] for s in starts],
                "x_lo": float(x.min()),
                "x_hi": float(x.max()),
                "n_points": int(x.size),
                "weighting": d.weighting,
                "rmse": _fin(d.rmse),
                "chi2": chi2_best,
                "bic": _fin(d.bic),
                "aic": _fin(d.aic),
                "n_vary": n_vary,
                "n_at_bound": _fin(d.n_at_bound),
                "bg_gt_data_frac": _fin(d.bg_gt_data_frac),
                "resid_lag1_autocorr": _fin(d.resid_lag1_autocorr),
                "resid_mean_edge_lo": _fin(d.resid_mean_edge_lo),
                "resid_mean_edge_hi": _fin(d.resid_mean_edge_hi),
                "success": bool(d.success),
            }
        )
        if window is not None:
            rec.update(_common_window_score(x, y, y_hat, pr.sigma, n_vary, window))
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec
