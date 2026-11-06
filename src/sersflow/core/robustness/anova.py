"""Variance decomposition of a factorial design (one observation per cell).

For a COMPLETE full factorial the decomposition is exact: the sum of squares of every main effect and interaction is
computed from marginal means (identical to the first-order and interaction Sobol indices of the discrete design).
Truncating ``max_order`` pools the higher-order interactions into one ``higher-order`` term.

When cells are missing (failed fits, a filter, subsampling) the design is unbalanced; a sequential least-squares
decomposition with sum-to-zero coding is used instead and flagged ``exact=False``.

Shares are SS(term) / SS(total); with one observation per cell there is no residual term, the remainder after the
requested order is reported as ``higher-order``.
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np


def _terms(n_factors: int, max_order: int | None) -> list[tuple[int, ...]]:
    top = n_factors if max_order is None else min(int(max_order), n_factors)
    out: list[tuple[int, ...]] = []
    for k in range(1, top + 1):
        out += list(itertools.combinations(range(n_factors), k))
    return out


def term_name(term: tuple[int, ...], factor_names: list[str]) -> str:
    return " x ".join(factor_names[i] for i in term)


def _exact(values: np.ndarray, terms: list[tuple[int, ...]]) -> dict[tuple[int, ...], float]:
    n_f = values.ndim
    mu = float(np.mean(values))
    marg: dict[tuple[int, ...], np.ndarray] = {}
    for k in range(0, n_f + 1):
        for sub in itertools.combinations(range(n_f), k):
            axes = tuple(i for i in range(n_f) if i not in sub)
            marg[sub] = np.mean(values, axis=axes) if axes else values.copy()
    marg[()] = np.asarray(mu)
    ss: dict[tuple[int, ...], float] = {}
    for term in terms:
        eff = np.zeros([values.shape[i] for i in term], dtype=float)
        for k in range(len(term) + 1):
            for sub in itertools.combinations(term, k):
                m = marg[sub] if sub else marg[()]
                # broadcast the marginal over the axes of `term` that are not in `sub`
                shape = [values.shape[i] if i in sub else 1 for i in term]
                eff = eff + ((-1) ** (len(term) - k)) * np.asarray(m).reshape(shape)
        n_rep = int(np.prod([values.shape[i] for i in range(n_f) if i not in term])) if n_f > len(term) else 1
        ss[term] = float(n_rep * np.sum(eff**2))
    return ss


def _effect_coded(levels: np.ndarray, n_levels: int) -> np.ndarray:
    """Sum-to-zero coding: (n, n_levels-1)."""
    n = levels.size
    X = np.zeros((n, n_levels - 1), dtype=float)
    for j in range(n_levels - 1):
        X[levels == j, j] = 1.0
    X[levels == n_levels - 1, :] = -1.0
    return X


def _sequential(
    level_index: np.ndarray, y: np.ndarray, n_levels: list[int], terms: list[tuple[int, ...]]
) -> dict[tuple[int, ...], float]:
    n = y.size
    cols: dict[int, np.ndarray] = {i: _effect_coded(level_index[:, i], n_levels[i]) for i in range(len(n_levels))}
    cur = np.ones((n, 1), dtype=float)

    def rss(X: np.ndarray) -> float:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        r = y - X @ beta
        return float(r @ r)

    prev = rss(cur)
    ss: dict[tuple[int, ...], float] = {}
    for term in terms:
        block = cols[term[0]]
        for i in term[1:]:
            a, b = block, cols[i]
            block = np.einsum("ni,nj->nij", a, b).reshape(n, -1)
        cur = np.hstack([cur, block])
        now = rss(cur)
        ss[term] = max(prev - now, 0.0)
        prev = now
    return ss


def decompose(
    level_index: list[tuple[int, ...]] | np.ndarray,
    y: list[float | None] | np.ndarray,
    n_levels: list[int],
    factor_names: list[str],
    *,
    max_order: int | None = None,
) -> dict[str, Any]:
    """Variance shares of the main effects and interactions of one response.

    ``level_index[k]`` is the level index per factor of observation k, ``y[k]`` its value (None / NaN = missing).
    Returns ``{"terms": [{"term", "order", "ss", "share"}], "total_ss", "exact", "n_obs", "n_expected"}``;
    ``share`` is None when the total variance is zero.
    """
    idx = np.asarray(level_index, dtype=int).reshape(-1, len(n_levels))
    yy = np.array([np.nan if v is None else float(v) for v in y], dtype=float)
    ok = np.isfinite(yy)
    idx, yy = idx[ok], yy[ok]
    n_expected = int(np.prod(n_levels))
    terms = _terms(len(n_levels), max_order)
    if yy.size < 2:
        return {"terms": [], "total_ss": None, "exact": False, "n_obs": int(yy.size), "n_expected": n_expected}

    complete = yy.size == n_expected and len({tuple(r) for r in idx.tolist()}) == n_expected
    total = float(np.sum((yy - yy.mean()) ** 2))
    if complete:
        grid = np.full(n_levels, np.nan)
        for r, v in zip(idx, yy):
            grid[tuple(r)] = v
        ss = _exact(grid, terms)
    else:
        ss = _sequential(idx, yy, n_levels, terms)

    rows = []
    used = 0.0
    for t in terms:
        used += ss[t]
        rows.append(
            {
                "term": term_name(t, factor_names),
                "order": len(t),
                "ss": ss[t],
                "share": (ss[t] / total) if total > 0 else None,
            }
        )
    rest = max(total - used, 0.0)
    if rest > 1e-12 * max(total, 1.0) or max_order is not None:
        rows.append(
            {
                "term": "higher-order",
                "order": (max_order or 0) + 1,
                "ss": rest,
                "share": (rest / total) if total > 0 else None,
            }
        )
    return {"terms": rows, "total_ss": total, "exact": bool(complete), "n_obs": int(yy.size), "n_expected": n_expected}
