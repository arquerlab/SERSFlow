from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

import numpy as np
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from sersflow.api.schemas.datasets import Dataset, DatasetListItem, DatasetMetadata, SpectrumRef
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.upload_registry import resolve_uploaded_path, upload_root
from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset
from sersflow.infra.blob_store import delete_blob_if_unreferenced, resolve_blob_path, store_blob_from_file
from sersflow.infra.sqlite_db import connect


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    metadata: DatasetMetadata
    spectra: list[SpectrumRef]


def _migrate_dataset_schema(con: sqlite3.Connection) -> None:
    for col, decl in (
        ("axis_time_s", "REAL"),
        ("axis_map_x", "REAL"),
        ("axis_map_y", "REAL"),
        ("blob_id", "TEXT"),
        ("blob_relative_path", "TEXT"),
        ("original_relative_path", "TEXT"),
    ):
        try:
            con.execute(f"ALTER TABLE dataset_spectra ADD COLUMN {col} {decl} NULL")
        except sqlite3.OperationalError:
            pass
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS dataset_file_meta (
          dataset_id TEXT NOT NULL,
          relative_path TEXT NOT NULL,
          grid_nx INTEGER NULL,
          grid_ny INTEGER NULL,
          kind TEXT NOT NULL,
          PRIMARY KEY (dataset_id, relative_path),
          FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_dataset_file_meta_dataset ON dataset_file_meta(dataset_id);
        """
    )


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets (
              dataset_id TEXT PRIMARY KEY,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dataset_spectra (
              dataset_id TEXT NOT NULL,
              spectrum_id TEXT NOT NULL,
              relative_path TEXT NOT NULL,
              record_index INTEGER NULL,
              position INTEGER NOT NULL,
              PRIMARY KEY (dataset_id, spectrum_id),
              FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_dataset_spectra_dataset_id ON dataset_spectra(dataset_id);
            """
        )
        _migrate_dataset_schema(con)
        _backfill_existing_blob_refs(con)


def _source_path_for_ref(ref: SpectrumRef):
    if ref.blob_relative_path:
        return resolve_blob_path(ref.blob_relative_path)
    root = upload_root()
    return resolve_uploaded_path(root, ref.relative_path)


def _with_blob_refs(spectra: Iterable[SpectrumRef]) -> list[SpectrumRef]:
    root = upload_root()
    blob_by_path: dict[str, tuple[str, str]] = {}
    out: list[SpectrumRef] = []
    for s in spectra:
        if s.blob_id and s.blob_relative_path:
            out.append(s)
            continue
        pair = blob_by_path.get(s.relative_path)
        if pair is None:
            try:
                source = resolve_uploaded_path(root, s.relative_path)
                if not source.exists():
                    raise FileNotFoundError(s.relative_path)
                stored = store_blob_from_file(source)
                pair = (stored.blob_id, stored.blob_relative_path)
                blob_by_path[s.relative_path] = pair
            except (OSError, ValueError, FileNotFoundError):
                pair = ("", "")
        blob_id, blob_rel = pair
        if blob_id and blob_rel:
            out.append(
                s.model_copy(
                    update={
                        "blob_id": blob_id,
                        "blob_relative_path": blob_rel,
                        "original_relative_path": s.original_relative_path or s.relative_path,
                    }
                )
            )
        else:
            out.append(s)
    return out


def _backfill_existing_blob_refs(con: sqlite3.Connection) -> None:
    rows = con.execute(
        """
        SELECT DISTINCT relative_path
        FROM dataset_spectra
        WHERE (blob_relative_path IS NULL OR blob_relative_path = '')
        """
    ).fetchall()
    if not rows:
        return
    root = upload_root()
    for row in rows:
        rel = str(row["relative_path"])
        try:
            source = resolve_uploaded_path(root, rel)
            if not source.exists():
                continue
            stored = store_blob_from_file(source)
        except (OSError, ValueError, FileNotFoundError):
            continue
        con.execute(
            """
            UPDATE dataset_spectra
            SET blob_id = ?, blob_relative_path = ?, original_relative_path = COALESCE(original_relative_path, relative_path)
            WHERE relative_path = ? AND (blob_relative_path IS NULL OR blob_relative_path = '')
            """,
            (stored.blob_id, stored.blob_relative_path, rel),
        )


