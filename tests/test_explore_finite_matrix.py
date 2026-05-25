from __future__ import annotations

import numpy as np
import pytest

from sersflow.api.services.explore_stats import (
    correlation_bundle,
    drop_all_nan_columns,
    prepare_multivariate_matrix,
)


def test_drop_all_nan_columns_raises_when_all_missing() -> None:
    X = np.full((3, 2), np.nan)
    with pytest.raises(ValueError, match="every column"):
        drop_all_nan_columns(X, ["a", "b"])


def test_drop_all_nan_columns_keeps_finite_columns() -> None:
    X = np.array([[np.nan, 1.0], [np.nan, 2.0]], dtype=float)
    out, names = drop_all_nan_columns(X, ["gone", "ok"])
    assert names == ["ok"]
    assert out.shape == (2, 1)


def test_prepare_multivariate_prefers_complete_cases() -> None:
    X = np.array([[1.0, 2.0], [np.nan, 3.0], [4.0, np.nan]], dtype=float)
    sids = ["a", "b", "c"]
    out, names, sids_out, meta = prepare_multivariate_matrix(X, ["f0", "f1"], sids)
    assert meta["rows_used"] == "complete_cases"
    assert names == ["f0", "f1"]
    assert sids_out == ["a"]
    assert out.shape == (1, 2)
    assert np.allclose(out[0], [1.0, 2.0])


def test_prepare_multivariate_mean_imputes_when_no_complete_row() -> None:
    X = np.array([[1.0, np.nan], [np.nan, 2.0]], dtype=float)
    sids = ["s0", "s1"]
    out, names, sids_out, meta = prepare_multivariate_matrix(X, ["f0", "f1"], sids)
    assert meta["rows_used"] == "all_spectra_mean_imputed"
    assert sids_out == ["s0", "s1"]
    assert out.shape == (2, 2)
    assert np.all(np.isfinite(out))


def test_correlation_bundle_runs_with_no_complete_rows_across_columns() -> None:
    """Mixing columns that miss on different rows: pairwise r still defined."""
    X = np.array([[1.0, np.nan, 3.0], [np.nan, 2.0, 4.0]], dtype=float)
    X, names = drop_all_nan_columns(X, ["a", "b", "c"])
    res = correlation_bundle(X, names)
    assert res["feature_names"] == names
    assert "R" in res
