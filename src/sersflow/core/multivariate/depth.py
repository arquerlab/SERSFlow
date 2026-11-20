"""Depth / ordered-axis analysis: interface alignment and contiguous segmentation.

Pure numpy (no I/O). Rows are spectra, ``z`` is an ordered coordinate (depth, time, distance).

* ``interface_edge_z`` locates a step ("edge") in a profile, per map position.
* ``position_z_shifts`` turns per-position edges into shifts relative to a reference position.
* ``prepare_features`` winsorises / robust-scales / standardises a feature matrix.
* ``contiguous_segments`` is the exact dynamic-programming split of ordered bins into K
  contiguous segments (minimum weighted within-segment SSE).
* ``kmeans_ordered`` is plain k-means with clusters renumbered by median z (for comparison).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.ndimage import uniform_filter1d


# --------------------------------------------------------------------------- alignment


def interface_edge_z(
    z: np.ndarray,
    profile: np.ndarray,
    *,
    mode: str = "edge",
    smooth: int = 3,
    plateau_z_max: float | None = None,
    plateau_n: int = 6,
    low_z_range: tuple[float, float] | None = None,
    search_z_min: float | None = None,
    direction: str = "down",
) -> float:
    """z of the half-height crossing of a step in ``profile`` (NaN if none is found).

    ``mode="edge"``: plateau = mean of the ``plateau_n`` largest smoothed values with z <= ``plateau_z_max``
    (default: lowest third of the z range); low = minimum over ``low_z_range`` (default: above the plateau
    window); half = (plateau + low) / 2; the first crossing of ``half`` for z >= ``search_z_min`` (default:
    lowest z) is located by linear interpolation. ``direction="down"`` = profile falls with increasing z,
    ``"up"`` = it rises (the profile is then negated, so plateau/low swap roles).
    ``mode="argmax"``: z of the maximum of the smoothed profile (noisier; kept as an alternative).
    """
    z = np.asarray(z, dtype=float)
    y = np.asarray(profile, dtype=float)
    ok = np.isfinite(z) & np.isfinite(y)
    if ok.sum() < 5:
        return float("nan")
    z, y = z[ok], y[ok]
    order = np.argsort(z, kind="stable")
    z, y = z[order], y[order]
    if smooth and smooth > 1:
        y = uniform_filter1d(y, int(smooth), mode="nearest")
    if mode == "argmax":
        return float(z[int(np.argmax(y))])
    if direction == "up":
        y = -y
    if plateau_z_max is None:
        plateau_z_max = float(z[0] + (z[-1] - z[0]) / 3.0)
    pm = z <= plateau_z_max
    if not pm.any():
        return float("nan")
    plate = float(np.sort(y[pm])[-max(1, int(plateau_n)):].mean())
    if low_z_range is None:
        lm = z > plateau_z_max
    else:
        lm = (z >= low_z_range[0]) & (z <= low_z_range[1])
    if not lm.any():
        return float("nan")
    low = float(y[lm].min())
    half = 0.5 * (plate + low)
    start = 0 if search_z_min is None else int(np.searchsorted(z, search_z_min, side="left"))
    for i in range(start, len(z) - 1):
        if y[i] >= half > y[i + 1]:
            return float(z[i] + (y[i] - half) / (y[i] - y[i + 1]) * (z[i + 1] - z[i]))
    return float("nan")


def position_z_shifts(
    edges: dict[tuple, float],
    reference: tuple | None = None,
) -> dict[str, Any]:
    """Shift per position = edge(position) - edge(reference); the reference keeps its z.

    ``edges`` maps a position key (tuple of coordinates) to its edge z. ``reference=None`` picks the
    position whose coordinates are closest to the centroid of all positions (the "centre").
    Positions without an edge get NaN shifts (their z is left unchanged by ``apply_shifts``).
    """
    keys = list(edges.keys())
    if not keys:
        raise ValueError("no positions")
    if reference is None:
        P = np.array(keys, dtype=float)
        reference = keys[int(np.argmin(((P - P.mean(0)) ** 2).sum(1)))]
    reference = tuple(reference)
    if reference not in edges:
        raise ValueError(f"reference position {reference} not found")
    ref_edge = edges[reference]
    if not np.isfinite(ref_edge):
        raise ValueError("no edge found at the reference position; adjust the alignment windows")
    shifts = {k: (v - ref_edge if np.isfinite(v) else float("nan")) for k, v in edges.items()}
    return {"reference": reference, "reference_edge_z": float(ref_edge), "shifts": shifts}


def apply_shifts(z: np.ndarray, pos_keys: list[tuple], shifts: dict[tuple, float]) -> np.ndarray:
    """Aligned z = z - shift(position); unknown / NaN shifts leave z unchanged."""
    sh = np.array([shifts.get(k, np.nan) for k in pos_keys], dtype=float)
    sh = np.where(np.isfinite(sh), sh, 0.0)
    return np.asarray(z, dtype=float) - sh


# --------------------------------------------------------------------------- features


def prepare_features(
    X: np.ndarray,
    *,
    winsor_pct: float | None = 99.0,
    robust_clip: float | None = 5.0,
    standardize: bool = True,
) -> np.ndarray:
    """Per-column: upper winsorise at ``winsor_pct`` percentile, robust-scale (median/IQR), clip to
    +-``robust_clip``, then z-score. Failed fits give isolated area spikes; this keeps them from
    dominating distances. Any step is skipped when its parameter is None/False. NaNs are kept."""
    X = np.array(X, dtype=float, copy=True)
    for j in range(X.shape[1]):
        c = X[:, j]
        f = np.isfinite(c)
        if not f.any():
            continue
        if winsor_pct is not None:
            c[f] = np.minimum(c[f], np.percentile(c[f], winsor_pct))
        if robust_clip is not None:
            q1, med, q3 = np.percentile(c[f], [25, 50, 75])
            iqr = q3 - q1
            c[f] = np.clip((c[f] - med) / (iqr if iqr > 0 else 1.0), -robust_clip, robust_clip)
        if standardize:
            sd = np.std(c[f], ddof=1) if f.sum() > 1 else 0.0
            c[f] = (c[f] - np.mean(c[f])) / (sd if sd > 0 else 1.0)
        X[:, j] = c
    return X


# --------------------------------------------------------------------------- segmentation


def bin_ordered(z: np.ndarray, F: np.ndarray, width: float) -> dict[str, np.ndarray]:
    """Group rows by ``round(z / width) * width``; returns bin centres, mean feature rows, counts."""
    z = np.asarray(z, dtype=float)
    if width and width > 0:
        zb = np.round(z / width) * width
    else:
        zb = z
    uniq, inv = np.unique(zb, return_inverse=True)
    n = np.bincount(inv).astype(float)
    M = np.zeros((len(uniq), F.shape[1]))
    np.add.at(M, inv, F)
    return {"z": uniq, "F": M / n[:, None], "w": n, "index": inv}


def contiguous_segments(
    F: np.ndarray, w: np.ndarray | None, k_max: int
) -> dict[int, tuple[float, list[int]]]:
    """Exact optimal splits of the ordered rows of ``F`` into K = 1..``k_max`` contiguous segments.

    Minimises the weighted within-segment sum of squares. Returns ``{K: (cost, starts)}`` where
    ``starts`` are the row indices at which segments 2..K begin. O(K n^2) with vectorised inner loop.
    """
    F = np.asarray(F, dtype=float)
    n = len(F)
    if n < 1:
        raise ValueError("empty input")
    w = np.ones(n) if w is None else np.asarray(w, dtype=float)
    k_max = int(min(k_max, n))
    cw = np.concatenate([[0.0], np.cumsum(w)])
    cs = np.vstack([np.zeros(F.shape[1]), np.cumsum(F * w[:, None], axis=0)])
    cq = np.concatenate([[0.0], np.cumsum(w * (F**2).sum(1))])

    def seg_cost(i: np.ndarray, j: int) -> np.ndarray:  # rows i..j-1, vectorised over i
        W = cw[j] - cw[i]
        s = cs[j] - cs[i]
        return (cq[j] - cq[i]) - (s**2).sum(1) / W

    C = np.full((k_max + 1, n + 1), np.inf)
    B = np.zeros((k_max + 1, n + 1), dtype=int)
    C[0, 0] = 0.0
    for k in range(1, k_max + 1):
        for j in range(k, n + 1):
            i = np.arange(k - 1, j)
            tot = C[k - 1, i] + seg_cost(i, j)
            m = int(np.argmin(tot))
            C[k, j], B[k, j] = tot[m], i[m]
    out: dict[int, tuple[float, list[int]]] = {}
    for K in range(1, k_max + 1):
        starts, j = [], n
        for k in range(K, 0, -1):
            i = int(B[k, j])
            starts.append(i)
            j = i
        out[K] = (float(max(C[K, n], 0.0)), sorted(starts)[1:])
    return out


def cut_positions(zb: np.ndarray, starts: list[int]) -> list[float]:
    """Boundary z = midpoint between the last bin of one segment and the first of the next."""
    return [float((zb[i - 1] + zb[i]) / 2.0) for i in starts]


def segment_labels(z: np.ndarray, cuts: list[float]) -> np.ndarray:
    """0-based segment index of each z (increasing with z)."""
    return np.digitize(np.asarray(z, dtype=float), np.asarray(cuts, dtype=float))


def per_position_cuts(
    z: np.ndarray, F: np.ndarray, groups: np.ndarray, K: int
) -> list[dict[str, Any]]:
    """Independent K-segment split inside each group (position): shows boundary scatter / tilt."""
    out = []
    groups = np.asarray(groups, dtype=float).reshape(len(z), -1)
    for g in np.unique(groups, axis=0):
        idx = np.where(np.all(groups == g, axis=1))[0]
        idx = idx[np.argsort(z[idx], kind="stable")]
        ok = np.all(np.isfinite(F[idx]), axis=1)
        idx = idx[ok]
        if len(idx) < K:
            continue
        _, starts = contiguous_segments(F[idx], None, K)[K]
        zz = z[idx]
        out.append({"position": np.atleast_1d(g).tolist(), "cuts": [float((zz[i - 1] + zz[i]) / 2) for i in starts]})
    return out


def kmeans_ordered(F: np.ndarray, z: np.ndarray, k: int, *, seed: int = 0, n_init: int = 50):
    """k-means on ``F`` with clusters renumbered by increasing median z. Returns labels, inertia."""
    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=k, n_init=max(20, int(n_init)), random_state=seed).fit(F)
    lab = km.labels_
    med = [float(np.median(z[lab == c])) if np.any(lab == c) else np.inf for c in range(k)]
    remap = {int(o): i for i, o in enumerate(np.argsort(med))}
    return np.array([remap[int(v)] for v in lab]), float(km.inertia_)