def _populate_axes_for_dataset(dataset_id: str, spectra: list[SpectrumRef]) -> None:
    by_path: dict[str, list[SpectrumRef]] = {}
    for s in spectra:
        by_path.setdefault(s.relative_path, []).append(s)

    with connect() as con:
        for rel, refs in by_path.items():
            try:
                p = _source_path_for_ref(refs[0])
                ds = load_dataset(p)
            except (OSError, ValueError, FileNotFoundError):
                continue

            if isinstance(ds, SpectrumDataset):
                con.execute(
                    """
                    INSERT OR REPLACE INTO dataset_file_meta(dataset_id, relative_path, grid_nx, grid_ny, kind)
                    VALUES (?,?,?,?,?)
                    """,
                    (dataset_id, rel, 1, 1, "single"),
                )
                for ref in refs:
                    con.execute(
                        """
                        UPDATE dataset_spectra
                        SET axis_time_s=NULL, axis_map_x=NULL, axis_map_y=NULL
                        WHERE dataset_id=? AND spectrum_id=?
                        """,
                        (dataset_id, ref.spectrum_id),
                    )
            elif isinstance(ds, SeriesDataset):
                nx = int(ds.spectra.shape[0])
                con.execute(
                    """
                    INSERT OR REPLACE INTO dataset_file_meta(dataset_id, relative_path, grid_nx, grid_ny, kind)
                    VALUES (?,?,?,?,?)
                    """,
                    (dataset_id, rel, nx, 1, "series"),
                )
                for ref in refs:
                    idx = int(ref.record_index or 0)
                    t = float(ds.axis[idx])
                    con.execute(
                        """
                        UPDATE dataset_spectra
                        SET axis_time_s=?, axis_map_x=NULL, axis_map_y=NULL
                        WHERE dataset_id=? AND spectrum_id=?
                        """,
                        (t, dataset_id, ref.spectrum_id),
                    )
            elif isinstance(ds, MapDataset):
                ux = int(len(np.unique(np.asarray(ds.xpos))))
                uy = int(len(np.unique(np.asarray(ds.ypos))))
                con.execute(
                    """
                    INSERT OR REPLACE INTO dataset_file_meta(dataset_id, relative_path, grid_nx, grid_ny, kind)
                    VALUES (?,?,?,?,?)
                    """,
                    (dataset_id, rel, ux, uy, "map"),
                )
                for ref in refs:
                    idx = int(ref.record_index or 0)
                    con.execute(
                        """
                        UPDATE dataset_spectra
                        SET axis_time_s=NULL, axis_map_x=?, axis_map_y=?
                        WHERE dataset_id=? AND spectrum_id=?
                        """,
                        (float(ds.xpos[idx]), float(ds.ypos[idx]), dataset_id, ref.spectrum_id),
                    )


