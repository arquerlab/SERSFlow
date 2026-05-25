from __future__ import annotations

import json
import os
from typing import Any, Literal

import numpy as np
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA, SparsePCA
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

from sersflow.api.services.observation_export import iter_observation_wide_dicts
from sersflow.infra.analysis_store import get_run, iter_spectrum_rows
from sersflow.infra.datasets_store import spectrum_export_lookup
from sersflow.infra.sqlite_db import connect
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths

PcaScaler = Literal["none", "standard"]


def _scalar_cell_to_float(v: Any) -> float:
    if v is None:
        return float(np.nan)
    if isinstance(v, bool):
        return float(np.nan)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        stripped = v.strip()
        if not stripped:
            return float(np.nan)
        try:
            return float(stripped)
        except (TypeError, ValueError):
            return float(np.nan)
    return float(np.nan)


def load_explore_feature_matrix(
    run_id: str,
    column_names: list[str],
) -> tuple[np.ndarray, list[str], list[str]]:
    """
    Build a numeric matrix from merged observation rows (analysis features plus axis_* and meta_*).
    Each name in ``column_names`` becomes one column; missing keys become NaN.
    """
    if not column_names:
        raise ValueError("no columns selected")
    rec = get_run(run_id)
    if rec is None:
        raise ValueError("analysis run not found")
    keys: list[str] = []
    if rec.feature_columns_json:
        try:
            keys = list(json.loads(rec.feature_columns_json))
        except json.JSONDecodeError:
            keys = []
    lookup = spectrum_export_lookup(rec.dataset_id)
    paths = list(
        {str(lookup[sid].get("relative_path", "")) for sid in lookup if lookup[sid].get("relative_path")}
    )
    labels_by_path: dict[str, dict[str, Any]] = {}
    if paths:
        with connect() as con:
            labels_by_path = fetch_upload_labels_for_paths(con, paths)
    rows: list[list[float]] = []
    sids: list[str] = []
    for row in iter_observation_wide_dicts(
        run_id=run_id,
        feature_keys=keys,
        spectrum_lookup=lookup,
        labels_by_path=labels_by_path,
        join_labels=True,
        join_axes=True,
    ):
        sid = str(row["spectrum_id"])
        sids.append(sid)
        rows.append([_scalar_cell_to_float(row.get(c)) for c in column_names])
    X = np.asarray(rows, dtype=np.float64)
    return X, sids, column_names


def load_feature_matrix_from_analysis_run(
    run_id: str, feature_keys: list[str]
) -> tuple[np.ndarray, list[str], list[str]]:
    """Returns X (n_samples, n_features), spectrum_ids, feature_keys used (numeric only)."""
    rows: list[list[float]] = []
    sids: list[str] = []
    for sid, feat in iter_spectrum_rows(run_id=run_id, chunk_size=500):
        row: list[float] = []
        for k in feature_keys:
            v = feat.get(k)
            if v is None:
                row.append(np.nan)
            else:
                try:
                    row.append(float(v))
                except (TypeError, ValueError):
                    row.append(np.nan)
        rows.append(row)
        sids.append(sid)
    X = np.asarray(rows, dtype=np.float64)
    return X, sids, feature_keys


