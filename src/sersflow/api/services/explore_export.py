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


def _parse_float_cell(value: Any, *, label: str) -> float:
    if value is None:
        return float("nan")
    text = str(value).strip()
    if not text:
        return float("nan")
    try:
        return float(text)
    except ValueError as e:
        raise ValueError(f"Invalid numeric value for {label}: {text!r}") from e


def parse_matrix_csv(text: str | bytes) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Parse exported matrix CSV into (Y, x, spectrum_ids).

    Expected format matches ``iter_matrix_csv_bytes``:
    header ``spectrum_id,<wavenumber>,...`` then one row per spectrum.
    """
    if isinstance(text, bytes):
        raw = text.decode("utf-8-sig")
    else:
        raw = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(raw))
    try:
        header = next(reader)
    except StopIteration as e:
        raise ValueError("Matrix CSV is empty") from e
    if not header or str(header[0]).strip().lower() not in {"spectrum_id", "spectrumid"}:
        raise ValueError("Matrix CSV header must start with spectrum_id")
    if len(header) < 2:
        raise ValueError("Matrix CSV must include at least one wavenumber column")
    x = np.asarray(
        [_parse_float_cell(v, label=f"header column {i + 1}") for i, v in enumerate(header[1:])],
        dtype=np.float64,
    )
    if x.size < 1:
        raise ValueError("Matrix CSV must include at least one wavenumber column")
    if not np.all(np.isfinite(x)):
        raise ValueError("Matrix CSV wavenumber header contains non-finite values")

    sids: list[str] = []
    rows: list[np.ndarray] = []
    for row_idx, row in enumerate(reader, start=2):
        if not row or all(not str(c).strip() for c in row):
            continue
        if len(row) != len(header):
            raise ValueError(
                f"Matrix CSV row {row_idx} has {len(row)} columns, expected {len(header)}"
            )
        sid = str(row[0]).strip()
        if not sid:
            raise ValueError(f"Matrix CSV row {row_idx} is missing spectrum_id")
        vals = np.asarray(
            [_parse_float_cell(v, label=f"row {row_idx} col {i + 2}") for i, v in enumerate(row[1:])],
            dtype=np.float32,
        )
        sids.append(sid)
        rows.append(vals)

    if not rows:
        raise ValueError("Matrix CSV has no spectrum rows")
    y = np.stack(rows, axis=0)
    return y, x, sids


def iter_pca_scores_csv_bytes(
    result: dict[str, Any],
    *,
    meta_columns: list[str] | None = None,
    meta_by_spectrum_id: dict[str, dict[str, Any]] | None = None,
) -> Iterator[bytes]:
    scores = np.asarray(result.get("scores", []), dtype=np.float64)
    if scores.ndim != 2:
        raise ValueError("PCA scores must be 2-dimensional")
    spectrum_ids = result.get("spectrum_ids")
    if isinstance(spectrum_ids, list) and len(spectrum_ids) == scores.shape[0]:
        row_ids = [str(v) for v in spectrum_ids]
    else:
        row_ids = [str(i) for i in range(scores.shape[0])]
    extra_cols = [str(c) for c in (meta_columns or []) if str(c).strip()]
    meta_map = meta_by_spectrum_id or {}
    yield _csv_bytes(["spectrum_id", *[f"PC{i + 1}" for i in range(scores.shape[1])], *extra_cols])
    for sid, row in zip(row_ids, scores):
        meta = meta_map.get(sid) or {}
        extras = [meta.get(c) for c in extra_cols]
        yield _csv_bytes([sid, *row.tolist(), *extras])


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