def spectrum_export_lookup(dataset_id: str) -> dict[str, dict[str, Any]]:
    """
    Map spectrum_id -> relative_path, axis_*, grid_*, file_kind for CSV joins.
    """
    ensure_schema()
    with connect() as con:
        rows = con.execute(
            """
            SELECT ds.spectrum_id, ds.relative_path, ds.blob_id, ds.blob_relative_path, ds.original_relative_path,
                   ds.axis_time_s, ds.axis_map_x, ds.axis_map_y,
                   fm.grid_nx, fm.grid_ny, fm.kind AS file_kind
            FROM dataset_spectra ds
            LEFT JOIN dataset_file_meta fm
              ON fm.dataset_id = ds.dataset_id AND fm.relative_path = ds.relative_path
            WHERE ds.dataset_id = ?
            """,
            (dataset_id,),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[str(r["spectrum_id"])] = {
            "relative_path": r["relative_path"],
            "blob_id": r["blob_id"],
            "blob_relative_path": r["blob_relative_path"],
            "original_relative_path": r["original_relative_path"],
            "axis_time_s": r["axis_time_s"],
            "axis_map_x": r["axis_map_x"],
            "axis_map_y": r["axis_map_y"],
            "grid_nx": r["grid_nx"],
            "grid_ny": r["grid_ny"],
            "file_kind": r["file_kind"],
        }
    return out


def iter_spectrum_axes_page(
    *,
    dataset_id: str,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    ensure_schema()
    lim = max(1, min(int(limit), 2000))
    off = max(0, int(offset))
    with connect() as con:
        total = con.execute(
            "SELECT COUNT(*) AS c FROM dataset_spectra WHERE dataset_id=?",
            (dataset_id,),
        ).fetchone()
        ntot = int(total["c"]) if total else 0
        rows = con.execute(
            """
            SELECT ds.spectrum_id, ds.relative_path, ds.record_index,
                   ds.blob_id, ds.blob_relative_path, ds.original_relative_path,
                   ds.axis_time_s, ds.axis_map_x, ds.axis_map_y,
                   fm.grid_nx, fm.grid_ny, fm.kind AS file_kind
            FROM dataset_spectra ds
            LEFT JOIN dataset_file_meta fm
              ON fm.dataset_id = ds.dataset_id AND fm.relative_path = ds.relative_path
            WHERE ds.dataset_id = ?
            ORDER BY ds.position ASC
            LIMIT ? OFFSET ?
            """,
            (dataset_id, lim, off),
        ).fetchall()
    items = [dict(r) for r in rows]
    return items, ntot


def create_dataset(*, metadata: DatasetMetadata, spectra: Iterable[SpectrumRef]) -> DatasetRecord:
    ensure_schema()
    dataset_id = f"ds_{uuid4().hex}"
    created_at = _utc_now_iso()

    md = metadata.model_copy()
    if md.created_at is None:
        md.created_at = created_at

    spectra_list = _with_blob_refs(spectra)
    with connect() as con:
        con.execute(
            "INSERT INTO datasets(dataset_id, metadata_json, created_at, updated_at) VALUES (?,?,?,?)",
            (dataset_id, md.model_dump_json(), created_at, created_at),
        )
        con.executemany(
            """
            INSERT INTO dataset_spectra(
              dataset_id, spectrum_id, relative_path, record_index, position,
              blob_id, blob_relative_path, original_relative_path
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    dataset_id,
                    s.spectrum_id,
                    s.relative_path,
                    s.record_index,
                    i,
                    s.blob_id,
                    s.blob_relative_path,
                    s.original_relative_path,
                )
                for i, s in enumerate(spectra_list)
            ],
        )
    _populate_axes_for_dataset(dataset_id, spectra_list)
    return DatasetRecord(dataset_id=dataset_id, metadata=md, spectra=spectra_list)


def _load_metadata(metadata_json: str) -> DatasetMetadata:
    try:
        obj = json.loads(metadata_json)
    except json.JSONDecodeError:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    return DatasetMetadata.model_validate(obj)


def get_dataset(dataset_id: str) -> DatasetRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute(
            "SELECT dataset_id, metadata_json FROM datasets WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()
        if row is None:
            return None
        md = _load_metadata(row["metadata_json"])
        spectra_rows = con.execute(
            """
            SELECT spectrum_id, relative_path, record_index, blob_id, blob_relative_path, original_relative_path
            FROM dataset_spectra
            WHERE dataset_id = ?
            ORDER BY position ASC
            """,
            (dataset_id,),
        ).fetchall()
        spectra = [
            SpectrumRef(
                spectrum_id=r["spectrum_id"],
                relative_path=r["relative_path"],
                record_index=r["record_index"],
                blob_id=r["blob_id"],
                blob_relative_path=r["blob_relative_path"],
                original_relative_path=r["original_relative_path"],
            )
            for r in spectra_rows
        ]
        return DatasetRecord(dataset_id=row["dataset_id"], metadata=md, spectra=spectra)


def list_datasets(*, limit: int = 50, offset: int = 0) -> list[DatasetListItem]:
    ensure_schema()
    with connect() as con:
        rows = con.execute(
            """
            SELECT d.dataset_id, d.metadata_json, COUNT(ds.spectrum_id) AS spectrum_count
            FROM datasets d
            LEFT JOIN dataset_spectra ds ON ds.dataset_id = d.dataset_id
            GROUP BY d.dataset_id
            ORDER BY d.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (int(limit), int(offset)),
        ).fetchall()
        out: list[DatasetListItem] = []
        for r in rows:
            out.append(
                DatasetListItem(
                    dataset_id=r["dataset_id"],
                    count=int(r["spectrum_count"] or 0),
                    metadata=_load_metadata(r["metadata_json"]),
                )
            )
        return out


def to_schema(record: DatasetRecord) -> Dataset:
    return Dataset(dataset_id=record.dataset_id, spectra=record.spectra, metadata=record.metadata)


def delete_dataset(dataset_id: str) -> bool:
    """
    Delete a dataset and its spectra rows.

    Notes:
    - `dataset_spectra` rows are removed via ON DELETE CASCADE.
    - Sessions referencing this dataset are cleaned up separately (sessions table has no FK).
    """
    ensure_schema()
    blob_paths = _blob_paths_for_dataset(dataset_id)
    with connect() as con:
        cur = con.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))
        deleted = int(cur.rowcount or 0) > 0
    if deleted:
        delete_unreferenced_dataset_blobs(blob_paths)
    return deleted


