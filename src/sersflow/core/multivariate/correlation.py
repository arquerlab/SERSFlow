"""Correlation matrices (Pearson / Spearman) with optional hierarchical reordering."""

from __future__ import annotations

from typing import Any

import numpy as np

MAX_VARS = 1500
LINKAGES = ("average", "complete", "single", "ward")


def _ranks(M: np.ndarray) -> np.ndarray:
    from scipy.stats import rankdata

    return np.apply_along_axis(rankdata, 0, M)


def clustered_order(R: np.ndarray, linkage: str = "average") -> list[int]:
    """Leaf order of a hierarchical clustering on distance 1 - R (NaN treated as 0 correlation)."""
    from scipy.cluster.hierarchy import linkage as _linkage, optimal_leaf_ordering, leaves_list
    from scipy.spatial.distance import squareform

    if linkage not in LINKAGES:
        raise ValueError(f"unknown linkage {linkage!r}")
    n = R.shape[0]
    if n < 3:
        return list(range(n))
    Rc = np.where(np.isfinite(R), R, 0.0)
    D = np.clip(1.0 - Rc, 0.0, 2.0)
    D = (D + D.T) / 2.0
    np.fill_diagonal(D, 0.0)
    cond = squareform(D, checks=False)
    Z = _linkage(cond, method=linkage)
    try:
        Z = optimal_leaf_ordering(Z, cond)
    except Exception:
        pass
    return [int(i) for i in leaves_list(Z)]


def reorder_correlation_result(
    result: dict[str, Any], *, linkage: str = "average"
) -> dict[str, Any]:
    """Permute R / P / Q_bh and the labels of a correlation result into clustered order."""
    R = np.asarray(result["R"], dtype=float)
    order = clustered_order(R, linkage)
    out = dict(result)
    for key in ("R", "P", "Q_bh"):
        if key in result:
            M = np.asarray(result[key], dtype=float)
            out[key] = M[np.ix_(order, order)].tolist()
    names = result.get("feature_names") or result.get("labels")
    if names:
        names = [names[i] for i in order]
        out["feature_names" if "feature_names" in result else "labels"] = names
    out["order"] = order
    out["reordered"] = True
    out["linkage"] = linkage
    return out


def correlation_matrix(
    Y: np.ndarray,
    x: np.ndarray,
    spectrum_ids: list[str],
    *,
    axis: str = "channels",
    method: str = "pearson",
    reorder: bool = False,
    linkage: str = "average",
) -> dict[str, Any]:
    """Correlation of channels (columns of Y) or of samples (rows of Y)."""
    if axis not in ("channels", "samples"):
        raise ValueError("axis must be 'channels' or 'samples'")
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")
    M = np.asarray(Y, dtype=np.float64)
    if axis == "samples":
        M = M.T  # variables in columns
        labels = [str(s) for s in spectrum_ids]
    else:
        labels = [f"{v:.6g}" for v in np.asarray(x, dtype=float)]
    p = M.shape[1]
    if p > MAX_VARS:
        raise ValueError(
            f"{p} variables exceed the limit of {MAX_VARS}; bin or crop the matrix first"
        )
    if M.shape[0] < 3:
        raise ValueError("need at least 3 observations per variable")
    if method == "spearman":
        M = _ranks(M)
    sd = M.std(axis=0)
    ok = sd > 0
    R = np.full((p, p), np.nan)
    if ok.any():
        R[np.ix_(ok, ok)] = np.corrcoef(M[:, ok], rowvar=False).reshape(int(ok.sum()), int(ok.sum()))
    np.fill_diagonal(R, 1.0)
    R = np.clip(R, -1.0, 1.0)
    out: dict[str, Any] = {
        "method": method,
        "axis": axis,
        "labels": labels,
        "R": R.tolist(),
        "n_observations": int(M.shape[0]),
        "n_constant_variables": int((~ok).sum()),
        "reordered": False,
    }
    if axis == "channels":
        out["x"] = np.asarray(x, dtype=float).tolist()
    if reorder:
        out = reorder_correlation_result(out, linkage=linkage)
    return out
