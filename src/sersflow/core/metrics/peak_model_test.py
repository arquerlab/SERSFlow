"""
"Test peak model" (S1, CasaXPS Cookbook p.119-125) on one spectrum.

* ``scan_parameter``: fix one parameter (or the same parameter of every component of a type, e.g. GL ``m`` of all
  peaks) at each value of a grid and refit; report chi2 / reduced chi2 / RMSE / BIC and every component's area and
  %area per grid value. A flat chi2 with moving %area flags an unstable component.
* ``noise_replicates``: the F2 Monte Carlo engine (refit noisy copies of the best fit); report the %area and parameter
  spread per component plus a few replicate component curves for an overlay.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from sersflow.core.metrics.fit_uncertainty import area_percentages, component_areas, run_monte_carlo, spread
from sersflow.core.metrics.fitting_features import _param_keys_for_component
from sersflow.core.preprocess.fitting import fit_curve, fit_problem_from_step_params
from sersflow.core.spectrum import XY

MAX_SCAN_POINTS = 101
MAX_REPLICATES = 500


def _fin(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def scan_targets(step_params: dict[str, Any], key: str, component_id: str | None, component_type: str | None) -> list[int]:
    """Flat indices of the scanned parameter: one component, or every component (of a type) having ``key``."""
    comps = [c for c in (step_params.get("components") or []) if isinstance(c, dict)]
    out: list[int] = []
    cursor = 0
    for c in comps:
        keys = _param_keys_for_component(c)
        cid = str(c.get("component_id"))
        ctype = str(c.get("component_type") or "").strip().lower()
        hit = key in keys and (
            (component_id is not None and cid == component_id)
            or (component_id is None and (component_type is None or ctype == component_type.strip().lower()))
        )
        if hit:
            out.append(cursor + keys.index(key))
        cursor += len(keys)
    if not out:
        who = component_id or (f"components of type {component_type}" if component_type else "any component")
        raise ValueError(f"no parameter {key!r} on {who}")
    return out


def _fixed_at(step_params: dict[str, Any], idx: list[int], value: float) -> dict[str, Any]:
    out = copy.deepcopy(step_params)
    n = len(out.get("p0") or [])
    p0 = list(out["p0"])
    lo = list(out.get("bounds_lower") or [None] * n)
    hi = list(out.get("bounds_upper") or [None] * n)
    vary = list(out.get("vary") or [True] * n)
    for i in idx:
        p0[i] = float(value)
        vary[i] = False
        if lo[i] is not None:
            lo[i] = min(float(lo[i]), float(value))
        if hi[i] is not None:
            hi[i] = max(float(hi[i]), float(value))
    # A scanned parameter must not also be defined by a link.
    keys_by_idx = _index_keys(out)
    scanned = {keys_by_idx[i] for i in idx}
    out["param_links"] = [
        lk for lk in (out.get("param_links") or []) if (lk.get("source_component_id"), lk.get("source_key")) not in scanned
    ]
    out.update({"p0": p0, "bounds_lower": lo, "bounds_upper": hi, "vary": vary})
    return out


def _index_keys(step_params: dict[str, Any]) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    cursor = 0
    for c in step_params.get("components") or []:
        keys = _param_keys_for_component(c)
        for j, k in enumerate(keys):
            out[cursor + j] = (str(c.get("component_id")), k)
        cursor += len(keys)
    return out


def scan_parameter(
    xy: XY,
    step_params: dict[str, Any],
    *,
    key: str,
    values: list[float],
    component_id: str | None = None,
    component_type: str | None = None,
) -> dict[str, Any]:
    vals = [float(v) for v in values]
    if not vals or len(vals) > MAX_SCAN_POINTS or not all(math.isfinite(v) for v in vals):
        raise ValueError(f"scan needs 1..{MAX_SCAN_POINTS} finite values")
    idx = scan_targets(step_params, key, component_id, component_type)
    names = _index_keys(step_params)
    points: list[dict[str, Any]] = []
    comp_ids: list[str] = []
    for v in vals:
        row: dict[str, Any] = {"value": v, "error": None}
        try:
            prob = fit_problem_from_step_params(xy, _fixed_at(step_params, idx, v))
            if prob is None:
                raise ValueError("empty spectrum / fit window")
            res = fit_curve(prob)
            d = res.diagnostics
            areas = component_areas(res.mapping, res.p_opt)
            pct = area_percentages(areas)
            comp_ids = [str(m["component_id"]) for m in res.mapping]
            row.update(
                {
                    "chi2": _fin(d.chi2),
                    "redchi": _fin(d.redchi),
                    "rmse": _fin(d.rmse),
                    "bic": _fin(d.bic),
                    "success": bool(d.success),
                    "n_at_bound": d.n_at_bound,
                    "area": {cid: _fin(a) for cid, a in zip(comp_ids, areas) if a is not None},
                    "area_pct": {cid: _fin(p) for cid, p in zip(comp_ids, pct) if p is not None},
                    "params": {f"{names[i][0]}.{names[i][1]}": _fin(res.p_opt[i]) for i in range(len(res.p_opt)) if i in names},
                }
            )
        except Exception as e:  # one failing grid value must not kill the scan
            row["error"] = f"{type(e).__name__}: {e}"
        points.append(row)
    ok = [p for p in points if p["error"] is None and p.get("chi2") is not None]
    best = min(ok, key=lambda p: p["chi2"]) if ok else None
    return {
        "mode": "scan",
        "key": key,
        "component_id": component_id,
        "component_type": component_type,
        "scanned": [f"{names[i][0]}.{names[i][1]}" for i in idx],
        "points": points,
        "best_value": best["value"] if best else None,
        "component_ids": comp_ids,
    }


def noise_replicates(
    xy: XY,
    step_params: dict[str, Any],
    *,
    n_replicates: int = 50,
    seed: int = 0,
    n_overlay: int = 20,
) -> dict[str, Any]:
    if not (2 <= int(n_replicates) <= MAX_REPLICATES):
        raise ValueError(f"n_replicates must be 2..{MAX_REPLICATES}")
    prob = fit_problem_from_step_params(xy, step_params)
    if prob is None:
        raise ValueError("empty spectrum / fit window")
    res = fit_curve(prob)
    mc = run_monte_carlo(prob, res, n_replicates=int(n_replicates), seed=int(seed))
    comp_ids = [str(m["component_id"]) for m in res.mapping]
    names = _index_keys(step_params)
    best_areas = component_areas(res.mapping, res.p_opt)
    best_pct = area_percentages(best_areas)
    components = []
    for ci, cid in enumerate(comp_ids):
        if best_areas[ci] is None:
            continue
        components.append(
            {
                "component_id": cid,
                "area_pct_best": _fin(best_pct[ci]),
                "area_pct": [_fin(v) for v in (mc.area_pct[:, ci].tolist() if mc.n_ok else [])],
                "area_pct_spread": spread(mc.area_pct[:, ci]) if mc.n_ok else None,
            }
        )
    params = []
    for i in range(len(res.p_opt)):
        col = mc.params[:, i] if mc.n_ok else np.array([])
        sp = spread(col)
        if sp["sd"] in (None, 0.0) and (res.p_stderr is None or not np.isfinite(res.p_stderr[i])):
            continue
        cid, key = names.get(i, ("?", str(i)))
        params.append(
            {
                "name": f"{cid}.{key}",
                "best": _fin(res.p_opt[i]),
                "stderr_cov": _fin(res.p_stderr[i]) if res.p_stderr is not None else None,
                **{f"mc_{k}": v for k, v in sp.items()},
            }
        )
    # Overlay: component curves of the first replicates (evaluated from their parameters).
    from sersflow.core.preprocess.fitting import evaluate_fit_curves

    overlay = []
    for r in range(min(int(n_overlay), mc.n_ok)):
        try:
            ev = evaluate_fit_curves(prob, mc.params[r])
            overlay.append({cid: np.asarray(c, dtype=float).tolist() for cid, c in zip(comp_ids, ev.component_y_hat)})
        except Exception:
            break
    return {
        "mode": "noise",
        "n_requested": mc.n_requested,
        "n_ok": mc.n_ok,
        "seed": int(seed),
        "noise_model": mc.noise_model,
        "x": np.asarray(prob.x, dtype=float).tolist(),
        "y": np.asarray(prob.y, dtype=float).tolist(),
        "best_y_hat": np.asarray(res.y_hat, dtype=float).tolist(),
        "components": components,
        "params": params,
        "overlay": overlay,
        "component_ids": comp_ids,
    }
