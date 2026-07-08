from __future__ import annotations

from typing import Literal

import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


OutlierMethod = Literal[
    "correlation_to_median",
    "pca_reconstruction_error",
    "pca_score_distance",
]

PcaScaler = Literal["none", "standard"]


def _require_matrix_same_grid(
    ys_by_id: dict[str, np.ndarray],
    x_by_id: dict[str, np.ndarray],
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """
    Ensure all spectra share the same x-grid shape and values (within tolerance),
    then return (X, spectrum_ids, x0).
    """
    if not ys_by_id:
        return np.zeros((0, 0), dtype=np.float64), [], np.zeros((0,), dtype=np.float64)
    sids = list(ys_by_id.keys())
    x0 = np.asarray(x_by_id[sids[0]], dtype=np.float64).ravel()
    if x0.size < 2:
        raise ValueError("Outlier detection requires at least 2 points per spectrum.")
    rows: list[np.ndarray] = []
    for sid in sids:
        x = np.asarray(x_by_id[sid], dtype=np.float64).ravel()
        y = np.asarray(ys_by_id[sid], dtype=np.float64).ravel()
        if x.shape != x0.shape:
            raise ValueError(
                "Outlier detection requires a shared Raman-shift grid. "
                "Add an enabled align_resample step before outlier_detection."
            )
        if not np.allclose(x, x0, rtol=0.0, atol=1e-3):
            raise ValueError(
                "Outlier detection requires a shared Raman-shift grid. "
                "Add an enabled align_resample step before outlier_detection."
            )
        rows.append(y)
    X = np.stack(rows, axis=0).astype(np.float64, copy=False)
    return X, sids, x0


def _impute_nonfinite_with_col_mean(X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=np.float64)
    if X.size == 0:
        return X
    X2 = X.copy()
    finite = np.isfinite(X2)
    # Column means over finite values; fallback 0 when a column is all non-finite.
    means = np.nanmean(np.where(finite, X2, np.nan), axis=0)
    means = np.where(np.isfinite(means), means, 0.0)
    inds = np.where(~finite)
    X2[inds] = means[inds[1]]
    return X2


def correlation_to_median_scores(X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[0] < 1:
        return np.zeros((0,), dtype=np.float64)
    med = np.median(X, axis=0)
    scores = np.full((X.shape[0],), np.nan, dtype=np.float64)
    for i in range(X.shape[0]):
        a = X[i]
        mask = np.isfinite(a) & np.isfinite(med)
        if int(np.sum(mask)) < 3:
            continue
        aa = a[mask]
        mm = med[mask]
        # Pearson correlation
        aa = aa - float(np.mean(aa))
        mm = mm - float(np.mean(mm))
        denom = float(np.linalg.norm(aa) * np.linalg.norm(mm))
        if denom <= 0:
            continue
        scores[i] = float(np.dot(aa, mm) / denom)
    return scores


def pca_scores(
    X: np.ndarray,
    *,
    n_components: int,
    scaler: PcaScaler,
) -> tuple[np.ndarray, PCA, dict[str, object]]:
    X_in = _impute_nonfinite_with_col_mean(X)
    meta: dict[str, object] = {"scaler": scaler}
    if scaler == "standard":
        ss = StandardScaler()
        X_fit = np.asarray(ss.fit_transform(X_in), dtype=np.float64)
        meta["scaler_mean"] = ss.mean_.astype(float).tolist()
        meta["scaler_scale"] = ss.scale_.astype(float).tolist()
    else:
        X_fit = X_in
    n_comp = max(1, min(int(n_components), X_fit.shape[0], X_fit.shape[1]))
    pca = PCA(n_components=n_comp)
    Z = np.asarray(pca.fit_transform(X_fit), dtype=np.float64)
    meta["n_components"] = int(n_comp)
    meta["explained_variance_ratio"] = pca.explained_variance_ratio_.astype(float).tolist()
    return Z, pca, meta


def pca_reconstruction_error_scores(
    X: np.ndarray,
    *,
    n_components: int,
    scaler: PcaScaler,
) -> tuple[np.ndarray, dict[str, object]]:
    X_in = _impute_nonfinite_with_col_mean(X)
    meta: dict[str, object] = {"scaler": scaler}
    if scaler == "standard":
        ss = StandardScaler()
        X_fit = np.asarray(ss.fit_transform(X_in), dtype=np.float64)
    else:
        X_fit = X_in
    Z, pca, pmeta = pca_scores(X, n_components=n_components, scaler=scaler)
    meta.update(pmeta)
    X_hat = np.asarray(pca.inverse_transform(Z), dtype=np.float64)
    err = np.mean((X_fit - X_hat) ** 2, axis=1)
    return np.asarray(err, dtype=np.float64), meta


def pca_score_distance_scores(
    X: np.ndarray,
    *,
    n_components: int,
    scaler: PcaScaler,
) -> tuple[np.ndarray, dict[str, object]]:
    Z, _pca, meta = pca_scores(X, n_components=n_components, scaler=scaler)
    d = np.linalg.norm(Z, axis=1)
    return np.asarray(d, dtype=np.float64), meta


def outlier_scores_from_xy(
    *,
    method: OutlierMethod,
    ys_by_id: dict[str, np.ndarray],
    x_by_id: dict[str, np.ndarray],
    n_components: int = 8,
    pca_scaler: PcaScaler = "none",
) -> tuple[dict[str, float], dict[str, object]]:
    """
    Compute anomaly scores for whole spectra.

    Returns:
      scores_by_spectrum_id, meta
    """
    X, sids, x0 = _require_matrix_same_grid(ys_by_id, x_by_id)
    meta: dict[str, object] = {"method": method, "x_len": int(x0.size)}
    if X.shape[0] < 2:
        # Not enough samples to estimate outliers meaningfully.
        return {sid: float("nan") for sid in sids}, meta

    if method == "correlation_to_median":
        arr = correlation_to_median_scores(X)
        return {sid: float(arr[i]) for i, sid in enumerate(sids)}, meta

    if method == "pca_reconstruction_error":
        arr, pmeta = pca_reconstruction_error_scores(X, n_components=n_components, scaler=pca_scaler)
        meta.update(pmeta)
        return {sid: float(arr[i]) for i, sid in enumerate(sids)}, meta

    if method == "pca_score_distance":
        arr, pmeta = pca_score_distance_scores(X, n_components=n_components, scaler=pca_scaler)
        meta.update(pmeta)
        return {sid: float(arr[i]) for i, sid in enumerate(sids)}, meta

    raise ValueError(f"Unknown outlier method: {method}")

