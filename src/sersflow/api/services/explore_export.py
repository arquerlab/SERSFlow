from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np


def _csv_bytes(row: list[Any]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow([_cell(v) for v in row])
    return buf.getvalue().encode("utf-8")


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return value


def _x_label(value: Any) -> str:
    try:
        return f"{float(value):.10g}"
    except (TypeError, ValueError):
        return str(value)


def load_pca_artifact(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("PCA artifact must be a JSON object")
    return data


def iter_matrix_csv_bytes(npz_path: str | Path) -> Iterator[bytes]:
    data = np.load(str(npz_path), allow_pickle=True)
    y = np.asarray(data["Y"])
    x = np.asarray(data["x"]).ravel()
    spectrum_ids = [str(v) for v in np.asarray(data["spectrum_ids"]).ravel().tolist()]
    if y.ndim != 2:
        raise ValueError("matrix Y must be 2-dimensional")
    if y.shape[0] != len(spectrum_ids):
        raise ValueError("spectrum_ids length does not match matrix rows")
    if y.shape[1] != x.size:
        raise ValueError("x length does not match matrix columns")
    yield _csv_bytes(["spectrum_id", *[_x_label(v) for v in x]])
    for sid, row in zip(spectrum_ids, y):
        yield _csv_bytes([sid, *np.asarray(row).tolist()])


def iter_pca_scores_csv_bytes(result: dict[str, Any]) -> Iterator[bytes]:
    scores = np.asarray(result.get("scores", []), dtype=np.float64)
    if scores.ndim != 2:
        raise ValueError("PCA scores must be 2-dimensional")
    spectrum_ids = result.get("spectrum_ids")
    if isinstance(spectrum_ids, list) and len(spectrum_ids) == scores.shape[0]:
        row_ids = [str(v) for v in spectrum_ids]
    else:
        row_ids = [str(i) for i in range(scores.shape[0])]
    yield _csv_bytes(["spectrum_id", *[f"PC{i + 1}" for i in range(scores.shape[1])]])
    for sid, row in zip(row_ids, scores):
        yield _csv_bytes([sid, *row.tolist()])


def iter_pca_loadings_csv_bytes(result: dict[str, Any]) -> Iterator[bytes]:
    components = np.asarray(result.get("components", []), dtype=np.float64)
    if components.ndim != 2:
        raise ValueError("PCA components must be 2-dimensional")
    n_features = components.shape[1]
    x_cm1 = result.get("x_cm1")
    if isinstance(x_cm1, list) and len(x_cm1) == n_features:
        label_name = "x_cm1"
        labels = [_x_label(v) for v in x_cm1]
    else:
        feature_names = result.get("feature_names")
        if isinstance(feature_names, list) and len(feature_names) == n_features:
            labels = [str(v) for v in feature_names]
        else:
            labels = [f"feature_{i}" for i in range(n_features)]
        label_name = "feature_name"
    yield _csv_bytes([label_name, *[f"PC{i + 1}_loading" for i in range(components.shape[0])]])
    for feature_idx, label in enumerate(labels):
        yield _csv_bytes([label, *components[:, feature_idx].tolist()])


def iter_pca_variance_csv_bytes(result: dict[str, Any]) -> Iterator[bytes]:
    ratios = result.get("explained_variance_ratio")
    ratio_values = ratios if isinstance(ratios, list) else []
    n_components = int(result.get("n_components") or len(ratio_values) or len(result.get("components", [])))
    yield _csv_bytes(["component", "explained_variance_ratio"])
    for idx in range(n_components):
        value = ratio_values[idx] if idx < len(ratio_values) else None
        yield _csv_bytes([f"PC{idx + 1}", value])


def iter_pca_mean_csv_bytes(result: dict[str, Any]) -> Iterator[bytes]:
    x_cm1 = result.get("x_cm1")
    mean_spectrum = result.get("mean_spectrum")
    if not isinstance(x_cm1, list) or not isinstance(mean_spectrum, list):
        raise ValueError("PCA artifact does not include a mean spectrum")
    if len(x_cm1) != len(mean_spectrum):
        raise ValueError("x_cm1 length does not match mean_spectrum length")
    yield _csv_bytes(["x_cm1", "mean_intensity"])
    for x_val, y_val in zip(x_cm1, mean_spectrum):
        yield _csv_bytes([_x_label(x_val), y_val])
