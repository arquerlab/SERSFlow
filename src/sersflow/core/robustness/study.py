"""Aggregation of a robustness study: filters, ANOVA per spectrum, trend preservation, noise comparison.

Input is the list of per-(spectrum, cell) records from ``cell_fit.fit_cell`` plus the design. Nothing here refits, so
responses, filters and the interaction order can be changed after the (expensive) fits are done.

Fit-quality filters (``filter_spec``; the report says what each removed, per factor level)
    ``none``              keep every successful fit
    ``delta_bic_common``  keep cells whose common-window BIC is within ``threshold`` of the best cell of the same
                          (spectrum, upstream group)   [valid across windows / backgrounds / constraints]
    ``delta_bic_native``  as above on the native BIC, within groups that fitted the identical data points and
                          weighting   [classical, but cells with other windows are never compared]
    ``rmse_ratio``        keep cells whose common-window rmse is <= ``threshold`` x the best of the group
    plus ``exclude_degenerate`` (drop multi-start-degenerate cells) and ``max_at_bound`` (drop fits with more
    parameters at a bound than allowed).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np

from sersflow.core.robustness.anova import decompose
from sersflow.core.robustness.design import Design
from sersflow.core.robustness.responses import evaluate_responses, trend_metrics


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def record_response(rec: dict[str, Any], spec: dict[str, Any], all_specs: list[dict[str, Any]]) -> float | None:
    """Stored response value, or recomputed from the stored fit when the study was run with other responses."""
    if rec.get("error"):
        return None
    stored = rec.get("responses") or {}
    if spec["name"] in stored:
        return _num(stored[spec["name"]])
    if rec.get("p_opt") is None or rec.get("mapping") is None:
        return None
    vals = evaluate_responses(all_specs, rec["mapping"], np.asarray(rec["p_opt"], dtype=float))
    return _num(vals.get(spec["name"]))


# --------------------------------------------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------------------------------------------

def apply_filter(
    records: list[dict[str, Any]],
    design: Design,
    filter_spec: dict[str, Any] | None,
) -> tuple[set[tuple[str, str]], dict[str, Any]]:
    """Keys ``(spectrum_id, cell_id)`` kept by the filter, and a report of what was removed per factor level."""
    spec = dict(filter_spec or {})
    mode = str(spec.get("mode") or "none")
    thr = spec.get("threshold")
    if mode not in ("none", "delta_bic_common", "delta_bic_native", "rmse_ratio"):
        raise ValueError(f"unknown filter mode {mode!r}")
    cell_by_id = {c.cell_id: c for c in design.cells}
    ok = [r for r in records if not r.get("error") and r["cell_id"] in cell_by_id]
    failed = [r for r in records if r.get("error")]
    reason: dict[tuple[str, str], str] = {}

    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    if mode in ("delta_bic_common", "rmse_ratio"):
        for r in ok:
            groups[(r["spectrum_id"], cell_by_id[r["cell_id"]].upstream_key)].append(r)
    elif mode == "delta_bic_native":
        for r in ok:
            groups[
                (r["spectrum_id"], cell_by_id[r["cell_id"]].upstream_key, r.get("n_points"), r.get("weighting"), r.get("x_lo"), r.get("x_hi"))
            ].append(r)
    if mode == "delta_bic_common":
        t = 10.0 if thr is None else float(thr)
        for g in groups.values():
            vals = [r.get("bic_common") for r in g if _num(r.get("bic_common")) is not None]
            if not vals:
                continue
            best = min(vals)
            for r in g:
                b = _num(r.get("bic_common"))
                if b is None or b - best > t:
                    reason[(r["spectrum_id"], r["cell_id"])] = f"dBIC_common > {t:g}"
    elif mode == "delta_bic_native":
        t = 10.0 if thr is None else float(thr)
        for g in groups.values():
            vals = [r.get("bic") for r in g if _num(r.get("bic")) is not None]
            if not vals:
                continue
            best = min(vals)
            for r in g:
                b = _num(r.get("bic"))
                if b is None or b - best > t:
                    reason[(r["spectrum_id"], r["cell_id"])] = f"dBIC_native > {t:g}"
    elif mode == "rmse_ratio":
        t = 1.5 if thr is None else float(thr)
        for g in groups.values():
            vals = [r.get("rmse_common") for r in g if _num(r.get("rmse_common")) is not None]
            if not vals:
                continue
            best = min(vals)
            for r in g:
                v = _num(r.get("rmse_common"))
                if v is None or (best > 0 and v > t * best):
                    reason[(r["spectrum_id"], r["cell_id"])] = f"rmse_common > {t:g} x best"
    if spec.get("exclude_degenerate"):
        for r in ok:
            if r.get("degenerate"):
                reason.setdefault((r["spectrum_id"], r["cell_id"]), "degenerate (multi-start)")
    if spec.get("max_at_bound") is not None:
        m = float(spec["max_at_bound"])
        for r in ok:
            nb = _num(r.get("n_at_bound"))
            if nb is not None and nb > m:
                reason.setdefault((r["spectrum_id"], r["cell_id"]), f"n_at_bound > {m:g}")

    kept = {(r["spectrum_id"], r["cell_id"]) for r in ok if (r["spectrum_id"], r["cell_id"]) not in reason}

    by_level: dict[str, dict[str, dict[str, int]]] = {}
    for fi, f in enumerate(design.factors):
        lv: dict[str, dict[str, int]] = {l.name: {"total": 0, "kept": 0, "removed": 0, "failed": 0} for l in f.levels}
        for r in ok:
            name = cell_by_id[r["cell_id"]].levels[fi]
            lv[name]["total"] += 1
            lv[name]["kept" if (r["spectrum_id"], r["cell_id"]) in kept else "removed"] += 1
        for r in failed:
            c = cell_by_id.get(r["cell_id"])
            if c is not None:
                lv[c.levels[fi]]["total"] += 1
                lv[c.levels[fi]]["failed"] += 1
        by_level[f.name] = lv
    report = {
        "mode": mode,
        "threshold": thr,
        "exclude_degenerate": bool(spec.get("exclude_degenerate")),
        "max_at_bound": spec.get("max_at_bound"),
        "n_total": len(records),
        "n_failed": len(failed),
        "n_kept": len(kept),
        "n_removed": len(reason),
        "by_level": by_level,
        "note": (
            "Native BIC is only compared between fits of identical data points and weighting; the common-window "
            "score is compared within the same upstream group. Check by_level: a filter that removes mostly one "
            "level of a factor biases that factor's apparent effect."
        ),
    }
    return kept, report


# --------------------------------------------------------------------------------------------------------------
# ANOVA across spectra
# --------------------------------------------------------------------------------------------------------------

def _values_by_spectrum(
    design: Design,
    records: list[dict[str, Any]],
    kept: set[tuple[str, str]],
    spec: dict[str, Any],
    all_specs: list[dict[str, Any]],
) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = defaultdict(dict)
    for r in records:
        key = (r["spectrum_id"], r["cell_id"])
        out[r["spectrum_id"]].setdefault(r["cell_id"], None)
        if key in kept:
            out[r["spectrum_id"]][r["cell_id"]] = record_response(r, spec, all_specs)
    return out


def anova_study(
    design: Design,
    values: dict[str, dict[str, float | None]],
) -> dict[str, Any]:
    """Per-spectrum decomposition and its aggregate over spectra."""
    n_levels = [len(f.levels) for f in design.factors]
    names = design.factor_names
    idx = [c.level_index for c in design.cells]
    cell_ids = [c.cell_id for c in design.cells]
    per: dict[str, Any] = {}
    agg_share: dict[str, list[float]] = defaultdict(list)
    agg_ss: dict[str, float] = defaultdict(float)
    agg_total = 0.0
    order_of: dict[str, int] = {}
    n_exact = 0
    for sid, v in values.items():
        y = [v.get(cid) for cid in cell_ids]
        res = decompose(idx, y, n_levels, names, max_order=design.interaction_order)
        per[sid] = res
        if not res["terms"] or not res["total_ss"]:
            continue
        n_exact += int(res["exact"] and design.exact)
        agg_total += res["total_ss"]
        for t in res["terms"]:
            order_of[t["term"]] = t["order"]
            agg_ss[t["term"]] += t["ss"]
            if t["share"] is not None:
                agg_share[t["term"]].append(t["share"])
    terms = []
    for term, shares in agg_share.items():
        terms.append(
            {
                "term": term,
                "order": order_of[term],
                "share_mean": float(np.mean(shares)),
                "share_median": float(np.median(shares)),
                "share_min": float(np.min(shares)),
                "share_max": float(np.max(shares)),
                "share_pooled": float(agg_ss[term] / agg_total) if agg_total > 0 else None,
                "n_spectra": len(shares),
            }
        )
    terms.sort(key=lambda t: -(t["share_pooled"] or 0.0))
    return {
        "terms": terms,
        "n_spectra": len(per),
        "n_spectra_exact": n_exact,
        "exact": bool(per) and n_exact == len([r for r in per.values() if r["terms"] and r["total_ss"]]),
        "per_spectrum": per,
    }


# --------------------------------------------------------------------------------------------------------------
# trend preservation, bands, noise comparison
# --------------------------------------------------------------------------------------------------------------

def trend_study(
    design: Design,
    values: dict[str, dict[str, float | None]],
    x_by_spectrum: dict[str, float | None],
    *,
    reference_cell: str | None = None,
) -> dict[str, Any]:
    """How the response changes with x (any label) in every cell, and whether the trend survives the choices."""
    sids = [s for s in values if x_by_spectrum.get(s) is not None]
    sids.sort(key=lambda s: x_by_spectrum[s])
    xs = np.array([x_by_spectrum[s] for s in sids], dtype=float)
    per_cell: list[dict[str, Any]] = []
    profiles: list[np.ndarray] = []
    for c in design.cells:
        y = np.array([np.nan if values[s].get(c.cell_id) is None else values[s][c.cell_id] for s in sids], dtype=float)
        tm = trend_metrics(xs, y)
        per_cell.append({"cell_id": c.cell_id, "levels": list(c.levels), "n": int(np.isfinite(y).sum()), **tm})
        profiles.append(y)
    signs = [p["sign"] for p in per_cell if p["sign"] is not None]
    if reference_cell is not None:
        ref = next((p["sign"] for p in per_cell if p["cell_id"] == reference_cell), None)
        ref_desc = f"cell {reference_cell}"
    else:
        ref = None if not signs else (1.0 if sum(signs) >= 0 else -1.0)
        ref_desc = "majority sign of the cells"
    preserved = [p for p in per_cell if p["sign"] is not None and ref is not None and p["sign"] == ref]
    n_valid = len([p for p in per_cell if p["sign"] is not None])
    # ordering agreement: Spearman of each cell's profile vs the median profile of all cells
    ordering: list[float] = []
    if profiles and len(sids) >= 3:
        med = np.nanmedian(np.vstack(profiles), axis=0)
        from sersflow.core.robustness.responses import spearman

        for p, row in zip(per_cell, profiles):
            rho = spearman(row, med)
            p["ordering_vs_median"] = rho
            if rho is not None:
                ordering.append(rho)
    rhos = [p["spearman"] for p in per_cell if p["spearman"] is not None]
    bands = []
    for j, s in enumerate(sids):
        col = np.array([prof[j] for prof in profiles], dtype=float)
        col = col[np.isfinite(col)]
        if col.size == 0:
            continue
        q = np.percentile(col, [2.5, 50, 97.5])
        bands.append(
            {
                "spectrum_id": s,
                "x": float(xs[j]),
                "p2_5": float(q[0]),
                "p50": float(q[1]),
                "p97_5": float(q[2]),
                "min": float(col.min()),
                "max": float(col.max()),
                "n": int(col.size),
            }
        )
    return {
        "n_spectra": len(sids),
        "reference": ref_desc,
        "reference_sign": ref,
        "n_cells_with_trend": n_valid,
        "fraction_sign_preserved": (len(preserved) / n_valid) if n_valid else None,
        "spearman_median": float(np.median(rhos)) if rhos else None,
        "spearman_min": float(np.min(rhos)) if rhos else None,
        "spearman_max": float(np.max(rhos)) if rhos else None,
        "ordering_vs_median_median": float(np.median(ordering)) if ordering else None,
        "bands": bands,
        "per_cell": per_cell,
    }


def choice_variance(values: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
    """Variance of the response across the (kept) cells, per spectrum (ddof=1)."""
    out: dict[str, float | None] = {}
    for sid, v in values.items():
        arr = np.array([x for x in v.values() if x is not None], dtype=float)
        out[sid] = float(np.var(arr, ddof=1)) if arr.size > 1 else None
    return out


def noise_comparison(
    choice_var: dict[str, float | None],
    noise_values: dict[str, list[float]],
) -> dict[str, Any]:
    """Analyst-choice variance vs counting-noise Monte Carlo variance (same response, per spectrum)."""
    per: dict[str, Any] = {}
    ratios: list[float] = []
    for sid, cv in choice_var.items():
        nv = [x for x in noise_values.get(sid, []) if x is not None and math.isfinite(x)]
        if cv is None or len(nv) < 2:
            continue
        nvar = float(np.var(np.asarray(nv), ddof=1))
        ratio = float(cv / nvar) if nvar > 0 else None
        per[sid] = {"choice_var": cv, "noise_var": nvar, "choice_sd": math.sqrt(cv), "noise_sd": math.sqrt(nvar), "ratio_var": ratio}
        if ratio is not None and math.isfinite(ratio):
            ratios.append(ratio)
    return {
        "per_spectrum": per,
        "ratio_var_median": float(np.median(ratios)) if ratios else None,
        "ratio_var_min": float(np.min(ratios)) if ratios else None,
        "ratio_var_max": float(np.max(ratios)) if ratios else None,
        "ratio_sd_median": float(math.sqrt(np.median(ratios))) if ratios else None,
        "n_spectra": len(ratios),
    }


def degeneracy_summary(records: list[dict[str, Any]], design: Design) -> dict[str, Any]:
    ok = [r for r in records if not r.get("error")]
    cell_by_id = {c.cell_id: c for c in design.cells}
    by_level: dict[str, dict[str, dict[str, int]]] = {}
    for fi, f in enumerate(design.factors):
        lv = {l.name: {"n": 0, "degenerate": 0} for l in f.levels}
        for r in ok:
            c = cell_by_id.get(r["cell_id"])
            if c is None:
                continue
            lv[c.levels[fi]]["n"] += 1
            lv[c.levels[fi]]["degenerate"] += int(bool(r.get("degenerate")))
        by_level[f.name] = lv
    n_deg = sum(1 for r in ok if r.get("degenerate"))
    return {
        "n_fits": len(ok),
        "n_degenerate": n_deg,
        "fraction_degenerate": (n_deg / len(ok)) if ok else None,
        "by_level": by_level,
    }


def summarize_study(
    design: Design,
    records: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    *,
    x_by_spectrum: dict[str, float | None] | None = None,
    filter_spec: dict[str, Any] | None = None,
    noise: dict[str, dict[str, list[float]]] | None = None,
    reference_cell: str | None = None,
) -> dict[str, Any]:
    """Everything the study reports, per response. ``noise[response][spectrum_id]`` = Monte Carlo replicate values."""
    kept, frep = apply_filter(records, design, filter_spec)
    unfiltered, _ = apply_filter(records, design, None)
    out: dict[str, Any] = {
        "design": design.to_public_dict(),
        "filter": frep,
        "degeneracy": degeneracy_summary(records, design),
        "responses": {},
    }
    for spec in responses:
        name = spec["name"]
        vals = _values_by_spectrum(design, records, kept, spec, responses)
        block: dict[str, Any] = {
            "anova": anova_study(design, vals),
            "choice_variance": choice_variance(vals),
        }
        if filter_spec and str(filter_spec.get("mode") or "none") != "none" or (filter_spec or {}).get("exclude_degenerate"):
            vals_all = _values_by_spectrum(design, records, unfiltered, spec, responses)
            block["anova_unfiltered"] = {k: v for k, v in anova_study(design, vals_all).items() if k != "per_spectrum"}
        if x_by_spectrum is not None:
            block["trend"] = trend_study(design, vals, x_by_spectrum, reference_cell=reference_cell)
        if noise and name in noise:
            block["noise_comparison"] = noise_comparison(block["choice_variance"], noise[name])
        out["responses"][name] = block
    return out
