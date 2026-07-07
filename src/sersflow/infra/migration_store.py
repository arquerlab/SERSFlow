from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sersflow.core.io.upload_registry import (
    read_unloaded_registry,
    read_upload_registry,
    unloaded_registry_path,
    upload_root,
    write_unloaded_registry,
    write_upload_registry,
)
from sersflow.infra.datasets_store import ensure_schema as ensure_datasets_schema
from sersflow.infra.pipelines_store import ensure_schema as ensure_pipelines_schema
from sersflow.infra.sqlite_db import connect


@dataclass(frozen=True)
class AssignOrphansReport:
    datasets_updated: int
    pipelines_updated: int
    registry_rows_updated: int
    unloaded_rows_updated: int
    path_only_datasets: list[str]


def _path_only_dataset_rows() -> list[str]:
    ensure_datasets_schema()
    root = upload_root()
    active = {str(item.get("relative_path") or "") for item in read_upload_registry(root)}
    unloaded = {str(item.get("relative_path") or "") for item in read_unloaded_registry(root)}
    known = active | unloaded
    out: list[str] = []
    with connect() as con:
        rows = con.execute(
            """
            SELECT DISTINCT d.dataset_id, ds.relative_path
            FROM datasets d
            JOIN dataset_spectra ds ON ds.dataset_id = d.dataset_id
            WHERE d.owner_user_id IS NULL OR d.owner_user_id = ''
            """
        ).fetchall()
        seen: set[str] = set()
        for row in rows:
            rel = str(row["relative_path"] or "")
            ds_id = str(row["dataset_id"] or "")
            if ds_id in seen:
                continue
            if rel and rel not in known:
                seen.add(ds_id)
                out.append(ds_id)
    return sorted(out)


def _rewrite_registry_with_owner(root: Path, *, owner_user_id: str, dry_run: bool) -> tuple[int, int]:
    active = read_upload_registry(root)
    unloaded = read_unloaded_registry(root)
    active_changed = 0
    unloaded_changed = 0
    new_active: list[dict[str, Any]] = []
    for item in active:
        rec = dict(item)
        if not rec.get("owner_user_id"):
            rec["owner_user_id"] = owner_user_id
            active_changed += 1
        new_active.append(rec)
    new_unloaded: list[dict[str, Any]] = []
    for item in unloaded:
        rec = dict(item)
        if not rec.get("owner_user_id"):
            rec["owner_user_id"] = owner_user_id
            unloaded_changed += 1
        new_unloaded.append(rec)
    if not dry_run and (active_changed or unloaded_changed):
        if active_changed:
            write_upload_registry(root, new_active)
        if unloaded_changed:
            write_unloaded_registry(root, new_unloaded)
    return active_changed, unloaded_changed


def assign_orphans(*, owner_user_id: str, dry_run: bool = False) -> AssignOrphansReport:
    owner = owner_user_id.strip()
    if not owner:
        raise ValueError("owner_user_id is required")

    ensure_datasets_schema()
    ensure_pipelines_schema()
    path_only = _path_only_dataset_rows()

    datasets_updated = 0
    pipelines_updated = 0
    with connect() as con:
        if dry_run:
            row = con.execute(
                "SELECT COUNT(*) AS n FROM datasets WHERE owner_user_id IS NULL OR owner_user_id = ''"
            ).fetchone()
            datasets_updated = int(row["n"] if row else 0)
            row = con.execute(
                "SELECT COUNT(*) AS n FROM pipelines WHERE owner_user_id IS NULL OR owner_user_id = ''"
            ).fetchone()
            pipelines_updated = int(row["n"] if row else 0)
        else:
            cur = con.execute(
                """
                UPDATE datasets
                SET owner_user_id = ?
                WHERE owner_user_id IS NULL OR owner_user_id = ''
                """,
                (owner,),
            )
            datasets_updated = int(cur.rowcount or 0)
            cur = con.execute(
                """
                UPDATE pipelines
                SET owner_user_id = ?
                WHERE owner_user_id IS NULL OR owner_user_id = ''
                """,
                (owner,),
            )
            pipelines_updated = int(cur.rowcount or 0)

    root = upload_root()
    active_changed, unloaded_changed = _rewrite_registry_with_owner(root, owner_user_id=owner, dry_run=dry_run)

    if not dry_run:
        from sersflow.api.services.ownership import invalidate_registry_cache

        invalidate_registry_cache()

    return AssignOrphansReport(
        datasets_updated=datasets_updated,
        pipelines_updated=pipelines_updated,
        registry_rows_updated=active_changed,
        unloaded_rows_updated=unloaded_changed,
        path_only_datasets=path_only,
    )
