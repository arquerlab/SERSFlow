from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.infra.sqlite_db import connect


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
              name TEXT NOT NULL UNIQUE,
              pipeline_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pipelines_updated_at ON pipelines(updated_at DESC);
            """
        )


def create_pipeline(*, name: str, pipeline: Pipeline) -> PipelineLibraryRecord:
    ensure_schema()
    pipeline_id = f"pl_{uuid4().hex}"
    now = _utc_now_iso()
    pj = pipeline.model_dump_json()
    with connect() as con:
        try:
            con.execute(
                """
                INSERT INTO pipelines(pipeline_id, name, pipeline_json, created_at, updated_at)
                VALUES (?,?,?,?,?)
                """,
                (pipeline_id, name.strip(), pj, now, now),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e).upper() or "unique" in str(e):
                raise ValueError(f"Pipeline name already exists: {name.strip()}") from e
            raise
    return PipelineLibraryRecord(
        pipeline_id=pipeline_id,
        name=name.strip(),
        pipeline=pipeline,
        created_at=now,
        updated_at=now,
    )


def _load_pipeline_json(text: str) -> Pipeline:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    return Pipeline.model_validate(obj)


def get_pipeline(pipeline_id: str) -> PipelineLibraryRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute(
            "SELECT pipeline_id, name, pipeline_json, created_at, updated_at FROM pipelines WHERE pipeline_id = ?",
            (pipeline_id,),
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


def list_pipelines(*, limit: int = 50, offset: int = 0, q: str | None = None) -> list[PipelineLibraryRecord]:
    ensure_schema()
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))
    with connect() as con:
        if q and str(q).strip():
            like = f"%{str(q).strip()}%"
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
            rows = con.execute(
                """
                SELECT pipeline_id, name, pipeline_json, created_at, updated_at
                FROM pipelines
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
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


def delete_pipeline(pipeline_id: str) -> bool:
    ensure_schema()
    with connect() as con:
        cur = con.execute("DELETE FROM pipelines WHERE pipeline_id = ?", (pipeline_id,))
        return int(cur.rowcount or 0) > 0
