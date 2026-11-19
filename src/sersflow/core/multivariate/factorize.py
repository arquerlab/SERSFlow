"""Non-negative factorisations of a spectrum matrix: NMF and MCR-ALS.

Both model ``Y (n x p) ~ C (n x k) @ S (k x p)`` with C = contributions per spectrum and
S = component spectra. Results use the PCA-like keys (``scores`` = C, ``components`` = S)
so that the shared plot and CSV code can consume them.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _lof(Y: np.ndarray, C: np.ndarray, S: np.ndarray) -> tuple[float, float]:
    res = Y - C @ S
    ss_res = float(np.sum(res**2))
    ss_tot = float(np.sum(Y**2))
    lof = 100.0 * np.sqrt(ss_res / ss_tot) if ss_tot > 0 else float("nan")
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(lof), float(r2)


def _check_nonneg(Y: np.ndarray) -> None:
    if float(np.min(Y)) < 0:
        raise ValueError("matrix has negative values; enable a non-negativity option")


def run_nmf(
    Y: np.ndarray,
    x: np.ndarray,
    spectrum_ids: list[str],
    *,
    n_components: int = 3,
    n_starts: int = 5,
    max_iter: int = 500,
    scan_k: list[int] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Multi-start NMF (nndsvda first, then random starts); best reconstruction error wins."""
    from sklearn.decomposition import NMF

    Y64 = np.asarray(Y, dtype=np.float64)
    _check_nonneg(Y64)
    n, p = Y64.shape
    kmax = min(n, p)

    def fit(k: int, starts: int | None = None) -> tuple[np.ndarray, np.ndarray, float, list[float]]:
        best = None
        errs: list[float] = []
        for i in range(max(1, n_starts if starts is None else starts)):
            kw: dict[str, Any] = dict(n_components=k, max_iter=max_iter, tol=1e-4)
            if i == 0:
                kw["init"] = "nndsvda"
            else:
                kw["init"] = "random"
                kw["random_state"] = seed + i
            m = NMF(**kw)
            W = m.fit_transform(Y64)
            err = float(m.reconstruction_err_)
            errs.append(err)
            if best is None or err < best[2]:
                best = (W, m.components_.copy(), err)
        assert best is not None
        return best[0], best[1], best[2], errs

    k = max(1, min(int(n_components), kmax))
    W, H, err, errs = fit(k)
    lof, r2 = _lof(Y64, W, H)
    # order components by contribution energy
    energy = (W**2).sum(axis=0) * (H**2).sum(axis=1)
    order = np.argsort(-energy)
    W, H = W[:, order], H[order]
    # scale each spectrum to unit max, push the scale into the contributions
    scale = np.maximum(H.max(axis=1), 1e-300)
    H = H / scale[:, None]
    W = W * scale[None, :]
    out: dict[str, Any] = {
        "kind": "nmf",
        "method": "nmf",
        "n_components": int(k),
        "scores": W.tolist(),
        "components": H.tolist(),
        "feature_names": [f"w{i}" for i in range(p)],
        "x_cm1": np.asarray(x, dtype=float).tolist(),
        "spectrum_ids": list(spectrum_ids),
        "explained_variance_ratio": (energy[order] / max(energy.sum(), 1e-300)).tolist(),
        "reconstruction_error": err,
        "lack_of_fit_pct": lof,
        "r2": r2,
        "n_starts": int(max(1, n_starts)),
        "start_errors": errs,
        "start_error_spread_pct": float(100.0 * (max(errs) - min(errs)) / max(min(errs), 1e-300)),
        "note": (
            "NMF solutions are not unique. A large start_error_spread_pct means the factorisation "
            "is unstable for this k; compare k values with scan_k and treat components as indicative."
        ),
    }
    if scan_k:
        scan = []
        for kk in sorted({int(v) for v in scan_k if 1 <= int(v) <= kmax}):
            _, _, e, _ = fit(kk, starts=min(2, max(1, n_starts)))  # the scan is a guide: keep it cheap
            Wk_lof = float(100.0 * e / max(np.linalg.norm(Y64), 1e-300))
            scan.append({"k": kk, "reconstruction_error": e, "lack_of_fit_pct": Wk_lof})
        out["scan"] = scan
    return out


def _unimodal(s: np.ndarray) -> np.ndarray:
    """Enforce one peak: non-increasing away from the maximum on both sides."""
    out = s.copy()
    i = int(np.argmax(out))
    for j in range(i - 1, -1, -1):
        out[j] = min(out[j], out[j + 1])
    for j in range(i + 1, len(out)):
        out[j] = min(out[j], out[j - 1])
    return out


