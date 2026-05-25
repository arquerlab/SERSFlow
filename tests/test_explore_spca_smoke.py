"""Smoke tests for sparse PCA helpers."""

from __future__ import annotations

import numpy as np

from sersflow.api.services.explore_stats import run_fpca_discrete, run_pca, run_spca


def test_run_spca_smoke_shapes() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_normal((24, 10))
    names = [f"f{i}" for i in range(10)]
    out = run_spca(X, names, n_components=4, alpha=0.5, ridge_alpha=1e-4)
    assert out["method"] == "spca"
    assert len(out["scores"]) == 24
    assert len(out["scores"][0]) == 4


def test_run_pca_standard_scaler_records_metadata_and_changes_scaled_features() -> None:
    X = np.asarray(
        [
            [0.0, 0.0],
            [1000.0, 1.0],
            [2000.0, 0.0],
            [3000.0, 1.0],
            [4000.0, 0.0],
            [5000.0, 1.0],
        ],
        dtype=np.float64,
    )
    names = ["large_scale", "small_scale"]

    unscaled = run_pca(X, names, n_components=2)
    scaled = run_pca(X, names, n_components=2, scaler="standard")

    assert unscaled["scaler"] == "none"
    assert unscaled["pca_preprocessing"] == {"scaler": "none"}
    assert scaled["scaler"] == "standard"
    assert scaled["pca_preprocessing"]["scaler"] == "standard"
    assert scaled["pca_preprocessing"]["mean"] == np.mean(X, axis=0).tolist()
    assert len(scaled["pca_preprocessing"]["scale"]) == 2
    assert not np.allclose(
        unscaled["explained_variance_ratio"],
        scaled["explained_variance_ratio"],
    )


def test_run_fpca_discrete_standard_scaler_preserves_raw_mean_spectrum() -> None:
    Y = np.asarray(
        [
            [10.0, 100.0, 0.0],
            [12.0, 140.0, 1.0],
            [14.0, 120.0, 0.0],
            [16.0, 180.0, 1.0],
        ],
        dtype=np.float64,
    )
    x = np.asarray([100.0, 101.0, 102.0], dtype=np.float64)
    spectrum_ids = ["s1", "s2", "s3", "s4"]

    out = run_fpca_discrete(
        Y,
        x,
        spectrum_ids,
        n_components=2,
        scaler="standard",
    )

    assert out["scaler"] == "standard"
    assert out["pca_preprocessing"]["scaler"] == "standard"
    assert out["pca_preprocessing"]["mean"] == np.mean(Y, axis=0).tolist()
    assert len(out["pca_preprocessing"]["scale"]) == Y.shape[1]
    assert out["mean_spectrum"] == np.mean(Y, axis=0).tolist()
    assert out["spectrum_ids"] == spectrum_ids
