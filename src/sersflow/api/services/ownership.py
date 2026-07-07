from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from sersflow.infra.user_access import has_global_access, resolve_owner_user_id

from sersflow.api.schemas.datasets import SpectrumRef
from sersflow.core.io.upload_registry import (
    read_unloaded_registry,
    read_upload_registry,
    unloaded_registry_path,
    upload_root,
)
from sersflow.infra.analysis_store import get_run
from sersflow.infra.datasets_store import DatasetRecord, get_dataset, get_dataset_internal
from sersflow.infra.explore_store import get_explore_run, get_matrix_job
from sersflow.infra.sessions_store import SessionRecord, get_session

_registry_cache_mtime: tuple[float, float] | None = None
_registry_owner_index: dict[str, str] = {}


class OwnershipError(Exception):
    """Raised when a user does not own a resource."""


def invalidate_registry_cache() -> None:
    global _registry_cache_mtime, _registry_owner_index
    _registry_cache_mtime = None
    _registry_owner_index = {}


def _registry_files_mtime(root: Path) -> tuple[float, float]:
    active = root / "upload_registry.jsonl"
    unloaded = root / "unloaded_registry.jsonl"
    return (
        active.stat().st_mtime if active.exists() else 0.0,
        unloaded.stat().st_mtime if unloaded.exists() else 0.0,
    )


def _rebuild_registry_cache() -> dict[str, str]:
    root = upload_root()
    index: dict[str, str] = {}
    for item in read_upload_registry(root) + read_unloaded_registry(root):
        rel = str(item.get("relative_path") or "")
        owner = item.get("owner_user_id")
        if rel and owner:
            index[rel] = str(owner)
    return index


def registry_owner_for_path(relative_path: str) -> str | None:
    global _registry_cache_mtime, _registry_owner_index
    root = upload_root()
    mtime = _registry_files_mtime(root)
    if _registry_cache_mtime != mtime:
        _registry_owner_index = _rebuild_registry_cache()
        _registry_cache_mtime = mtime
    return _registry_owner_index.get(relative_path)


def assert_path_owner(user_id: str, relative_path: str) -> None:
    if has_global_access(user_id):
        return
    effective = resolve_owner_user_id(user_id)
    owner = registry_owner_for_path(relative_path)
    if owner is None:
        raise OwnershipError(relative_path)
    if owner != effective:
        raise OwnershipError(relative_path)


def assert_paths_owner(user_id: str, relative_paths: list[str]) -> None:
    for rel in relative_paths:
        assert_path_owner(user_id, rel)


def paths_from_pipeline_inputs(inputs: list[SpectrumRef]) -> list[str]:
    out: list[str] = []
    for ref in inputs:
        rel = str(ref.relative_path or "").strip()
        if rel:
            out.append(rel)
    return out


def filter_registry_by_owner(items: list[dict[str, Any]], user_id: str) -> list[dict[str, Any]]:
    if has_global_access(user_id):
        return list(items)
    effective = resolve_owner_user_id(user_id)
    out: list[dict[str, Any]] = []
    for item in items:
        owner = item.get("owner_user_id")
        if owner is None:
            continue
        if str(owner) == effective:
            out.append(item)
    return out


def get_dataset_for_user(dataset_id: str, user_id: str) -> DatasetRecord | None:
    return get_dataset(dataset_id, owner_user_id=user_id)


def get_session_for_user(session_id: str, user_id: str) -> SessionRecord | None:
    sess = get_session(session_id)
    if sess is None:
        return None
    if has_global_access(user_id):
        return sess
    effective = resolve_owner_user_id(user_id)
    if get_dataset(sess.dataset_id, owner_user_id=effective) is None:
        return None
    return sess


def get_run_for_user(run_id: str, user_id: str):
    rec = get_run(run_id)
    if rec is None:
        return None
    if has_global_access(user_id):
        return rec
    effective = resolve_owner_user_id(user_id)
    if get_dataset(rec.dataset_id, owner_user_id=effective) is None:
        return None
    return rec


def get_matrix_job_for_user(matrix_job_id: str, user_id: str):
    mj = get_matrix_job(matrix_job_id)
    if mj is None:
        return None
    if has_global_access(user_id):
        return mj
    effective = resolve_owner_user_id(user_id)
    if get_dataset(mj.dataset_id, owner_user_id=effective) is None:
        return None
    return mj


def get_explore_run_for_user(explore_id: str, user_id: str):
    er = get_explore_run(explore_id)
    if er is None:
        return None
    if has_global_access(user_id):
        return er
    effective = resolve_owner_user_id(user_id)
    if get_dataset(er.dataset_id, owner_user_id=effective) is None:
        return None
    return er


def ownership_http_error(exc: OwnershipError, *, destructive: bool = False) -> HTTPException:
    if destructive:
        return HTTPException(status_code=403, detail="Forbidden")
    return HTTPException(status_code=404, detail="Not found")


# Re-export internal getter for workers only.
__all__ = [
    "assert_path_owner",
    "assert_paths_owner",
    "filter_registry_by_owner",
    "get_dataset_for_user",
    "get_dataset_internal",
    "get_explore_run_for_user",
    "get_matrix_job_for_user",
    "get_run_for_user",
    "get_session_for_user",
    "invalidate_registry_cache",
    "ownership_http_error",
    "OwnershipError",
    "paths_from_pipeline_inputs",
    "registry_owner_for_path",
]
