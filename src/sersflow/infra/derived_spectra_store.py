"""Catalog of derived spectra (group averages) so their ids resolve outside the run that made them."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sersflow.infra.sqlite_db import connect


@dataclass(frozen=True)
class DerivedSpectrumRecord:
    spectrum_id: str
    dataset_id: str
    kind: str
    blob_id: str
    blob_relative_path: str
    labels: dict[str, Any]
    member_spectrum_ids: list[str]
    group_key: dict[str, Any]
    rule: dict[str, Any]


def derived_relative_path(spectrum_id: str) -> str:
    """Path-level label key for a derived spectrum (not a file on disk; data lives in the blob)."""
    return f"derived/{spectrum_id}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS derived_spectra (
          spectrum_id TEXT NOT NULL,
          dataset_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          blob_id TEXT NOT NULL,
          blob_relative_path TEXT NOT NULL,
          labels_json TEXT NOT NULL,
          members_json TEXT NOT NULL,
          group_key_json TEXT NOT NULL,
          rule_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (dataset_id, spectrum_id)
        );
        CREATE INDEX IF NOT EXISTS idx_derived_spectra_id ON derived_spectra(spectrum_id);
        """
    )
    con.commit()


def upsert_derived_spectrum(rec: DerivedSpectrumRecord) -> None:
    """Insert or refresh a derived spectrum. The id is stable, so reruns update blob + labels in place."""
    con = connect()
    try:
        ensure_schema(con)
        now = _utc_now_iso()
        con.execute(
            """
            INSERT INTO derived_spectra (
              spectrum_id, dataset_id, kind, blob_id, blob_relative_path,
              labels_json, members_json, group_key_json, rule_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id, spectrum_id) DO UPDATE SET
              kind = excluded.kind,
              blob_id = excluded.blob_id,
              blob_relative_path = excluded.blob_relative_path,
              labels_json = excluded.labels_json,
              members_json = excluded.members_json,
              group_key_json = excluded.group_key_json,
              rule_json = excluded.rule_json,
              updated_at = excluded.updated_at
            """,
            (
                rec.spectrum_id,
                rec.dataset_id,
                rec.kind,
                rec.blob_id,
                rec.blob_relative_path,
                json.dumps(rec.labels, ensure_ascii=False, default=str),
                json.dumps(rec.member_spectrum_ids),
                json.dumps(rec.group_key, ensure_ascii=False, default=str),
                json.dumps(rec.rule, ensure_ascii=False, default=str),
                now,
                now,
            ),
        )
        con.commit()
    finally:
        con.close()


def _row_to_record(row: sqlite3.Row) -> DerivedSpectrumRecord:
    return DerivedSpectrumRecord(
        spectrum_id=str(row["spectrum_id"]),
        dataset_id=str(row["dataset_id"]),
        kind=str(row["kind"]),
        blob_id=str(row["blob_id"]),
        blob_relative_path=str(row["blob_relative_path"]),
        labels=json.loads(row["labels_json"]),
        member_spectrum_ids=list(json.loads(row["members_json"])),
        group_key=json.loads(row["group_key_json"]),
        rule=json.loads(row["rule_json"]),
    )


def get_derived_spectra(
    *, dataset_id: str, spectrum_ids: Iterable[str]
) -> dict[str, DerivedSpectrumRecord]:
    ids = list(dict.fromkeys(str(s) for s in spectrum_ids if s))
    if not ids:
        return {}
    con = connect()
    try:
        ensure_schema(con)
        out: dict[str, DerivedSpectrumRecord] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            ph = ",".join("?" * len(chunk))
            rows = con.execute(
                f"SELECT * FROM derived_spectra WHERE dataset_id = ? AND spectrum_id IN ({ph})",
                [dataset_id, *chunk],
            ).fetchall()
            for r in rows:
                rec = _row_to_record(r)
                out[rec.spectrum_id] = rec
        return out
    finally:
        con.close()


def list_derived_spectra(*, dataset_id: str) -> list[DerivedSpectrumRecord]:
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            "SELECT * FROM derived_spectra WHERE dataset_id = ? ORDER BY created_at, spectrum_id",
            (dataset_id,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]
    finally:
        con.close()
