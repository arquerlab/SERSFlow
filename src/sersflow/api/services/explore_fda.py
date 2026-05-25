from __future__ import annotations

from typing import Any

import numpy as np


def run_fpca_fda(
    Y: np.ndarray,
    x: np.ndarray,
    spectrum_ids: list[str],
    *,
    n_components: int | None = None,
) -> dict[str, Any]:
    """
    Functional PCA via scikit-fda on a spectrum matrix (discretized curves on a common grid).

    Optional dependency: ``scikit-fda`` (``pip install scikit-fda`` or ``pip install sersflow[explore-fda]``).
    """
    try:
        from skfda.preprocessing.dim_reduction import FPCA as FDA_FPCA
        from skfda.representation.grid import FDataGrid
    except ImportError as e:
        raise ImportError(
            "Refined FPCA requires scikit-fda; install with: pip install scikit-fda"
        ) from e

    Y64 = np.asarray(Y, dtype=np.float64)
    x1 = np.asarray(x, dtype=np.float64).ravel()
    n, p = Y64.shape
    if n < 2:
        raise ValueError("FPCA requires at least two spectra")
    k = n_components or min(10, n - 1, p)
    k = max(1, min(k, n - 1, p))

    fd = FDataGrid(Y64, grid_points=x1)
    fpca = FDA_FPCA(n_components=k)
    scores = fpca.fit_transform(fd)

    comp_dm = np.asarray(fpca.components_.data_matrix)
    if comp_dm.ndim == 3:
        comp_dm = np.squeeze(comp_dm, axis=-1)
    if comp_dm.ndim != 2:
        comp_dm = comp_dm.reshape(k, -1)

    mean_dm = np.asarray(fpca.mean_.data_matrix).squeeze().ravel()

    evr = np.asarray(fpca.explained_variance_ratio_, dtype=np.float64).tolist()

    return {
        "kind": "fpca_fda",
        "n_components": int(k),
        "explained_variance_ratio": evr,
        "x_cm1": x1.tolist(),
        "mean_spectrum": mean_dm.tolist(),
        "components": comp_dm.tolist(),
        "scores": np.asarray(scores, dtype=np.float64).tolist(),
        "spectrum_ids": spectrum_ids,
    }