def delete_all_datasets() -> int:
    """
    Delete all datasets.

    Returns:
        Number of dataset rows deleted.
    """
    ensure_schema()
    blob_paths = _all_blob_paths()
    with connect() as con:
        cur = con.execute("DELETE FROM datasets")
        deleted = int(cur.rowcount or 0)
    if deleted:
        delete_unreferenced_dataset_blobs(blob_paths)
    return deleted


def _blob_paths_for_dataset(dataset_id: str) -> list[str]:
    with connect() as con:
        rows = con.execute(
            "SELECT DISTINCT blob_relative_path FROM dataset_spectra WHERE dataset_id = ? AND blob_relative_path IS NOT NULL",
            (dataset_id,),
        ).fetchall()
    return [str(r["blob_relative_path"]) for r in rows if r["blob_relative_path"]]


def _all_blob_paths() -> list[str]:
    with connect() as con:
        rows = con.execute("SELECT DISTINCT blob_relative_path FROM dataset_spectra WHERE blob_relative_path IS NOT NULL").fetchall()
    return [str(r["blob_relative_path"]) for r in rows if r["blob_relative_path"]]


def delete_unreferenced_dataset_blobs(blob_relative_paths: Iterable[str]) -> int:
    unique = sorted({p for p in blob_relative_paths if p})
    removed = 0
    with connect() as con:
        for blob_rel in unique:
            row = con.execute(
                "SELECT COUNT(*) AS c FROM dataset_spectra WHERE blob_relative_path = ?",
                (blob_rel,),
            ).fetchone()
            if row and int(row["c"] or 0) > 0:
                continue
            try:
                if delete_blob_if_unreferenced(blob_rel):
                    removed += 1
            except (OSError, ValueError, FileNotFoundError):
                continue
    return removed


def path_only_dataset_reference_counts(relative_paths: Iterable[str]) -> dict[str, int]:
    paths = [p for p in dict.fromkeys(relative_paths) if p]
    if not paths:
        return {}
    placeholders = ",".join("?" for _ in paths)
    ensure_schema()
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT relative_path, COUNT(*) AS c
            FROM dataset_spectra
            WHERE relative_path IN ({placeholders})
              AND (blob_relative_path IS NULL OR blob_relative_path = '')
            GROUP BY relative_path
            """,
            paths,
        ).fetchall()
    return {str(r["relative_path"]): int(r["c"] or 0) for r in rows}


def relink_path_only_dataset_rows_from_upload_items(upload_items: Iterable[dict[str, Any]]) -> int:
    """
    Best-effort repair for old datasets whose upload file was unloaded before blobs existed.

    Exact relative_path matches are always allowed. Filename+size matches are only used
    when the old unloaded-registry entry and the new upload candidate are unique.
    """
    items = [dict(x) for x in upload_items if x]
    if not items:
        return 0
    ensure_schema()

    from sersflow.core.io.upload_registry import read_unloaded_registry

    root = upload_root()
    unloaded_meta: dict[str, tuple[str, int]] = {}
    for row in read_unloaded_registry(root):
        rel = str(row.get("relative_path") or "")
        fname = str(row.get("filename") or "")
        try:
            size = int(row.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        if rel and fname and size >= 0:
            unloaded_meta[rel] = (fname, size)

    by_exact = {str(item.get("relative_path") or ""): item for item in items}
    by_name_size: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in items:
        fname = str(item.get("filename") or "")
        try:
            size = int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        if fname:
            by_name_size.setdefault((fname, size), []).append(item)

    with connect() as con:
        rows = con.execute(
            """
            SELECT DISTINCT relative_path
            FROM dataset_spectra
            WHERE blob_relative_path IS NULL OR blob_relative_path = ''
            """
        ).fetchall()

    relinked = 0
    for row in rows:
        old_rel = str(row["relative_path"])
        item = by_exact.get(old_rel)
        if item is None:
            meta = unloaded_meta.get(old_rel)
            if meta is not None:
                candidates = by_name_size.get(meta) or []
                if len(candidates) == 1:
                    item = candidates[0]
        if item is None:
            continue

        new_rel = str(item.get("relative_path") or "")
        try:
            source = resolve_uploaded_path(root, new_rel)
            if not source.exists():
                continue
            stored = store_blob_from_file(source)
        except (OSError, ValueError, FileNotFoundError):
            continue
        with connect() as con:
            cur = con.execute(
                """
                UPDATE dataset_spectra
                SET blob_id = ?, blob_relative_path = ?, original_relative_path = COALESCE(original_relative_path, relative_path)
                WHERE relative_path = ? AND (blob_relative_path IS NULL OR blob_relative_path = '')
                """,
                (stored.blob_id, stored.blob_relative_path, old_rel),
            )
            relinked += int(cur.rowcount or 0)
    return relinked

