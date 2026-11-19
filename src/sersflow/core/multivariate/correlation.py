"""Correlation matrices (Pearson / Spearman) with optional hierarchical reordering."""

from __future__ import annotations

from typing import Any

import numpy as np

MAX_VARS = 4000
DEFAULT_MAX_DISPLAY = 800
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


def block_mean_matrix(R: np.ndarray, b: int) -> np.ndarray:
    """Mean of R over b x b blocks (NaN-aware); the last block may be smaller."""
    p = R.shape[0]
    idx = np.arange(0, p, b)
    ok = np.isfinite(R)
    S = np.add.reduceat(np.add.reduceat(np.where(ok, R, 0.0), idx, axis=0), idx, axis=1)
    N = np.add.reduceat(np.add.reduceat(ok.astype(float), idx, axis=0), idx, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(N > 0, S / N, np.nan)


def correlation_matrix(
    Y: np.ndarray,
    x: np.ndarray,
    spectrum_ids: list[str],
    *,
    axis: str = "channels",
    method: str = "pearson",
    reorder: bool = False,
    linkage: str = "average",
    max_display: int = DEFAULT_MAX_DISPLAY,
) -> dict[str, Any]:
    """Correlation of channels (columns of Y) or of samples (rows of Y).

    Channels are always kept in the order of ``x`` (ascending); clustered ``reorder`` applies to
    samples only. When there are more than ``max_display`` variables the returned matrix is the
    block mean of R (``block_size`` variables per cell) so the response stays small.
    """
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
    if reorder and axis == "samples":
        out = reorder_correlation_result(out, linkage=linkage)
    elif reorder:
        out["reorder_ignored"] = "channels stay in wavenumber order"
    out["n_variables"] = int(p)
    out["block_size"] = 1
    if p > max(50, int(max_display)):
        b = int(np.ceil(p / max(50, int(max_display))))
        Rm = np.asarray(out["R"], dtype=float)
        idx = np.arange(0, p, b)
        out["R"] = block_mean_matrix(Rm, b).tolist()
        labs = out["labels"]
        if axis == "channels":
            xs = np.asarray(out["x"], dtype=float)
            counts = np.diff(np.append(idx, p))
            xb = np.add.reduceat(xs, idx) / counts
            out["x"] = xb.tolist()
            out["labels"] = [f"{v:.6g}" for v in xb]
        else:
            ends = np.append(idx[1:], p) - 1
            out["labels"] = [f"{labs[i]}…{labs[j]}" if i != j else labs[i] for i, j in zip(idx, ends)]
        out["block_size"] = b
    return out
