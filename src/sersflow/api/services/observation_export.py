from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Iterator

from sersflow.infra.analysis_store import iter_spectrum_rows
from sersflow.infra.datasets_store import spectrum_export_lookup
from sersflow.infra.sqlite_db import connect
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths


def csv_cell(value: Any) -> str:
    """Format a scalar for CSV: None and NaN become empty string."""
    if value is None:
        return ""
    if isinstance(value, float):
        import math

        if math.isnan(value):
            return ""
    return str(value)


def build_analysis_manifest(
    *,
    run_id: str,
    dataset_id: str,
    pipeline_hash: str,
    subset_hash: str,
    created_at: str,
    finished_at: str | None,
    feature_columns: list[str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "pipeline_hash": pipeline_hash,
        "subset_hash": subset_hash,
        "created_at": created_at,
        "finished_at": finished_at,
        "feature_columns": feature_columns,
        "csv_contract": {
            "encoding": "utf-8",
            "delimiter": ",",
            "header_row": True,
            "missing_numeric": "empty_string",
            "orientation": "rows_are_samples_spectra_columns_are_features",
            "notes": "Select numeric feature columns for PCA/correlation; first column is spectrum_id.",
        },
    }


def iter_wide_feature_csv_bytes(
    *,
    run_id: str,
    feature_keys: list[str],
    max_rows: int | None = None,
) -> Iterator[bytes]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["spectrum_id", *feature_keys])
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)

    n = 0
    for sid, feat in iter_spectrum_rows(run_id=run_id, chunk_size=500):
        if max_rows is not None and n >= max_rows:
            break
        row = [sid] + [csv_cell(feat.get(k)) for k in feature_keys]
        w.writerow(row)
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        n += 1


def iter_long_feature_csv_bytes(
    *,
    run_id: str,
    run_id_value: str,
    feature_kind: str = "feature",
    max_spectra: int | None = None,
) -> Iterator[bytes]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", "spectrum_id", "feature_key", "value", "kind"])
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)

    n_spec = 0
    for sid, feat in iter_spectrum_rows(run_id=run_id, chunk_size=500):
        if max_spectra is not None and n_spec >= max_spectra:
            break
        for k, v in feat.items():
            w.writerow([run_id_value, sid, k, csv_cell(v), feature_kind])
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate(0)
        n_spec += 1


def _prepare_observation_wide(
    *,
    labels_by_path: dict[str, dict[str, Any]],
    join_labels: bool,
    join_axes: bool,
) -> tuple[list[str], list[str], dict[str, dict[str, Any]]]:
    """Returns (axis_col_names, meta_keys_sorted, meta_templates_by_path)."""
    axis_cols = (
        ["axis_time_s", "axis_map_x", "axis_map_y", "grid_nx", "grid_ny", "file_kind"]
        if join_axes
        else []
    )
    meta_keys: list[str] = []
    meta_templates: dict[str, dict[str, Any]] = {}
    meta_union: dict[str, None] = {}
    if join_labels:
        for path, lab in labels_by_path.items():
            flat = _flatten_labels(lab)
            meta_templates[path] = flat
            for k in flat:
                meta_union[k] = None
        meta_keys = sorted(meta_union.keys())
    return axis_cols, meta_keys, meta_templates


def _flatten_labels(labels: dict[str, Any], *, prefix: str = "meta_") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in labels.items():
        col = prefix + re.sub(r"[^a-zA-Z0-9_]+", "_", str(k).strip()) if k else f"{prefix}unknown"
        if isinstance(v, (dict, list)):
            out[col] = json.dumps(v, separators=(",", ":"), ensure_ascii=False)
        else:
            out[col] = v
    return out


def iter_observation_wide_dicts(
    *,
    run_id: str,
    feature_keys: list[str],
    spectrum_lookup: dict[str, dict[str, Any]],
    labels_by_path: dict[str, dict[str, Any]],
    join_labels: bool,
    join_axes: bool,
    max_rows: int | None = None,
) -> Iterator[dict[str, Any]]:
    """
    One dict per spectrum: raw Python values (for Parquet); same column order as wide CSV header.
    """
    axis_cols, meta_keys, meta_templates = _prepare_observation_wide(
        labels_by_path=labels_by_path,
        join_labels=join_labels,
        join_axes=join_axes,
    )
    n = 0
    for sid, feat in iter_spectrum_rows(run_id=run_id, chunk_size=500):
        if max_rows is not None and n >= max_rows:
            break
        row: dict[str, Any] = {"spectrum_id": sid}
        for k in feature_keys:
            row[k] = feat.get(k)
        info = spectrum_lookup.get(sid, {})
        rel = str(info.get("relative_path", ""))
        if join_axes:
            row["axis_time_s"] = info.get("axis_time_s")
            row["axis_map_x"] = info.get("axis_map_x")
            row["axis_map_y"] = info.get("axis_map_y")
            row["grid_nx"] = info.get("grid_nx")
            row["grid_ny"] = info.get("grid_ny")
            row["file_kind"] = info.get("file_kind")
        if join_labels:
            flat = meta_templates.get(rel, {})
            for mk in meta_keys:
                row[mk] = flat.get(mk)
        yield row
        n += 1


