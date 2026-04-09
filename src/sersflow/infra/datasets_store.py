from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from sersflow.api.schemas.datasets import Dataset, DatasetListItem, DatasetMetadata, SpectrumRef
from sersflow.infra.sqlite_db import connect


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    metadata: DatasetMetadata
    spectra: list[SpectrumRef]


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


def create_dataset(*, metadata: DatasetMetadata, spectra: Iterable[SpectrumRef]) -> DatasetRecord:
    ensure_schema()
    dataset_id = f"ds_{uuid4().hex}"
    created_at = _utc_now_iso()

    md = metadata.model_copy()
    if md.created_at is None:
        md.created_at = created_at

    spectra_list = list(spectra)
    with connect() as con:
        con.execute(
            "INSERT INTO datasets(dataset_id, metadata_json, created_at, updated_at) VALUES (?,?,?,?)",
            (dataset_id, md.model_dump_json(), created_at, created_at),
        )
        con.executemany(
            """
            INSERT INTO dataset_spectra(dataset_id, spectrum_id, relative_path, record_index, position)
            VALUES (?,?,?,?,?)
            """,
            [
                (
                    dataset_id,
                    s.spectrum_id,
                    s.relative_path,
                    s.record_index,
                    i,
                )
                for i, s in enumerate(spectra_list)
            ],
        )
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
            SELECT spectrum_id, relative_path, record_index
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

