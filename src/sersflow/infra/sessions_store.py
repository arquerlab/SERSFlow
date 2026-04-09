from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import Session, SessionCacheInfo, SubsetStrategy
from sersflow.infra.sqlite_db import connect


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    dataset_id: str
    pipeline: Pipeline
    subset: SubsetStrategy
    cache: SessionCacheInfo | None
    created_at: str
    updated_at: str


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              dataset_id TEXT NOT NULL,
              pipeline_json TEXT NOT NULL,
              subset_json TEXT NOT NULL,
              cache_json TEXT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_dataset_id ON sessions(dataset_id);
            """
        )


def create_session(*, dataset_id: str, pipeline: Pipeline, subset: SubsetStrategy) -> SessionRecord:
    ensure_schema()
    now = _utc_now_iso()
    session_id = f"sess_{uuid4().hex}"
    cache = SessionCacheInfo(cache_namespace=session_id)
    with connect() as con:
        con.execute(
            """
            INSERT INTO sessions(session_id, dataset_id, pipeline_json, subset_json, cache_json, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                session_id,
                dataset_id,
                pipeline.model_dump_json(),
                subset.model_dump_json(),
                cache.model_dump_json(),
                now,
                now,
            ),
        )
    return SessionRecord(
        session_id=session_id,
        dataset_id=dataset_id,
        pipeline=pipeline,
        subset=subset,
        cache=cache,
        created_at=now,
        updated_at=now,
    )


def _load_json(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def get_session(session_id: str) -> SessionRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        pipeline = Pipeline.model_validate(_load_json(row["pipeline_json"]))
        subset = SubsetStrategy.model_validate(_load_json(row["subset_json"]))
        cache = None
        if row["cache_json"]:
            cache = SessionCacheInfo.model_validate(_load_json(row["cache_json"]))
        return SessionRecord(
            session_id=row["session_id"],
            dataset_id=row["dataset_id"],
            pipeline=pipeline,
            subset=subset,
            cache=cache,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def update_session_pipeline(session_id: str, pipeline: Pipeline) -> SessionRecord | None:
    ensure_schema()
    now = _utc_now_iso()
    with connect() as con:
        con.execute(
            "UPDATE sessions SET pipeline_json = ?, updated_at = ? WHERE session_id = ?",
            (pipeline.model_dump_json(), now, session_id),
        )
    rec = get_session(session_id)
    return rec


def update_session_subset(session_id: str, subset: SubsetStrategy) -> SessionRecord | None:
    ensure_schema()
    now = _utc_now_iso()
    with connect() as con:
        con.execute(
            "UPDATE sessions SET subset_json = ?, updated_at = ? WHERE session_id = ?",
            (subset.model_dump_json(), now, session_id),
        )
    rec = get_session(session_id)
    return rec


def to_schema(rec: SessionRecord) -> Session:
    return Session(
        session_id=rec.session_id,
        dataset_id=rec.dataset_id,
        pipeline=rec.pipeline,
        subset=rec.subset,
        cache=rec.cache,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )

