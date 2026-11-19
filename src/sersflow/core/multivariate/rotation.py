"""Varimax rotation of PCA components."""

from __future__ import annotations

from typing import Any

import numpy as np


def varimax(L: np.ndarray, gamma: float = 1.0, max_iter: int = 500, tol: float = 1e-8) -> np.ndarray:
    """Orthogonal rotation matrix R (k x k) maximising the varimax criterion of L (p x k)."""
    p, k = L.shape
    R = np.eye(k)
    d = 0.0
    for _ in range(max_iter):
        d_old = d
        Lr = L @ R
        u, s, vt = np.linalg.svd(
            L.T @ (Lr**3 - (gamma / p) * Lr @ np.diag(np.sum(Lr**2, axis=0)))
        )
        R = u @ vt
        d = float(np.sum(s))
        if d_old != 0.0 and d / d_old < 1 + tol:
            break
    return R


def rotate_pca_result(result: dict[str, Any], *, kaiser: bool = True) -> dict[str, Any]:
    """Varimax-rotate a PCA-like result (``components`` k x p, ``scores`` n x k).

    Scores and components are rotated by the same orthogonal matrix, so
    ``scores @ components`` is unchanged. Variance ratios are recomputed and the
    components re-sorted by decreasing variance. Only valid for ordinary PCA.
    """
    C = np.asarray(result["components"], dtype=np.float64)  # k x p
    T = np.asarray(result["scores"], dtype=np.float64)  # n x k
    k = C.shape[0]
    if k < 2:
        out = dict(result)
        out["rotation"] = {"method": "varimax", "applied": False, "reason": "needs >= 2 components"}
        return out
    evr = np.asarray(result["explained_variance_ratio"], dtype=np.float64)
    var_scores = T.var(axis=0, ddof=1)
    total_var = float(var_scores.sum() / max(evr.sum(), 1e-300))
    L = C.T * np.sqrt(np.maximum(var_scores, 0.0))[None, :]  # p x k, scaled loadings
    if kaiser:
        h = np.sqrt(np.maximum((L**2).sum(axis=1), 1e-300))
        R = varimax(L / h[:, None])
    else:
        R = varimax(L)
    C_rot = R.T @ C
    T_rot = T @ R
    var_rot = T_rot.var(axis=0, ddof=1)
    order = np.argsort(-var_rot)
    C_rot, T_rot, var_rot = C_rot[order], T_rot[:, order], var_rot[order]
    out = dict(result)
    out["components"] = C_rot.tolist()
    out["scores"] = T_rot.tolist()
    out["explained_variance_ratio"] = (var_rot / total_var).tolist()
    out["rotation"] = {
        "method": "varimax",
        "applied": True,
        "kaiser_normalisation": bool(kaiser),
        "rotation_matrix": R[:, order].tolist(),
        "note": "Rotated scores are generally correlated and the variance is redistributed between components; the retained subspace is unchanged.",
    }
    return out
