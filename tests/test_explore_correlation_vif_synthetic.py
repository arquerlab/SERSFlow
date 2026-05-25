from __future__ import annotations

import numpy as np

from sersflow.api.services.explore_stats import correlation_bundle, variance_inflation_factors


def test_correlation_bundle_tiny_matrix() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_normal((20, 4))
    names = ["a", "b", "c", "d"]
    out = correlation_bundle(X, names)
    assert out["method"] == "pearson"
    assert len(out["feature_names"]) == 4
    assert np.asarray(out["R"]).shape == (4, 4)


def test_vif_tiny_matrix() -> None:
    rng = np.random.default_rng(1)
    X = rng.standard_normal((30, 3))
    names = ["x1", "x2", "x3"]
    out = variance_inflation_factors(X, names)
    assert len(out["vif"]) == 3
    assert all(np.isfinite(v) for v in out["vif"])
