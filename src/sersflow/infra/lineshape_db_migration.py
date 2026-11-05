"""One-time DB migration for K1 (``gl`` sum -> ``sgl``; ``gl`` now means the CasaXPS product)."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from sersflow.core.pipeline.lineshape_migration import migrate_legacy_gl
from sersflow.infra.sqlite_db import connect

logger = logging.getLogger(__name__)

MIGRATION_NAME = "k1_gl_sum_to_sgl"

# (table, primary key column, JSON column) holding pipelines or pipeline snapshots.
_PIPELINE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("pipelines", "pipeline_id", "pipeline_json"),
    ("sessions", "session_id", "pipeline_json"),
    ("analysis_runs", "run_id", "pipeline_json"),
    ("matrix_jobs", "matrix_job_id", "pipeline_json"),
)


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def migrate_gl_to_sgl(*, force: bool = False) -> dict[str, Any]:
    """
    Rewrite stored pipelines once (guarded by a ``schema_migrations`` marker).

    Returns ``{"applied": bool, "rows_changed": {table: n}, "components_renamed": n}``.
    Stored pipeline hashes on analysis runs are NOT recomputed: they keep describing the run as it
    was made. Re-running a migrated pipeline gives the same numbers under a new pipeline hash.
    """
    with connect() as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        done = con.execute("SELECT 1 FROM schema_migrations WHERE name = ?", (MIGRATION_NAME,)).fetchone()
        if done and not force:
            return {"applied": False, "rows_changed": {}, "components_renamed": 0}

        rows_changed: dict[str, int] = {}
        renamed = 0
        for table, pk, col in _PIPELINE_COLUMNS:
            if not _table_exists(con, table):
                continue
            n_rows = 0
            for row in con.execute(f"SELECT {pk}, {col} FROM {table}").fetchall():
                raw = row[1]
                if not raw or '"gl"' not in raw and '"a_gl"' not in raw:
                    continue
                try:
                    data = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                n = migrate_legacy_gl(data)
                if n:
                    con.execute(
                        f"UPDATE {table} SET {col} = ? WHERE {pk} = ?",
                        (json.dumps(data, ensure_ascii=False, separators=(",", ":")), row[0]),
                    )
                    n_rows += 1
                    renamed += n
            if n_rows:
                rows_changed[table] = n_rows
        con.execute(
            "INSERT OR REPLACE INTO schema_migrations(name, applied_at) VALUES (?, datetime('now'))",
            (MIGRATION_NAME,),
        )
    if renamed:
        logger.warning(
            "K1 migration: renamed %d legacy gl/a_gl component(s) to sgl/a_sgl in %s",
            renamed,
            rows_changed,
        )
    return {"applied": True, "rows_changed": rows_changed, "components_renamed": renamed}
