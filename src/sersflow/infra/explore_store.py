from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sersflow.infra.sqlite_db import connect


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def artifacts_root() -> str:
    return os.environ.get("SERSFLOW_ARTIFACTS_DIR", os.path.join(os.getcwd(), ".sersflow_artifacts"))


def max_explore_runs_per_dataset() -> int:
    raw = os.environ.get("SERSFLOW_EXPLORE_MAX_RUNS_PER_DATASET", "100")
    try:
        n = int(raw)
    except ValueError:
        n = 100
    return max(1, min(n, 10_000))


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS matrix_jobs (
              matrix_job_id TEXT PRIMARY KEY,
              dataset_id TEXT NOT NULL,
              session_id TEXT NULL,
              pipeline_hash TEXT NOT NULL,
              pipeline_json TEXT NULL,
              subset_hash TEXT NOT NULL,
              up_to_step TEXT NULL,
              status TEXT NOT NULL,
              npz_path TEXT NULL,
              manifest_json TEXT NULL,
              created_at TEXT NOT NULL,
              finished_at TEXT NULL,
              error TEXT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_matrix_jobs_dataset ON matrix_jobs(dataset_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS explore_runs (
              explore_id TEXT PRIMARY KEY,
              dataset_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              source_analysis_run_id TEXT NULL,
              matrix_job_id TEXT NULL,
              artifact_subdir TEXT NOT NULL,
              input_ref_json TEXT NULL,
              created_at TEXT NOT NULL,
              finished_at TEXT NULL,
              error TEXT NULL,
              pinned INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_explore_runs_dataset ON explore_runs(dataset_id, created_at DESC);
            """
        )
        # Backwards-compatible migration for existing DBs.
        try:
            con.execute("ALTER TABLE matrix_jobs ADD COLUMN pipeline_json TEXT NULL")
        except Exception:
            pass


@dataclass(frozen=True)
class MatrixJobRecord:
    matrix_job_id: str
    dataset_id: str
    session_id: str | None
    pipeline_hash: str
    pipeline_json: str | None
    subset_hash: str
    up_to_step: str | None
    status: str
    npz_path: str | None
    manifest_json: str | None
    created_at: str
    finished_at: str | None
    error: str | None


@dataclass(frozen=True)
class ExploreRunRecord:
    explore_id: str
    dataset_id: str
    kind: str
    status: str
    source_analysis_run_id: str | None
    matrix_job_id: str | None
    artifact_subdir: str
    input_ref_json: str | None
    created_at: str
    finished_at: str | None
    error: str | None
    pinned: bool


def create_matrix_job_pending(
    *,
    dataset_id: str,
    session_id: str | None,
    pipeline_hash: str,
    pipeline_json: str | None,
    subset_hash: str,
    up_to_step: str | None,
) -> str:
    ensure_schema()
    jid = f"mjob_{uuid4().hex}"
    now = _utc_now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT INTO matrix_jobs(
              matrix_job_id, dataset_id, session_id, pipeline_hash, pipeline_json, subset_hash, up_to_step,
              status, npz_path, manifest_json, created_at, finished_at, error
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                jid,
                dataset_id,
                session_id,
                pipeline_hash,
                pipeline_json,
                subset_hash,
                up_to_step,
                "pending",
                None,
                None,
                now,
                None,
                None,
            ),
        )
    return jid


def update_matrix_job(
    *,
    matrix_job_id: str,
    status: str,
    npz_path: str | None = None,
    manifest_json: str | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    ensure_schema()
    now = _utc_now_iso()
    with connect() as con:
        if finished:
            con.execute(
                """
                UPDATE matrix_jobs
                SET status = ?, npz_path = COALESCE(?, npz_path), manifest_json = COALESCE(?, manifest_json),
                    error = ?, finished_at = ?
                WHERE matrix_job_id = ?
                """,
                (status, npz_path, manifest_json, error, now, matrix_job_id),
            )
        else:
            con.execute(
                "UPDATE matrix_jobs SET status = ?, error = ? WHERE matrix_job_id = ?",
                (status, error, matrix_job_id),
            )


def get_matrix_job(matrix_job_id: str) -> MatrixJobRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute("SELECT * FROM matrix_jobs WHERE matrix_job_id = ?", (matrix_job_id,)).fetchone()
        if row is None:
            return None
        return MatrixJobRecord(
            matrix_job_id=row["matrix_job_id"],
            dataset_id=row["dataset_id"],
            session_id=row["session_id"],
            pipeline_hash=row["pipeline_hash"],
            pipeline_json=row["pipeline_json"],
            subset_hash=row["subset_hash"],
            up_to_step=row["up_to_step"],
            status=row["status"],
            npz_path=row["npz_path"],
            manifest_json=row["manifest_json"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            error=row["error"],
        )


def create_explore_run(
    *,
    dataset_id: str,
    kind: str,
    source_analysis_run_id: str | None,
    matrix_job_id: str | None,
    artifact_subdir: str,
    input_ref: dict[str, Any] | None,
) -> str:
    ensure_schema()
    eid = f"exp_{uuid4().hex}"
    now = _utc_now_iso()
    ref = json.dumps(input_ref, separators=(",", ":"), ensure_ascii=False) if input_ref else None
    with connect() as con:
        con.execute(
            """
            INSERT INTO explore_runs(
              explore_id, dataset_id, kind, status, source_analysis_run_id, matrix_job_id,
              artifact_subdir, input_ref_json, created_at, finished_at, error, pinned
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                eid,
                dataset_id,
                kind,
                "running",
                source_analysis_run_id,
                matrix_job_id,
                artifact_subdir,
                ref,
                now,
                None,
                None,
                0,
            ),
        )
    return eid


def get_explore_run(explore_id: str) -> ExploreRunRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute("SELECT * FROM explore_runs WHERE explore_id = ?", (explore_id,)).fetchone()
        if row is None:
            return None
        return ExploreRunRecord(
            explore_id=row["explore_id"],
            dataset_id=row["dataset_id"],
            kind=row["kind"],
            status=row["status"],
            source_analysis_run_id=row["source_analysis_run_id"],
            matrix_job_id=row["matrix_job_id"],
            artifact_subdir=row["artifact_subdir"],
            input_ref_json=row["input_ref_json"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            error=row["error"],
            pinned=bool(row["pinned"]),
        )


def finish_explore_run(
    *,
    explore_id: str,
    status: str,
    error: str | None = None,
) -> None:
    ensure_schema()
    now = _utc_now_iso()
    with connect() as con:
        con.execute(
            "UPDATE explore_runs SET status = ?, finished_at = ?, error = ? WHERE explore_id = ?",
            (status, now, error, explore_id),
        )


def prune_explore_runs(*, dataset_id: str, max_keep: int | None = None) -> int:
    cap = max_keep if max_keep is not None else max_explore_runs_per_dataset()
    ensure_schema()
    with connect() as con:
        rows = con.execute(
            """
            SELECT explore_id FROM explore_runs
            WHERE dataset_id = ? AND pinned = 0
            ORDER BY created_at DESC
            """,
            (dataset_id,),
        ).fetchall()
        ids = [r["explore_id"] for r in rows]
        if len(ids) <= cap:
            return 0
        to_del = ids[cap:]
        con.executemany("DELETE FROM explore_runs WHERE explore_id = ?", [(i,) for i in to_del])
    return len(to_del)
