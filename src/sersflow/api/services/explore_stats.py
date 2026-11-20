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
from sersflow.infra.analysis_store import get_run
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


def pairwise_pearson_pvalues(
    X: np.ndarray, method: str = "pearson"
) -> tuple[np.ndarray, np.ndarray]:
    """X: (n_samples, n_features). Returns R (p,p) and P (p,p) for pairwise Pearson (or Spearman) tests."""
    test = stats.spearmanr if method == "spearman" else stats.pearsonr
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
                r, pv = test(xi[mask], xj[mask])
            R[i, j] = R[j, i] = r
            P[i, j] = P[j, i] = pv
    return R, P


def correlation_bundle(
    X: np.ndarray, names: list[str], *, fdr_alpha: float = 0.05, method: str = "pearson"
) -> dict[str, Any]:
    R, P = pairwise_pearson_pvalues(X, method=method)
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
        "method": method,
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


def _jsonable(o: Any) -> Any:
    """numpy -> python, NaN/inf -> None (strict JSON)."""
    if isinstance(o, dict):
        return {(k if isinstance(k, str) else str(k)): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return _jsonable(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if np.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


def compute_depth_alignment(
    z: np.ndarray, pos: np.ndarray, profile: np.ndarray, params: dict[str, Any]
) -> dict[str, Any]:
    """Per-position edge of ``profile`` along ``z`` and the shifts relative to a reference position.

    ``pos`` is (n_rows, n_pos_cols). Returns aligned z per row (``z_aligned``) plus a per-position table.
    """
    from sersflow.core.multivariate import depth as dp

    z = np.asarray(z, dtype=np.float64)
    pos = np.asarray(pos, dtype=np.float64).reshape(len(z), -1)
    keys = [tuple(float(v) for v in r) for r in pos]
    rows_of: dict[tuple, list[int]] = {}
    for i, k in enumerate(keys):
        rows_of.setdefault(k, []).append(i)
    edges: dict[tuple, float] = {}
    for k, idx in rows_of.items():
        ix = np.asarray(idx)
        edges[k] = dp.interface_edge_z(
            z[ix],
            profile[ix],
            mode=params.get("mode", "edge"),
            smooth=int(params.get("smooth", 3)),
            plateau_z_max=params.get("plateau_z_max"),
            plateau_n=int(params.get("plateau_n", 6)),
            low_z_range=tuple(params["low_z_range"]) if params.get("low_z_range") else None,
            search_z_min=params.get("search_z_min"),
            direction=params.get("direction", "down"),
        )
    ref = tuple(float(v) for v in params["reference"]) if params.get("reference") else None
    res = dp.position_z_shifts(edges, ref)
    z_al = dp.apply_shifts(z, keys, res["shifts"])
    table = [{"position": list(k), "edge_z": edges[k], "shift": res["shifts"][k]} for k in edges]
    sh = np.array([t["shift"] for t in table], dtype=float)
    fin = sh[np.isfinite(sh)]
    return {
        "reference": [float(v) for v in res["reference"]],
        "reference_edge_z": res["reference_edge_z"],
        "n_positions": len(table),
        "n_positions_without_edge": int(len(table) - len(fin)),
        "shift_min": float(fin.min()) if fin.size else None,
        "shift_max": float(fin.max()) if fin.size else None,
        "shift_mean": float(fin.mean()) if fin.size else None,
        "shift_std": float(fin.std(ddof=1)) if fin.size > 1 else None,
        "positions": table,
        "z_aligned": z_al,
    }


def compute_segments(
    z: np.ndarray,
    X: np.ndarray,
    *,
    method: str = "contiguous",
    n_segments: int = 4,
    k_max: int = 6,
    bin_width: float = 5.0,
    winsor_pct: float | None = 99.0,
    robust_clip: float | None = 5.0,
    standardize: bool = True,
    seed: int = 0,
    n_init: int = 50,
    pos: np.ndarray | None = None,
    per_position_check: bool = True,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """Segment rows (ordered by ``z``) from feature matrix ``X`` (rows with non-finite z / features removed).

    Returns labels (0-based, increasing with z for ``contiguous``; k-means clusters are numbered by median z),
    cuts, cost / silhouette versus K, per-segment medians.
    """
    from sersflow.core.multivariate import depth as dp

    z = np.asarray(z, dtype=np.float64)
    F = dp.prepare_features(X, winsor_pct=winsor_pct, robust_clip=robust_clip, standardize=standardize)
    if len(z) < max(n_segments, 2):
        raise ValueError("fewer spectra than segments")
    k_max = max(int(k_max), int(n_segments))
    out: dict[str, Any] = {"method": method, "n_segments": int(n_segments), "n_rows": int(len(z))}
    if method == "contiguous":
        b = dp.bin_ordered(z, F, bin_width)
        sol = dp.contiguous_segments(b["F"], b["w"], k_max)
        if n_segments not in sol:
            raise ValueError("n_segments exceeds the number of distinct z bins")
        cuts_by_k = {K: dp.cut_positions(b["z"], st) for K, (_, st) in sol.items()}
        cost_by_k = {K: c for K, (c, _) in sol.items()}
        cuts = cuts_by_k[n_segments]
        labels = dp.segment_labels(z, cuts)
        out.update(cuts=cuts, cuts_by_k=cuts_by_k, cost_by_k=cost_by_k, n_bins=int(len(b["z"])))
        if per_position_check and pos is not None:
            out["per_position_cuts"] = dp.per_position_cuts(z, F, pos, n_segments)
    else:
        from sklearn.metrics import silhouette_score

        labels, inertia = dp.kmeans_ordered(F, z, n_segments, seed=seed, n_init=n_init)
        cost_by_k: dict[int, float] = {}
        sil_by_k: dict[int, float] = {}
        for K in range(2, k_max + 1):
            lab, ine = dp.kmeans_ordered(F, z, K, seed=seed, n_init=n_init)
            cost_by_k[K] = ine
            if len(np.unique(lab)) > 1:
                sil_by_k[K] = float(silhouette_score(F, lab, sample_size=min(1500, len(z)), random_state=seed))
        out.update(cost_by_k=cost_by_k, silhouette_by_k=sil_by_k, inertia=inertia)
        # contiguity: fraction of z-sorted neighbours that share a label (1 = perfectly contiguous)
        o = np.argsort(z, kind="stable")
        out["contiguity"] = float(np.mean(labels[o][1:] == labels[o][:-1]))
    seg = []
    for c in range(int(labels.max()) + 1):
        m = labels == c
        if not m.any():
            continue
        row: dict[str, Any] = {
            "segment": c,
            "n": int(m.sum()),
            "z_min": float(z[m].min()),
            "z_max": float(z[m].max()),
            "z_median": float(np.median(z[m])),
        }
        if names:
            row["median_features"] = {n: float(np.nanmedian(X[m, j])) for j, n in enumerate(names)}
        seg.append(row)
    out["segments"] = seg
    out["labels_array"] = labels
    return out


def run_depth_align(run_id: str, order_column: str, p: dict[str, Any]) -> dict[str, Any]:
    cols = list(dict.fromkeys([order_column, p["feature_column"], *p["position_columns"]]))
    M, sids, _ = load_explore_feature_matrix(run_id, cols)
    col = {n: M[:, i] for i, n in enumerate(cols)}
    z = col[order_column]
    pos = np.column_stack([col[c] for c in p["position_columns"]])
    ok = np.isfinite(z) & np.all(np.isfinite(pos), axis=1)
    if not ok.any():
        raise ValueError("order / position columns have no finite values")
    res = compute_depth_alignment(z[ok], pos[ok], col[p["feature_column"]][ok], p)
    z_al = res.pop("z_aligned")
    res["spectrum_ids"] = [s for s, k in zip(sids, ok) if k]
    res["z_original"] = z[ok]
    res["z_aligned"] = z_al
    res["order_column"] = order_column
    return res


def run_depth_segments(run_id: str, req: dict[str, Any]) -> dict[str, Any]:
    feats = list(req["feature_columns"])
    ocol = req["order_column"]
    poscols = list(req["position_columns"]) if (req.get("align") or req.get("per_position_check")) else []
    extra = [req["align"]["feature_column"]] if req.get("align") else []
    uniq = list(dict.fromkeys([ocol, *poscols, *extra, *feats]))
    M, sids, _ = load_explore_feature_matrix(run_id, uniq)
    col = {n: M[:, i] for i, n in enumerate(uniq)}
    z = col[ocol]
    pos = np.column_stack([col[c] for c in poscols]) if poscols else None
    ok = np.isfinite(z)
    if pos is not None:
        ok &= np.all(np.isfinite(pos), axis=1)
    alignment = None
    if req.get("align"):
        ap = dict(req["align"])
        alignment = compute_depth_alignment(z[ok], pos[ok], col[ap["feature_column"]][ok], ap)
        z_use = np.full_like(z, np.nan)
        z_use[ok] = alignment.pop("z_aligned")
    else:
        z_use = z
    Xf = np.column_stack([col[c] for c in feats])
    ok = ok & np.isfinite(z_use) & np.all(np.isfinite(Xf), axis=1)
    n_dropped = int((~ok).sum())
    if ok.sum() < 3:
        raise ValueError("too few spectra with finite z and features")
    res = compute_segments(
        z_use[ok],
        Xf[ok],
        method=req["method"],
        n_segments=req["n_segments"],
        k_max=req["k_max"],
        bin_width=req["bin_width"],
        winsor_pct=req.get("winsor_pct"),
        robust_clip=req.get("robust_clip"),
        standardize=req["standardize"],
        seed=req["seed"],
        n_init=req["n_init"],
        pos=pos[ok] if pos is not None else None,
        per_position_check=bool(req.get("per_position_check")),
        names=feats,
    )
    labels = res.pop("labels_array")
    names = req.get("zone_names") or []
    n_lab = int(labels.max()) + 1
    res["zone_names"] = [names[i] if i < len(names) and names[i] else f"Segment {i + 1}" for i in range(n_lab)]
    res["spectrum_ids"] = [s for s, k in zip(sids, ok) if k]
    res["labels"] = [int(v) for v in labels]
    res["z_used"] = z_use[ok]
    res["z_original"] = z[ok]
    res["order_column"] = ocol
    res["feature_columns"] = feats
    res["n_dropped_rows"] = n_dropped
    if alignment is not None:
        res["alignment"] = alignment
    return res


def save_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
