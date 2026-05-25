from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from sersflow.infra.sqlite_db import connect


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def max_runs_per_dataset() -> int:
    raw = os.environ.get("SERSFLOW_ANALYSIS_MAX_RUNS_PER_DATASET", "50")
    try:
        n = int(raw)
    except ValueError:
        n = 50
    return max(1, min(n, 10_000))


@dataclass(frozen=True)
class AnalysisRunRecord:
    run_id: str
    dataset_id: str
    session_id: str | None
    pipeline_id: str | None
    pipeline_name: str | None
    pipeline_hash: str
    subset_hash: str
    pipeline_json: str | None
    status: str
    error: str | None
    created_at: str
    finished_at: str | None
    kind: str
    label: str | None
    pinned: bool
    params_json: str | None
    feature_columns_json: str | None
    client_job_key: str | None


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
              run_id TEXT PRIMARY KEY,
              dataset_id TEXT NOT NULL,
              session_id TEXT NULL,
              pipeline_id TEXT NULL,
              pipeline_name TEXT NULL,
              pipeline_hash TEXT NOT NULL,
              subset_hash TEXT NOT NULL,
              pipeline_json TEXT NULL,
              status TEXT NOT NULL,
              error TEXT NULL,
              created_at TEXT NOT NULL,
              finished_at TEXT NULL,
              kind TEXT NOT NULL DEFAULT 'batch_features',
              label TEXT NULL,
              pinned INTEGER NOT NULL DEFAULT 0,
              params_json TEXT NULL,
              feature_columns_json TEXT NULL,
              client_job_key TEXT NULL UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_dataset_created
              ON analysis_runs(dataset_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_dataset_pinned_created
              ON analysis_runs(dataset_id, pinned, created_at DESC);

            CREATE TABLE IF NOT EXISTS analysis_spectrum_rows (
              run_id TEXT NOT NULL,
              spectrum_id TEXT NOT NULL,
              features_json TEXT NOT NULL,
              PRIMARY KEY (run_id, spectrum_id),
              FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_analysis_spectrum_rows_run ON analysis_spectrum_rows(run_id);

            CREATE TABLE IF NOT EXISTS analysis_jobs (
              job_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL,
              progress_done INTEGER NOT NULL DEFAULT 0,
              progress_total INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              error TEXT NULL,
              FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
            );
            """
        )
        # Backwards-compatible migrations for existing DBs.
        try:
            con.execute("ALTER TABLE analysis_runs ADD COLUMN pipeline_id TEXT NULL")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE analysis_runs ADD COLUMN pipeline_name TEXT NULL")
        except Exception:
            pass


def create_run_pending(
    *,
    dataset_id: str,
    session_id: str | None,
    pipeline_id: str | None = None,
    pipeline_name: str | None = None,
    pipeline_hash: str,
    subset_hash: str,
    pipeline_json: str | None,
    label: str | None,
    pinned: bool,
    client_job_key: str | None,
    params: dict[str, Any] | None,
) -> str:
    ensure_schema()
    run_id = f"arun_{uuid4().hex}"
    now = _utc_now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT INTO analysis_runs(
              run_id, dataset_id, session_id, pipeline_id, pipeline_name, pipeline_hash, subset_hash, pipeline_json,
              status, error, created_at, finished_at, kind, label, pinned, params_json,
              feature_columns_json, client_job_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                dataset_id,
                session_id,
                pipeline_id,
                pipeline_name,
                pipeline_hash,
                subset_hash,
                pipeline_json,
                "pending",
                None,
                now,
                None,
                "batch_features",
                label,
                1 if pinned else 0,
                _compact_json(params) if params else None,
                None,
                client_job_key,
            ),
        )
    return run_id


def create_job(*, run_id: str) -> str:
    ensure_schema()
    job_id = f"ajob_{uuid4().hex}"
    now = _utc_now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT INTO analysis_jobs(job_id, run_id, status, progress_done, progress_total, created_at, updated_at, error)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (job_id, run_id, "queued", 0, 0, now, now, None),
        )
    return job_id


def get_run(run_id: str) -> AnalysisRunRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute("SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return _row_to_run(row)


def _row_to_run(row: Any) -> AnalysisRunRecord:
    return AnalysisRunRecord(
        run_id=row["run_id"],
        dataset_id=row["dataset_id"],
        session_id=row["session_id"],
        pipeline_id=row["pipeline_id"] if "pipeline_id" in row.keys() else None,
        pipeline_name=row["pipeline_name"] if "pipeline_name" in row.keys() else None,
        pipeline_hash=row["pipeline_hash"],
        subset_hash=row["subset_hash"],
        pipeline_json=row["pipeline_json"],
        status=row["status"],
        error=row["error"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        kind=row["kind"],
        label=row["label"],
        pinned=bool(row["pinned"]),
        params_json=row["params_json"],
        feature_columns_json=row["feature_columns_json"],
        client_job_key=row["client_job_key"],
    )


def delete_run(*, run_id: str) -> bool:
    ensure_schema()
    with connect() as con:
        cur = con.execute("DELETE FROM analysis_runs WHERE run_id = ?", (run_id,))
        return int(cur.rowcount or 0) > 0


def delete_runs_for_dataset(*, dataset_id: str) -> int:
    ensure_schema()
    with connect() as con:
        cur = con.execute("DELETE FROM analysis_runs WHERE dataset_id = ?", (dataset_id,))
        return int(cur.rowcount or 0)


def find_run_by_client_job_key(client_job_key: str) -> AnalysisRunRecord | None:
    ensure_schema()
    with connect() as con:
        row = con.execute(
            "SELECT * FROM analysis_runs WHERE client_job_key = ?",
            (client_job_key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_run(row)


def list_runs(*, dataset_id: str, limit: int = 50) -> list[AnalysisRunRecord]:
    ensure_schema()
    lim = max(1, min(int(limit), 500))
    with connect() as con:
        rows = con.execute(
            """
            SELECT * FROM analysis_runs
            WHERE dataset_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (dataset_id, lim),
        ).fetchall()
    return [_row_to_run(r) for r in rows]


def update_run_status(
    *,
    run_id: str,
    status: str,
    error: str | None = None,
    feature_columns: list[str] | None = None,
    finished: bool = False,
) -> None:
    ensure_schema()
    now = _utc_now_iso()
    fc = _compact_json(feature_columns) if feature_columns is not None else None
    with connect() as con:
        if finished:
            con.execute(
                """
                UPDATE analysis_runs
                SET status = ?, error = ?, feature_columns_json = COALESCE(?, feature_columns_json), finished_at = ?
                WHERE run_id = ?
                """,
                (status, error, fc, now, run_id),
            )
        else:
            con.execute(
                """
                UPDATE analysis_runs
                SET status = ?, error = ?
                WHERE run_id = ?
                """,
                (status, error, run_id),
            )


def get_job_for_run(run_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with connect() as con:
        row = con.execute("SELECT * FROM analysis_jobs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return dict(row)


def get_job_by_id(job_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with connect() as con:
        row = con.execute("SELECT * FROM analysis_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return dict(row)


def update_job_progress(
    *,
    job_id: str,
    status: str | None,
    progress_done: int,
    progress_total: int,
    error: str | None = None,
) -> None:
    ensure_schema()
    now = _utc_now_iso()
    with connect() as con:
        if status is not None:
            con.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, progress_done = ?, progress_total = ?, updated_at = ?, error = COALESCE(?, error)
                WHERE job_id = ?
                """,
                (status, progress_done, progress_total, now, error, job_id),
            )
        else:
            con.execute(
                """
                UPDATE analysis_jobs
                SET progress_done = ?, progress_total = ?, updated_at = ?, error = COALESCE(?, error)
                WHERE job_id = ?
                """,
                (progress_done, progress_total, now, error, job_id),
            )


def insert_spectrum_rows_batch(*, run_id: str, rows: Iterable[tuple[str, dict[str, Any]]]) -> None:
    ensure_schema()
    data = [(run_id, sid, _compact_json(feat)) for sid, feat in rows]
    if not data:
        return
    with connect() as con:
        con.executemany(
            """
            INSERT INTO analysis_spectrum_rows(run_id, spectrum_id, features_json)
            VALUES (?,?,?)
            """,
            data,
        )


def iter_spectrum_rows(*, run_id: str, chunk_size: int = 500) -> Iterable[tuple[str, dict[str, Any]]]:
    ensure_schema()
    offset = 0
    cs = max(1, min(chunk_size, 5000))
    while True:
        with connect() as con:
            batch = con.execute(
                """
                SELECT spectrum_id, features_json FROM analysis_spectrum_rows
                WHERE run_id = ?
                ORDER BY spectrum_id
                LIMIT ? OFFSET ?
                """,
                (run_id, cs, offset),
            ).fetchall()
        if not batch:
            break
        for r in batch:
            sid = r["spectrum_id"]
            feat = json.loads(r["features_json"])
            yield sid, feat
        offset += cs
        if len(batch) < cs:
            break


def count_spectrum_rows(run_id: str) -> int:
    ensure_schema()
    with connect() as con:
        row = con.execute(
            "SELECT COUNT(*) AS c FROM analysis_spectrum_rows WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def prune_unpinned_runs(*, dataset_id: str, max_keep: int | None = None) -> int:
    """
    Keep at most max_keep unpinned runs for dataset_id (newest first). Returns number deleted.
    """
    ensure_schema()
    cap = max_keep if max_keep is not None else max_runs_per_dataset()
    with connect() as con:
        rows = con.execute(
            """
            SELECT run_id FROM analysis_runs
            WHERE dataset_id = ? AND pinned = 0
            ORDER BY created_at DESC, rowid DESC
            """,
            (dataset_id,),
        ).fetchall()
        ids = [r["run_id"] for r in rows]
        if len(ids) <= cap:
            return 0
        to_del = ids[cap:]
        con.executemany("DELETE FROM analysis_runs WHERE run_id = ?", [(i,) for i in to_del])
    return len(to_del)