def pairwise_pearson_pvalues(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """X: (n_samples, n_features). Returns R (p,p) and P (p,p) for pairwise Pearson tests."""
    p = X.shape[1]
    R = np.ones((p, p), dtype=np.float64)
    P = np.ones((p, p), dtype=np.float64)
    for i in range(p):
        for j in range(i + 1, p):
            xi = X[:, i]
            xj = X[:, j]
            mask = np.isfinite(xi) & np.isfinite(xj)
            if mask.sum() < 3:
                r, pv = np.nan, np.nan
            else:
                r, pv = stats.pearsonr(xi[mask], xj[mask])
            R[i, j] = R[j, i] = r
            P[i, j] = P[j, i] = pv
    return R, P


def correlation_bundle(
    X: np.ndarray, names: list[str], *, fdr_alpha: float = 0.05
) -> dict[str, Any]:
    R, P = pairwise_pearson_pvalues(X)
    triu = np.triu_indices_from(R, k=1)
    p_flat = P[triu]
    # FDR step does not accept NaN p-values (pairs with too few finite overlaps).
    p_flat_fdr = np.where(np.isfinite(p_flat), p_flat, 1.0)
    try:
        from scipy.stats import false_discovery_control

        q_flat = false_discovery_control(p_flat_fdr)
    except Exception:
        m = len(p_flat_fdr)
        if m == 0:
            q_flat = p_flat_fdr
        else:
            order = np.argsort(p_flat_fdr)
            qv = np.empty_like(p_flat_fdr, dtype=np.float64)
            cummin = 1.0
            for rank in range(m - 1, -1, -1):
                i = int(order[rank])
                adj = p_flat_fdr[i] * m / (rank + 1)
                cummin = min(float(adj), cummin)
                qv[i] = cummin
            q_flat = np.clip(qv, 0.0, 1.0)
    # Restore NaN Q where p was NaN (no valid test).
    q_flat = np.where(np.isfinite(p_flat), q_flat, np.nan)
    Q = np.ones_like(P)
    Q[triu] = q_flat
    Q[(triu[1], triu[0])] = q_flat
    return {
        "method": "pearson",
        "feature_names": names,
        "R": R.tolist(),
        "P": P.tolist(),
        "Q_bh": Q.tolist(),
        "fdr_alpha": fdr_alpha,
        "pairwise_note": (
            "Each correlation uses pairwise complete observations (finite values in both features). "
            "Fitting and intensity features often miss on different spectra; this is expected."
        ),
    }


def drop_all_nan_columns(X: np.ndarray, names: list[str]) -> tuple[np.ndarray, list[str]]:
    """Remove columns that have no finite value in any row."""
    X = np.asarray(X, dtype=np.float64)
    if X.size == 0:
        raise ValueError("empty matrix")
    if X.shape[1] != len(names):
        raise ValueError("shape mismatch")
    col_has_finite = np.any(np.isfinite(X), axis=0)
    if not np.any(col_has_finite):
        raise ValueError("every column is missing for all spectra")
    X = X[:, col_has_finite]
    names = [n for n, ok in zip(names, col_has_finite.tolist()) if ok]
    return X, names


def prepare_multivariate_matrix(
    X: np.ndarray, names: list[str], spectrum_ids: list[str]
) -> tuple[np.ndarray, list[str], list[str], dict[str, Any]]:
    """Drop columns with no finite values. Prefer complete-case rows; else mean-impute NaNs.

    PCA / VIF / k-means need a full numeric matrix; fitting + spectral columns rarely share
    complete rows across all probes, so mean imputation is a practical fallback.

    ``spectrum_ids`` must align with rows of ``X``; it is filtered when rows are dropped
    for the complete-case path.
    """
    meta: dict[str, Any] = {}
    X, names = drop_all_nan_columns(X, names)
    if len(spectrum_ids) != X.shape[0]:
        raise ValueError("spectrum_ids length must match number of rows")
    row_ok = np.all(np.isfinite(X), axis=1)
    if np.any(row_ok):
        meta["rows_used"] = "complete_cases"
        meta["n_rows"] = int(np.sum(row_ok))
        sids_out = [spectrum_ids[i] for i in range(len(spectrum_ids)) if row_ok[i]]
        return X[row_ok], names, sids_out, meta
    imp = SimpleImputer(strategy="mean")
    X2 = imp.fit_transform(X)
    meta["rows_used"] = "all_spectra_mean_imputed"
    meta["n_rows"] = int(X2.shape[0])
    meta["note"] = (
        "No spectrum had a finite value for every selected column (common when mixing fit_* and I_* features). "
        "Missing entries were filled with the column mean so this analysis could run; treat as exploratory only."
    )
    return np.asarray(X2, dtype=np.float64), names, list(spectrum_ids), meta


def variance_inflation_factors(X: np.ndarray, names: list[str]) -> dict[str, Any]:
    """X must have no NaN; columns are predictors."""
    X = np.asarray(X, dtype=np.float64)
    if np.any(~np.isfinite(X)):
        raise ValueError("VIF requires finite values; impute or drop columns with NaN")
    p = X.shape[1]
    vifs: list[float] = []
    for j in range(p):
        y_col = X[:, j]
        X_others = np.delete(X, j, axis=1)
        lr = LinearRegression()
        lr.fit(X_others, y_col)
        r2 = float(lr.score(X_others, y_col))
        if r2 >= 1.0 - 1e-12:
            vifs.append(float("inf"))
        else:
            vifs.append(float(1.0 / (1.0 - r2)))
    return {"feature_names": names, "vif": vifs}


def _apply_pca_scaler(X: np.ndarray, scaler: PcaScaler) -> tuple[np.ndarray, dict[str, Any]]:
    X = np.asarray(X, dtype=np.float64)
    if scaler == "none":
        return X, {"scaler": "none"}
    if scaler != "standard":
        raise ValueError(f"unknown PCA scaler {scaler!r}")
    fitted = StandardScaler()
    X_scaled = np.asarray(fitted.fit_transform(X), dtype=np.float64)
    return X_scaled, {
        "scaler": "standard",
        "with_mean": True,
        "with_std": True,
        "mean": np.asarray(fitted.mean_, dtype=np.float64).tolist(),
        "scale": np.asarray(fitted.scale_, dtype=np.float64).tolist(),
        "var": np.asarray(fitted.var_, dtype=np.float64).tolist(),
    }


def run_pca(
    X: np.ndarray,
    names: list[str],
    *,
    n_components: int | None = None,
    scaler: PcaScaler = "none",
) -> dict[str, Any]:
    X_prepared, scaling = _apply_pca_scaler(X, scaler)
    p = X_prepared.shape[1]
    n_comp = min(p, X_prepared.shape[0], n_components or min(p, 10))
    pca = PCA(n_components=n_comp)
    scores = pca.fit_transform(X_prepared)
    return {
        "n_components": int(n_comp),
        "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
        "components": pca.components_.tolist(),
        "mean": pca.mean_.tolist(),
        "feature_names": names,
        "scores": scores.tolist(),
        "scaler": scaler,
        "pca_preprocessing": scaling,
    }


def run_spca(
    X: np.ndarray,
    names: list[str],
    *,
    n_components: int | None = None,
    alpha: float = 1.0,
    ridge_alpha: float = 1e-5,
    scaler: PcaScaler = "none",
) -> dict[str, Any]:
    """Sparse PCA on numeric columns (same row contract as :func:`run_pca`)."""
    X_prepared, scaling = _apply_pca_scaler(X, scaler)
    p = X_prepared.shape[1]
    n_comp = min(p, X_prepared.shape[0], n_components or min(p, 10))
    n_comp = max(1, int(n_comp))
    spca = SparsePCA(
        n_components=n_comp,
        alpha=float(alpha),
        ridge_alpha=float(ridge_alpha),
        random_state=0,
    )
    scores = np.asarray(spca.fit_transform(X_prepared), dtype=np.float64)
    return {
        "method": "spca",
        "n_components": int(n_comp),
        "alpha": float(alpha),
        "ridge_alpha": float(ridge_alpha),
        "components": np.asarray(spca.components_, dtype=np.float64).tolist(),
        "feature_names": names,
        "scores": scores.tolist(),
        "scaler": scaler,
        "pca_preprocessing": scaling,
    }


def run_fpca_discrete(
    Y: np.ndarray,
    x: np.ndarray,
    spectrum_ids: list[str],
    *,
    method: str = "pca",
    n_components: int | None = None,
    spca_alpha: float = 1.0,
    spca_ridge_alpha: float = 1e-5,
    scaler: PcaScaler = "none",
) -> dict[str, Any]:
    """Y: (n_samples, n_wavenumbers); PCA or SparsePCA on row-centered Y."""
    Y64 = Y.astype(np.float64)
    mu = np.mean(Y64, axis=0, dtype=np.float64)
    if scaler == "standard":
        X_input, scaling = _apply_pca_scaler(Y64, scaler)
    else:
        X_input = Y64 - mu
        scaling = {"scaler": "none"}
    feat_names = [f"w{i}" for i in range(Y.shape[1])]
    n_comp = n_components if n_components is not None else min(10, Y.shape[0], Y.shape[1])
    if method == "spca":
        p = run_spca(
            X_input,
            feat_names,
            n_components=n_comp,
            alpha=spca_alpha,
            ridge_alpha=spca_ridge_alpha,
        )
        p["kind"] = "fpca_discrete_spca"
    else:
        p = run_pca(X_input, feat_names, n_components=n_comp)
        p["kind"] = "fpca_discrete"
    p["scaler"] = scaler
    p["pca_preprocessing"] = scaling
    p["x_cm1"] = x.tolist()
    p["mean_spectrum"] = mu.tolist()
    p["spectrum_ids"] = spectrum_ids
    return p


def run_kmeans_on_spectrum_matrix(
    Y: np.ndarray,
    spectrum_ids: list[str],
    *,
    n_clusters: int = 3,
    seed: int = 0,
    n_pc_embedding: int = 10,
) -> dict[str, Any]:
    """k-means on PCA scores of row-centered spectra (reduces cost for large p)."""
    mu = np.mean(Y, axis=0, dtype=np.float64)
    Xc = Y.astype(np.float64) - mu
    n_emb = min(int(n_pc_embedding), Xc.shape[0], Xc.shape[1])
    n_emb = max(1, n_emb)
    pca = PCA(n_components=n_emb)
    scores = pca.fit_transform(Xc)
    out = run_kmeans(scores, spectrum_ids, n_clusters=n_clusters, seed=seed)
    out["embedding"] = "pca_scores"
    out["n_pc_embedding"] = int(n_emb)
    out["explained_variance_ratio_sum"] = float(np.sum(pca.explained_variance_ratio_))
    return out


def run_kmeans(X: np.ndarray, spectrum_ids: list[str], *, n_clusters: int = 3, seed: int = 0) -> dict[str, Any]:
    km = KMeans(n_clusters=n_clusters, random_state=seed, n_init=10)
    labels = km.fit_predict(X)
    return {
        "n_clusters": n_clusters,
        "labels": {sid: int(lbl) for sid, lbl in zip(spectrum_ids, labels)},
        "inertia": float(km.inertia_),
    }


def save_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
