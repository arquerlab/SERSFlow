from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("skfda")

from sersflow.api.services.explore_fda import run_fpca_fda


def test_run_fpca_fda_shapes() -> None:
    rng = np.random.default_rng(0)
    Y = rng.standard_normal((8, 32)).astype(np.float32)
    x = np.linspace(100.0, 900.0, 32)
    sids = [f"s{i}" for i in range(8)]
    out = run_fpca_fda(Y, x, sids, n_components=3)
    assert out["kind"] == "fpca_fda"
    assert len(out["explained_variance_ratio"]) == 3
    assert np.asarray(out["scores"]).shape == (8, 3)
    assert len(out["x_cm1"]) == 32
    assert len(out["mean_spectrum"]) == 32
    assert np.asarray(out["components"]).shape == (3, 32)
