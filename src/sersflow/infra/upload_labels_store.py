from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from sersflow.infra.sqlite_db import connect


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_upload_labels_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_labels (
            relative_path TEXT PRIMARY KEY,
            labels_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    con.commit()


def upsert_upload_labels(con: sqlite3.Connection, *, relative_path: str, labels: dict[str, Any]) -> None:
    ensure_upload_labels_schema(con)
    now = _utc_now_iso()
    payload = json.dumps(labels, ensure_ascii=False)
    con.execute(
        """
        INSERT INTO upload_labels (relative_path, labels_json, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(relative_path) DO UPDATE SET
            labels_json = excluded.labels_json,
            updated_at = excluded.updated_at;
        """,
        (relative_path, payload, now, now),
    )
    con.commit()


def fetch_upload_labels_for_paths(
    con: sqlite3.Connection, relative_paths: Iterable[str]
) -> dict[str, dict[str, Any]]:
    ensure_upload_labels_schema(con)
    paths = list(dict.fromkeys(p for p in relative_paths if p))
    if not paths:
        return {}
    placeholders = ",".join("?" * len(paths))
    rows = con.execute(
        f"SELECT relative_path, labels_json FROM upload_labels WHERE relative_path IN ({placeholders})",
        paths,
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rel = str(row["relative_path"])
        try:
            out[rel] = json.loads(row["labels_json"])
        except json.JSONDecodeError:
            out[rel] = {}
    return out


def delete_upload_labels_for_paths(con: sqlite3.Connection, relative_paths: Iterable[str]) -> None:
    ensure_upload_labels_schema(con)
    paths = [p for p in relative_paths if p]
    if not paths:
        return
    placeholders = ",".join("?" * len(paths))
    con.execute(f"DELETE FROM upload_labels WHERE relative_path IN ({placeholders})", paths)
    con.commit()


def with_connection() -> sqlite3.Connection:
    con = connect()
    ensure_upload_labels_schema(con)
    return con
