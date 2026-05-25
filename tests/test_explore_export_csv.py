from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import numpy as np

from sersflow.api.services.explore_export import (
    iter_matrix_csv_bytes,
    iter_pca_loadings_csv_bytes,
    iter_pca_mean_csv_bytes,
    iter_pca_scores_csv_bytes,
    iter_pca_variance_csv_bytes,
    load_pca_artifact,
)


def _rows(chunks: object) -> list[list[str]]:
    text = b"".join(chunks).decode("utf-8")
    return list(csv.reader(io.StringIO(text)))


def test_matrix_csv_exports_spectrum_rows_and_wavenumber_columns(tmp_path: Path) -> None:
    npz_path = tmp_path / "matrix.npz"
    np.savez_compressed(
        npz_path,
        Y=np.asarray([[1.0, 2.0], [3.5, 4.5]], dtype=np.float32),
        x=np.asarray([100.0, 101.5], dtype=np.float64),
        spectrum_ids=np.asarray(["s1", "s2"]),
    )

    rows = _rows(iter_matrix_csv_bytes(npz_path))

    assert rows[0] == ["spectrum_id", "100", "101.5"]
    assert rows[1][0] == "s1"
    assert rows[2][0] == "s2"
    assert rows[2][1:] == ["3.5", "4.5"]


def test_pca_csv_exports_scores_loadings_variance_and_mean(tmp_path: Path) -> None:
    artifact = {
        "n_components": 2,
        "explained_variance_ratio": [0.75, 0.25],
        "components": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        "scores": [[1.0, 2.0], [3.0, 4.0]],
        "spectrum_ids": ["s1", "s2"],
        "x_cm1": [100.0, 101.0, 102.0],
        "mean_spectrum": [10.0, 11.0, 12.0],
    }
    path = tmp_path / "fpca_discrete.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    loaded = load_pca_artifact(path)

    assert _rows(iter_pca_scores_csv_bytes(loaded))[0] == ["spectrum_id", "PC1", "PC2"]
    assert _rows(iter_pca_scores_csv_bytes(loaded))[1] == ["s1", "1.0", "2.0"]
    assert _rows(iter_pca_loadings_csv_bytes(loaded))[0] == ["x_cm1", "PC1_loading", "PC2_loading"]
    assert _rows(iter_pca_loadings_csv_bytes(loaded))[1] == ["100", "0.1", "0.4"]
    assert _rows(iter_pca_variance_csv_bytes(loaded))[1] == ["PC1", "0.75"]
    assert _rows(iter_pca_mean_csv_bytes(loaded))[1] == ["100", "10.0"]
