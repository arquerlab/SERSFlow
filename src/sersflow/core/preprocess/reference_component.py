"""
Measured reference spectrum as a fit component (M1, CasaXPS linear least squares basis).

The component dict carries ``reference_id`` (and ``reference_sha256`` for reproducibility). The stored spectrum is
normalised to unit area, so the fitted ``amp`` IS the component area. ``shift`` moves the reference in energy
(fixed at 0 by default; CasaXPS LLS assumes calibrated data). Outside the reference's own x range it is 0.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

import numpy as np


@functools.lru_cache(maxsize=64)
def _load(reference_id: str) -> tuple[np.ndarray, np.ndarray, str]:
    from sersflow.infra.reference_spectra_store import get_reference_any

    ref = get_reference_any(reference_id)
    if ref is None:
        raise ValueError(f"reference spectrum {reference_id!r} not found")
    x = np.asarray(ref.x, dtype=float)
    y = np.asarray(ref.y, dtype=float) / float(ref.area)
    return x, y, ref.sha256


def reference_arrays(options: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    rid = str(options.get("reference_id") or "").strip()
    if not rid:
        raise ValueError("reference_spectrum component needs a reference_id")
    x, y, sha = _load(rid)
    want = str(options.get("reference_sha256") or "").strip()
    if want and want != sha:
        raise ValueError(f"reference {rid!r} changed since this pipeline was saved (sha256 mismatch)")
    return x, y


def make_reference_function(options: dict[str, Any]) -> Callable[..., np.ndarray]:
    xr, yr = reference_arrays(options)

    def reference_spectrum(x: np.ndarray, amp: float, shift: float) -> np.ndarray:
        xf = np.asarray(x, dtype=float)
        return float(amp) * np.interp(xf - float(shift), xr, yr, left=0.0, right=0.0)

    return reference_spectrum


def clear_cache() -> None:
    _load.cache_clear()


def is_pure_reference_model(problem: Any) -> bool:
    """True when every component is a reference spectrum with its shift fixed and no links (exact NNLS applies)."""
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    if getattr(problem, "param_links", None):
        return False
    vary = list(problem.vary or [])
    cursor = 0
    for c in problem.components:
        if c.component_type.strip().lower() != "reference_spectrum":
            return False
        keys = [s.key for s in component_param_specs(c.component_type)]
        si = cursor + keys.index("shift")
        if si < len(vary) and vary[si]:
            return False
        cursor += len(keys)
    return bool(problem.components)


def fit_references_nnls(problem: Any) -> Any:
    """
    Non-negative linear least squares on the reference basis (CasaXPS LLS with positivity), weighted by 1/sigma.

    amp_i >= 0 are the component areas (unit-area references); covariance (A^T W A)^-1 scaled by the reduced chi2 on
    the active (non-zero) set, zero for components at the positivity bound.
    """
    from scipy.optimize import nnls

    from sersflow.core.preprocess.fit_diagnostics import compute_fit_diagnostics
    from sersflow.core.preprocess.fitting import FitResult, stderr_from_cov
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    x = np.asarray(problem.x, dtype=float)
    y = np.asarray(problem.y, dtype=float)
    cols, mapping, shifts = [], [], []
    cursor = 0
    for c in problem.components:
        keys = [s.key for s in component_param_specs(c.component_type)]
        shift = float(problem.p0[cursor + keys.index("shift")])
        f = make_reference_function(c.options or {})
        cols.append(f(x, 1.0, shift))
        shifts.append(shift)
        mapping.append(
            {
                "component_id": c.component_id,
                "component_type": c.component_type,
                "degree": None,
                "param_keys": keys,
                "index_range": [cursor, cursor + len(keys)],
                "x_window": [float(np.min(x)), float(np.max(x))],
                "options": dict(c.options or {}),
            }
        )
        cursor += len(keys)
    A = np.column_stack(cols)
    w = 1.0 / np.asarray(problem.sigma, dtype=float) if problem.sigma is not None else np.ones_like(y)
    amps, _rnorm = nnls(A * w[:, None], y * w)
    y_hat = A @ amps
    n = len(problem.components)
    p_opt = np.zeros(cursor)
    for i, m in enumerate(mapping):
        s = m["index_range"][0]
        p_opt[s] = amps[i]
        p_opt[s + 1] = shifts[i]
    active = [i for i in range(n) if amps[i] > 0]
    dof = max(1, y.size - len(active))
    chi2 = float(np.sum(((y - y_hat) * w) ** 2))
    p_cov = np.zeros((cursor, cursor))
    if active:
        Aw = (A * w[:, None])[:, active]
        try:
            c_act = np.linalg.inv(Aw.T @ Aw) * (chi2 / dof)
            idx = [mapping[i]["index_range"][0] for i in active]
            p_cov[np.ix_(idx, idx)] = c_act
        except np.linalg.LinAlgError:
            p_cov = None
    free = [False] * cursor
    for i in range(n):
        free[mapping[i]["index_range"][0]] = True
    diag = compute_fit_diagnostics(
        y,
        y_hat,
        n_vary=n,
        p_cov=p_cov,
        p_opt=p_opt,
        nfev=1,
        success=True,
        x=x,
        sigma=problem.sigma,
        weighting=problem.weighting,
        weighting_note=(problem.weighting_note or "") + " · solved exactly by NNLS (linear reference model)",
    )
    return FitResult(
        p_opt=p_opt,
        p_cov=p_cov,
        y_hat=y_hat,
        component_y_hat=[A[:, i] * amps[i] for i in range(n)],
        mapping=mapping,
        diagnostics=diag,
        p_stderr=stderr_from_cov(p_cov, cursor, free),
    )