def _solve_rows(
    A: np.ndarray, B: np.ndarray, nonneg: bool, solver: str, X0: np.ndarray | None = None
) -> np.ndarray:
    """Solve min ||B_i - A x_i|| for every row i of B: returns X (n x k) with B ~ X @ A.T.

    A: (p, k) design, B: (n, p). ``solver="hals"`` is a vectorised non-negative coordinate descent
    (warm-started from ``X0``); ``"nnls"`` is the exact active-set solve per row (slow on big matrices).
    """
    if not nonneg:
        X, *_ = np.linalg.lstsq(A, B.T, rcond=None)
        return X.T
    if solver == "lstsq_clip":
        X, *_ = np.linalg.lstsq(A, B.T, rcond=None)
        return np.clip(X.T, 0.0, None)
    if solver == "hals":
        G = A.T @ A
        H = B @ A
        if X0 is not None and X0.shape == (B.shape[0], A.shape[1]):
            X = np.clip(X0, 0.0, None)
        else:
            X0_, *_ = np.linalg.lstsq(A, B.T, rcond=None)
            X = np.clip(X0_.T, 0.0, None)
        diag = np.diag(G)
        for _ in range(40):
            moved = 0.0
            for j in range(A.shape[1]):
                if diag[j] <= 1e-300:
                    continue
                new = np.maximum(0.0, X[:, j] + (H[:, j] - X @ G[:, j]) / diag[j])
                moved = max(moved, float(np.max(np.abs(new - X[:, j]), initial=0.0)))
                X[:, j] = new
            scale = float(np.max(np.abs(X), initial=1e-12))
            if moved < 1e-7 * scale:
                break
        return X
    from scipy.optimize import nnls

    out = np.empty((B.shape[0], A.shape[1]))
    for i in range(B.shape[0]):
        out[i], _ = nnls(A, B[i])
    return out


def run_mcr_als(
    Y: np.ndarray,
    x: np.ndarray,
    spectrum_ids: list[str],
    *,
    n_components: int = 3,
    nonneg_conc: bool = True,
    nonneg_spec: bool = True,
    closure: bool = False,
    unimodal_spec: bool = False,
    normalise_spec: bool = True,
    fixed_spectrum_ids: list[str] | None = None,
    solver: str = "hals",
    max_iter: int = 200,
    tol: float = 1e-6,
    seed: int = 0,
) -> dict[str, Any]:
    """MCR-ALS with optional constraints.

    Initial spectra come from NMF (nndsvda). ``fixed_spectrum_ids`` pick rows of ``Y`` whose
    spectra become the first components and are held fixed throughout.
    """
    from sklearn.decomposition import NMF

    Y64 = np.asarray(Y, dtype=np.float64)
    if nonneg_spec or nonneg_conc:
        _check_nonneg(Y64)
    n, p = Y64.shape
    k = max(1, min(int(n_components), min(n, p)))
    sids = [str(s) for s in spectrum_ids]
    fixed_idx: list[int] = []
    for sid in fixed_spectrum_ids or []:
        if str(sid) not in sids:
            raise ValueError(f"fixed spectrum id {sid!r} not in the matrix")
        fixed_idx.append(sids.index(str(sid)))
    if len(fixed_idx) > k:
        raise ValueError("more fixed spectra than components")
    nf = len(fixed_idx)

    S_fixed = Y64[fixed_idx].copy() if nf else None
    if nf:
        # free components start from NMF of what the fixed spectra cannot explain
        C0 = _solve_rows(S_fixed.T, Y64, True, "hals")
        resid = np.clip(Y64 - C0 @ S_fixed, 0.0, None) + 1e-9
        S = np.zeros((k, p))
        S[:nf] = S_fixed
        if k > nf:
            nmf = NMF(n_components=k - nf, init="nndsvda", max_iter=500, random_state=seed)
            nmf.fit(resid)
            S[nf:] = nmf.components_
    else:
        nmf = NMF(n_components=k, init="nndsvda", max_iter=500, random_state=seed)
        nmf.fit(np.clip(Y64, 0.0, None))
        S = nmf.components_.copy()
    S = np.maximum(S, 0.0) if nonneg_spec else S

    prev = np.inf
    C = np.zeros((n, k))
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        C = _solve_rows(S.T, Y64, nonneg_conc, solver, X0=C if it > 1 else None)
        if closure:
            tot = C.sum(axis=1, keepdims=True)
            tot[tot == 0] = 1.0
            C = C / tot
        S_new = _solve_rows(C, Y64.T, nonneg_spec, solver, X0=S.T if it > 1 else None).T
        if unimodal_spec:
            for j in range(nf, k):
                S_new[j] = _unimodal(S_new[j])
        if nf:
            S_new[:nf] = S_fixed
        S = S_new
        lof, _ = _lof(Y64, C, S)
        if abs(prev - lof) < tol * max(lof, 1e-12):
            converged = True
            break
        prev = lof
    lof, r2 = _lof(Y64, C, S)
    if normalise_spec:
        m = np.maximum(np.abs(S).max(axis=1), 1e-300)
        S = S / m[:, None]
        C = C * m[None, :]
    energy = (C**2).sum(axis=0) * (S**2).sum(axis=1)
    return {
        "kind": "mcr_als",
        "method": "mcr_als",
        "n_components": int(k),
        "scores": C.tolist(),
        "components": S.tolist(),
        "feature_names": [f"w{i}" for i in range(p)],
        "x_cm1": np.asarray(x, dtype=float).tolist(),
        "spectrum_ids": sids,
        "explained_variance_ratio": (energy / max(energy.sum(), 1e-300)).tolist(),
        "lack_of_fit_pct": lof,
        "r2": r2,
        "iterations": int(it),
        "converged": bool(converged),
        "fixed_spectrum_ids": [sids[i] for i in fixed_idx],
        "constraints": {
            "nonneg_conc": bool(nonneg_conc),
            "nonneg_spec": bool(nonneg_spec),
            "closure": bool(closure),
            "unimodal_spec": bool(unimodal_spec),
            "normalise_spec": bool(normalise_spec),
            "solver": solver,
        },
        "note": (
            "MCR-ALS solutions have rotational ambiguity; constraints and fixed reference spectra "
            "narrow it but do not remove it. Use PCA/NMF scans to choose k first."
        ),
    }
