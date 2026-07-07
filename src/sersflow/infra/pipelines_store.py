from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.infra.sqlite_db import connect
from sersflow.infra.user_access import has_global_access, resolve_owner_user_id


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PipelineLibraryRecord:
    pipeline_id: str
    name: str
    pipeline: Pipeline
    created_at: str
    updated_at: str


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS pipelines (
              pipeline_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              pipeline_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              owner_user_id TEXT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pipelines_updated_at ON pipelines(updated_at DESC);
            """
        )
        _migrate_pipelines_owner(con)
        con.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pipelines_owner_name
            ON pipelines(owner_user_id, name)
            """
        )


def _migrate_pipelines_owner(con: sqlite3.Connection) -> None:
    try:
        con.execute("ALTER TABLE pipelines ADD COLUMN owner_user_id TEXT NULL")
    except sqlite3.OperationalError:
        pass
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='pipelines'"
    ).fetchone()
    sql = str(row["sql"] if row else "")
    if "UNIQUE" in sql and "owner_user_id" not in sql:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS pipelines_new (
              pipeline_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              pipeline_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              owner_user_id TEXT NULL,
              UNIQUE(owner_user_id, name)
            );
            INSERT OR IGNORE INTO pipelines_new(
              pipeline_id, name, pipeline_json, created_at, updated_at, owner_user_id
            )
            SELECT pipeline_id, name, pipeline_json, created_at, updated_at, owner_user_id
            FROM pipelines;
            DROP TABLE pipelines;
            ALTER TABLE pipelines_new RENAME TO pipelines;
            CREATE INDEX IF NOT EXISTS idx_pipelines_updated_at ON pipelines(updated_at DESC);
            """
        )


def get_pipeline_by_name(name: str, *, owner_user_id: str) -> PipelineLibraryRecord | None:
    """Return the library entry whose name matches (exact, stripped) for this owner, or None."""
    ensure_schema()
    name_clean = name.strip()
    if not name_clean:
        return None
    with connect() as con:
        if has_global_access(owner_user_id):
            row = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                WHERE name = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (name_clean,),
            ).fetchone()
        else:
            effective = resolve_owner_user_id(owner_user_id)
            row = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                WHERE name = ? AND owner_user_id = ?
                """,
                (name_clean, effective),
            ).fetchone()
        if row is None:
            return None
        return PipelineLibraryRecord(
            pipeline_id=row["pipeline_id"],
            name=row["name"],
            pipeline=_load_pipeline_json(row["pipeline_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def create_pipeline(
    *,
    name: str,
    pipeline: Pipeline,
    owner_user_id: str,
    overwrite: bool = False,
) -> PipelineLibraryRecord:
    ensure_schema()
    name_clean = name.strip()
    if not name_clean:
        name_clean = f"Unnamed pipeline {uuid4().hex[:8]}"
    now = _utc_now_iso()
    pj = pipeline.model_dump_json()
    with connect() as con:
        if overwrite:
            row = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                WHERE name = ? AND owner_user_id = ?
                """,
                (name_clean, owner_user_id),
            ).fetchone()
            if row is not None:
                con.execute(
                    """
                    UPDATE pipelines
                    SET pipeline_json = ?, updated_at = ?
                    WHERE pipeline_id = ?
                    """,
                    (pj, now, row["pipeline_id"]),
                )
                return PipelineLibraryRecord(
                    pipeline_id=row["pipeline_id"],
                    name=name_clean,
                    pipeline=pipeline,
                    created_at=row["created_at"],
                    updated_at=now,
                )
        pipeline_id = f"pl_{uuid4().hex}"
        try:
            con.execute(
                """
                INSERT INTO pipelines(pipeline_id, name, pipeline_json, created_at, updated_at, owner_user_id)
                VALUES (?,?,?,?,?,?)
                """,
                (pipeline_id, name_clean, pj, now, now, owner_user_id),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e).upper() or "unique" in str(e):
                raise ValueError(f"Pipeline name already exists: {name_clean}") from e
            raise
    return PipelineLibraryRecord(
        pipeline_id=pipeline_id,
        name=name_clean,
        pipeline=pipeline,
        created_at=now,
        updated_at=now,
    )


def update_pipeline(
    *,
    pipeline_id: str,
    owner_user_id: str,
    name: str | None = None,
    pipeline: Pipeline | None = None,
) -> PipelineLibraryRecord | None:
    """
    Update an existing library entry's name and/or pipeline JSON.

    Raises:
        ValueError: If neither name nor pipeline is provided, or if the new name conflicts.
    """
    if name is None and pipeline is None:
        raise ValueError("At least one of name or pipeline is required")
    ensure_schema()
    existing = get_pipeline(pipeline_id, owner_user_id=owner_user_id)
    if existing is None:
        return None
    new_name = existing.name if name is None else name
    new_pipeline = existing.pipeline if pipeline is None else pipeline
    now = _utc_now_iso()
    pj = new_pipeline.model_dump_json()
    with connect() as con:
        try:
            if has_global_access(owner_user_id):
                con.execute(
                    """
                    UPDATE pipelines
                    SET name = ?, pipeline_json = ?, updated_at = ?
                    WHERE pipeline_id = ?
                    """,
                    (new_name, pj, now, pipeline_id),
                )
            else:
                effective = resolve_owner_user_id(owner_user_id)
                con.execute(
                    """
                    UPDATE pipelines
                    SET name = ?, pipeline_json = ?, updated_at = ?
                    WHERE pipeline_id = ? AND owner_user_id = ?
                    """,
                    (new_name, pj, now, pipeline_id, effective),
                )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e).upper() or "unique" in str(e):
                raise ValueError(f"Pipeline name already exists: {new_name}") from e
            raise
    updated = get_pipeline(pipeline_id, owner_user_id=owner_user_id)
    assert updated is not None
    return updated


def _load_pipeline_json(text: str) -> Pipeline:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    return Pipeline.model_validate(obj)


def get_pipeline(pipeline_id: str, *, owner_user_id: str) -> PipelineLibraryRecord | None:
    ensure_schema()
    with connect() as con:
        if has_global_access(owner_user_id):
            row = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                WHERE pipeline_id = ?
                """,
                (pipeline_id,),
            ).fetchone()
        else:
            effective = resolve_owner_user_id(owner_user_id)
            row = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                WHERE pipeline_id = ? AND owner_user_id = ?
                """,
                (pipeline_id, effective),
            ).fetchone()
        if row is None:
            return None
        return PipelineLibraryRecord(
            pipeline_id=row["pipeline_id"],
            name=row["name"],
            pipeline=_load_pipeline_json(row["pipeline_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def list_pipelines(
    *,
    owner_user_id: str,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
) -> list[PipelineLibraryRecord]:
    ensure_schema()
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))
    with connect() as con:
        if q and str(q).strip():
            like = f"%{str(q).strip()}%"
            if has_global_access(owner_user_id):
                rows = con.execute(
                    """
                    SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                    FROM pipelines
                    WHERE name LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (like, limit, offset),
                ).fetchall()
            else:
                effective = resolve_owner_user_id(owner_user_id)
                rows = con.execute(
                    """
                    SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                    FROM pipelines
                    WHERE owner_user_id = ? AND name LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (effective, like, limit, offset),
                ).fetchall()
        elif has_global_access(owner_user_id):
            rows = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        else:
            effective = resolve_owner_user_id(owner_user_id)
            rows = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                WHERE owner_user_id = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (effective, limit, offset),
            ).fetchall()
        return [
            PipelineLibraryRecord(
                pipeline_id=r["pipeline_id"],
                name=r["name"],
                pipeline=_load_pipeline_json(r["pipeline_json"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]


def delete_pipeline(pipeline_id: str, *, owner_user_id: str) -> bool:
    ensure_schema()
    with connect() as con:
        if has_global_access(owner_user_id):
            cur = con.execute("DELETE FROM pipelines WHERE pipeline_id = ?", (pipeline_id,))
        else:
            effective = resolve_owner_user_id(owner_user_id)
            cur = con.execute(
                "DELETE FROM pipelines WHERE pipeline_id = ? AND owner_user_id = ?",
                (pipeline_id, effective),
            )
        return int(cur.rowcount or 0) > 0
