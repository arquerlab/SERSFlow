from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sersflow.api.schemas.datasets import DatasetImportResponse, DatasetMetadata, SpectrumRef
from sersflow.infra.blob_store import data_root, ensure_within_data_root, resolve_blob_path
from sersflow.infra.datasets_store import create_dataset, get_dataset, to_schema
from sersflow.infra.sqlite_db import connect
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, upsert_upload_labels, with_connection

DATASET_SCHEMA_VERSION = "sersflow.dataset.v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dataset_rows(dataset_id: str) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT spectrum_id, relative_path, record_index, position,
                   blob_id, blob_relative_path, original_relative_path,
                   axis_time_s, axis_map_x, axis_map_y
            FROM dataset_spectra
            WHERE dataset_id = ?
            ORDER BY position ASC
            """,
            (dataset_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _file_meta_rows(dataset_id: str) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT relative_path, grid_nx, grid_ny, kind
            FROM dataset_file_meta
            WHERE dataset_id = ?
            ORDER BY relative_path ASC
            """,
            (dataset_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _labels_for_dataset_paths(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    paths = []
    for row in rows:
        for key in ("relative_path", "original_relative_path"):
            val = row.get(key)
            if val:
                paths.append(str(val))
    con = with_connection()
    try:
        return fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()


def export_dataset_package(dataset_id: str, *, owner_user_id: str) -> tuple[bytes, str]:
    rec = get_dataset(dataset_id, owner_user_id=owner_user_id)
    if rec is None:
        raise FileNotFoundError(dataset_id)
    rows = _dataset_rows(dataset_id)
    file_meta = _file_meta_rows(dataset_id)
    labels = _labels_for_dataset_paths(rows)

    blob_entries: dict[str, dict[str, Any]] = {}
    blob_payloads: dict[str, Path] = {}
    missing: list[str] = []
    for row in rows:
        blob_rel = row.get("blob_relative_path")
        blob_id = row.get("blob_id")
        if not blob_rel or not blob_id:
            missing.append(str(row.get("relative_path") or row.get("spectrum_id") or "unknown"))
            continue
        try:
            p = resolve_blob_path(str(blob_rel))
        except FileNotFoundError:
            missing.append(str(row.get("relative_path") or row.get("spectrum_id") or "unknown"))
            continue
        arcname = str(Path("blobs") / Path(str(blob_rel)).name[:2] / Path(str(blob_rel)).name).replace("\\", "/")
        blob_entries[str(blob_id)] = {
            "blob_id": str(blob_id),
            "blob_relative_path": str(blob_rel),
            "zip_path": arcname,
            "size_bytes": int(p.stat().st_size),
        }
        blob_payloads[arcname] = p

    if missing:
        raise ValueError("Dataset export is missing durable blob data for: " + ", ".join(missing[:20]))

    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "created_by": "SERSFlow",
        "exported_at": _utc_now_iso(),
        "dataset": {
            "source_dataset_id": dataset_id,
            "metadata": rec.metadata.model_dump(mode="json"),
        },
        "spectra": rows,
        "file_meta": file_meta,
        "labels": labels,
        "blobs": blob_entries,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        zf.writestr(
            "README.txt",
            "SERSFlow dataset package. Inspect manifest.json for metadata and import this zip through SERSFlow.\n",
        )
        for arcname, path in sorted(blob_payloads.items()):
            zf.write(path, arcname)
    name = (rec.metadata.name or dataset_id).strip() or dataset_id
    safe = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in name)
    return buf.getvalue(), f"{safe}.sersflow-dataset.zip"


def import_dataset_package(data: bytes, *, owner_user_id: str) -> DatasetImportResponse:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
    except zipfile.BadZipFile as e:
        raise ValueError("Invalid dataset package zip") from e
    with zf:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError as e:
            raise ValueError("Dataset package is missing manifest.json") from e
        except json.JSONDecodeError as e:
            raise ValueError("Dataset manifest is not valid JSON") from e
        if manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
            raise ValueError(f"Unsupported dataset package schema: {manifest.get('schema_version')}")

        blobs = manifest.get("blobs")
        if not isinstance(blobs, dict):
            raise ValueError("Dataset manifest missing blobs map")
        imported_blobs = 0
        for entry in blobs.values():
            if not isinstance(entry, dict):
                continue
            blob_rel = str(entry.get("blob_relative_path") or "")
            zip_path = str(entry.get("zip_path") or "")
            blob_id = str(entry.get("blob_id") or "")
            if not blob_rel or not zip_path or not blob_id:
                raise ValueError("Dataset manifest has an incomplete blob entry")
            payload = zf.read(zip_path)
            if _sha256_bytes(payload) != blob_id:
                raise ValueError(f"Blob hash mismatch for {zip_path}")
            target = ensure_within_data_root(data_root() / blob_rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(payload)
                imported_blobs += 1

    dataset_meta = manifest.get("dataset") if isinstance(manifest.get("dataset"), dict) else {}
    metadata = DatasetMetadata.model_validate(dataset_meta.get("metadata") or {})
    spectra_raw = manifest.get("spectra")
    if not isinstance(spectra_raw, list) or not spectra_raw:
        raise ValueError("Dataset package contains no spectra")
    spectra = [
        SpectrumRef(
            spectrum_id=str(row["spectrum_id"]),
            relative_path=str(row["relative_path"]),
            record_index=row.get("record_index"),
            blob_id=row.get("blob_id"),
            blob_relative_path=row.get("blob_relative_path"),
            original_relative_path=row.get("original_relative_path") or row.get("relative_path"),
        )
        for row in spectra_raw
        if isinstance(row, dict)
    ]
    rec = create_dataset(metadata=metadata, spectra=spectra, owner_user_id=owner_user_id)

    imported_labels = 0
    labels = manifest.get("labels")
    if isinstance(labels, dict):
        con = with_connection()
        try:
            for rel, label_obj in labels.items():
                if isinstance(label_obj, dict):
                    upsert_upload_labels(con, relative_path=str(rel), labels=label_obj)
                    imported_labels += 1
        finally:
            con.close()

    return DatasetImportResponse(
        dataset=to_schema(rec),
        imported_spectra=len(rec.spectra),
        imported_blobs=imported_blobs,
        imported_labels=imported_labels,
    )