def write_observation_wide_parquet_bytes(
    *,
    run_id: str,
    feature_keys: list[str],
    spectrum_lookup: dict[str, dict[str, Any]],
    labels_by_path: dict[str, dict[str, Any]],
    join_labels: bool,
    join_axes: bool,
    max_rows: int | None = None,
    batch_size: int = 4096,
) -> bytes:
    """
    Serializes the wide observation table to Apache Parquet (columnar, efficient for wide tables).
    Requires optional dependency ``pyarrow`` (``pip install pyarrow`` or ``pip install sersflow[parquet]``).
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - exercised when extra missing
        raise ImportError(
            "Parquet export requires pyarrow; install with: pip install pyarrow"
        ) from e

    axis_cols, meta_keys, _meta_templates = _prepare_observation_wide(
        labels_by_path=labels_by_path,
        join_labels=join_labels,
        join_axes=join_axes,
    )
    header = ["spectrum_id", *feature_keys, *axis_cols, *meta_keys]

    out = io.BytesIO()
    writer: Any = None
    batch: list[dict[str, Any]] = []
    n_rows = 0

    def flush() -> None:
        nonlocal writer, batch
        if not batch:
            return
        table = pa.Table.from_pylist(batch)
        if writer is None:
            writer = pq.ParquetWriter(out, table.schema)
        writer.write_table(table)
        batch = []

    for row in iter_observation_wide_dicts(
        run_id=run_id,
        feature_keys=feature_keys,
        spectrum_lookup=spectrum_lookup,
        labels_by_path=labels_by_path,
        join_labels=join_labels,
        join_axes=join_axes,
        max_rows=max_rows,
    ):
        n_rows += 1
        batch.append({k: row.get(k) for k in header})
        if len(batch) >= batch_size:
            flush()

    flush()
    if writer is not None:
        writer.close()
    if n_rows == 0:
        empty = {h: [] for h in header}
        pq.write_table(pa.Table.from_pydict(empty), out)
    return out.getvalue()


def iter_observation_wide_csv_bytes(
    *,
    run_id: str,
    dataset_id: str,
    feature_keys: list[str],
    spectrum_lookup: dict[str, dict[str, Any]],
    labels_by_path: dict[str, dict[str, Any]],
    join_labels: bool,
    join_axes: bool,
    max_rows: int | None = None,
) -> Iterator[bytes]:
    """
    Wide CSV: spectrum_id, feature columns, optional axis_* / grid_*, optional meta_* from labels.
    """
    buf = io.StringIO()
    w = csv.writer(buf)

    axis_cols, meta_keys, meta_templates = _prepare_observation_wide(
        labels_by_path=labels_by_path,
        join_labels=join_labels,
        join_axes=join_axes,
    )

    header = ["spectrum_id", *feature_keys, *axis_cols, *meta_keys]
    w.writerow(header)
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)

    n = 0
    for sid, feat in iter_spectrum_rows(run_id=run_id, chunk_size=500):
        if max_rows is not None and n >= max_rows:
            break
        row: list[Any] = [sid] + [csv_cell(feat.get(k)) for k in feature_keys]
        info = spectrum_lookup.get(sid, {})
        rel = info.get("relative_path", "")
        if join_axes:
            row.extend(
                [
                    csv_cell(info.get("axis_time_s")),
                    csv_cell(info.get("axis_map_x")),
                    csv_cell(info.get("axis_map_y")),
                    csv_cell(info.get("grid_nx")),
                    csv_cell(info.get("grid_ny")),
                    csv_cell(info.get("file_kind")),
                ]
            )
        if join_labels:
            flat = meta_templates.get(str(rel), {})
            row.extend([csv_cell(flat.get(k)) for k in meta_keys])
        w.writerow(row)
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        n += 1


def iter_observation_long_csv_bytes(
    *,
    run_id: str,
    run_id_value: str,
    dataset_id: str,
    spectrum_lookup: dict[str, dict[str, Any]],
    labels_by_path: dict[str, dict[str, Any]],
    join_labels: bool,
    join_axes: bool,
    max_spectra: int | None = None,
) -> Iterator[bytes]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", "dataset_id", "spectrum_id", "feature_key", "value", "kind"])
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)

    n_spec = 0
    for sid, feat in iter_spectrum_rows(run_id=run_id, chunk_size=500):
        if max_spectra is not None and n_spec >= max_spectra:
            break
        for k, v in feat.items():
            w.writerow([run_id_value, dataset_id, sid, k, csv_cell(v), "feature"])
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate(0)

        info = spectrum_lookup.get(sid, {})
        rel = str(info.get("relative_path", ""))

        if join_axes:
            for ak, av in (
                ("axis_time_s", info.get("axis_time_s")),
                ("axis_map_x", info.get("axis_map_x")),
                ("axis_map_y", info.get("axis_map_y")),
                ("grid_nx", info.get("grid_nx")),
                ("grid_ny", info.get("grid_ny")),
                ("file_kind", info.get("file_kind")),
            ):
                w.writerow([run_id_value, dataset_id, sid, ak, csv_cell(av), "axis"])
                yield buf.getvalue().encode("utf-8")
                buf.seek(0)
                buf.truncate(0)

        if join_labels and rel:
            flat = _flatten_labels(labels_by_path.get(rel, {}))
            for mk, mv in flat.items():
                w.writerow([run_id_value, dataset_id, sid, mk, csv_cell(mv), "meta"])
                yield buf.getvalue().encode("utf-8")
                buf.seek(0)
                buf.truncate(0)

        n_spec += 1


def list_observation_axis_and_meta_keys_for_dataset(dataset_id: str) -> tuple[list[str], list[str]]:
    """Returns (axis column names, sorted meta_* keys) for upload labels union across the dataset."""
    lookup = spectrum_export_lookup(dataset_id)
    paths = list(
        {str(lookup[sid].get("relative_path", "")) for sid in lookup if lookup[sid].get("relative_path")}
    )
    labels_by_path: dict[str, dict[str, Any]] = {}
    if paths:
        with connect() as con:
            labels_by_path = fetch_upload_labels_for_paths(con, paths)
    axis_cols, meta_keys, _ = _prepare_observation_wide(
        labels_by_path=labels_by_path,
        join_labels=True,
        join_axes=True,
    )
    return axis_cols, meta_keys
