from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from sersflow.api.schemas.datasets import DatasetRestoreUploadsItem, DatasetRestoreUploadsResponse
from sersflow.core.io.upload_registry import (
    append_upload_registry_unique,
    make_registry_item,
    reactivate_unloaded_registry_entries,
    read_upload_registry,
    read_unloaded_registry,
    resolve_uploaded_path,
    upload_root,
)
from sersflow.infra.blob_store import resolve_blob_path
from sersflow.infra.datasets_store import DatasetRecord
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, upsert_upload_labels, with_connection


def _safe_restored_subpath(original_relative_path: str, filename: str) -> str:
    raw = str(original_relative_path or "").replace("\\", "/")
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    if len(parts) >= 2:
        return str(Path(*parts[1:])).replace("\\", "/")
    return filename


def _labels_for_paths(paths: list[str]) -> dict[str, dict[str, Any]]:
    con = with_connection()
    try:
        return fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()


def _copy_labels(source_rel: str, target_rel: str, fallback_labels: dict[str, Any] | None = None) -> None:
    labels = _labels_for_paths([source_rel]).get(source_rel)
    if labels is None and fallback_labels:
        labels = dict(fallback_labels)
    if labels is None:
        return
    con = with_connection()
    try:
        upsert_upload_labels(con, relative_path=target_rel, labels=labels)
    finally:
        con.close()


def restore_dataset_uploads(
    record: DatasetRecord,
    *,
    owner_user_id: str,
    force_copy: bool = False,
) -> DatasetRestoreUploadsResponse:
    root = upload_root()
    root.mkdir(parents=True, exist_ok=True)
    active = read_upload_registry(root)
    unloaded = read_unloaded_registry(root)
    active_by_rel = {str(item.get("relative_path") or ""): dict(item) for item in active}
    active_by_restored_source = {
        str(item.get("restored_from_relative_path") or ""): dict(item)
        for item in active
        if item.get("restored_from_dataset_id") == record.dataset_id and item.get("restored_from_relative_path")
    }
    unloaded_by_rel = {str(item.get("relative_path") or ""): dict(item) for item in unloaded}

    by_file: dict[str, Any] = {}
    for ref in record.spectra:
        original = ref.original_relative_path or ref.relative_path
        by_file.setdefault(original, ref)

    response = DatasetRestoreUploadsResponse()
    restore_batch_id = f"restored_{record.dataset_id}_{uuid4().hex[:8]}"
    restore_batch_dir = root / restore_batch_id

    for original_rel, ref in by_file.items():
        filename = Path(str(original_rel).replace("\\", "/")).name or "spectrum.dat"
        item_base = {
            "original_relative_path": original_rel,
            "filename": filename,
        }

        original_path = None
        try:
            original_path = resolve_uploaded_path(root, original_rel)
        except ValueError:
            original_path = None

        if not force_copy and original_rel in active_by_rel and original_path is not None and original_path.exists():
            response.already_active.append(
                DatasetRestoreUploadsItem(
                    **item_base,
                    relative_path=original_rel,
                    status="already_active",
                )
            )
            continue

        restored_active = active_by_restored_source.get(original_rel)
        if not force_copy and restored_active:
            restored_rel = str(restored_active.get("relative_path") or "")
            try:
                restored_path = resolve_uploaded_path(root, restored_rel)
            except ValueError:
                restored_path = None
            if restored_rel and restored_path is not None and restored_path.exists():
                response.already_active.append(
                    DatasetRestoreUploadsItem(
                        **item_base,
                        relative_path=restored_rel,
                        status="already_active",
                    )
                )
                continue

        if not force_copy and original_path is not None and original_path.exists():
            restored, restored_paths = reactivate_unloaded_registry_entries(root, [original_rel])
            if original_rel not in restored_paths:
                labels = _labels_for_paths([original_rel]).get(original_rel)
                size = int(original_path.stat().st_size)
                rec = make_registry_item(
                    batch_id=Path(original_rel).parts[0] if Path(original_rel).parts else restore_batch_id,
                    filename=filename,
                    relative_subpath=str(Path(*Path(original_rel).parts[1:])).replace("\\", "/")
                    if len(Path(original_rel).parts) > 1
                    else filename,
                    size_bytes=size,
                    labels=labels,
                    owner_user_id=owner_user_id,
                ).to_dict()
                restored = append_upload_registry_unique(root, [rec])
                restored_paths = {str(x.get("relative_path") or "") for x in restored}
            if original_rel in restored_paths:
                _copy_labels(original_rel, original_rel, unloaded_by_rel.get(original_rel, {}).get("labels"))
                response.reactivated.append(
                    DatasetRestoreUploadsItem(
                        **item_base,
                        relative_path=original_rel,
                        status="reactivated",
                    )
                )
                continue

        if ref.blob_relative_path:
            try:
                blob_path = resolve_blob_path(ref.blob_relative_path)
                rel_subpath = _safe_restored_subpath(original_rel, filename)
                target = restore_batch_dir / rel_subpath
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(blob_path, target)
                rel = str(Path(restore_batch_id) / rel_subpath).replace("\\", "/")
                labels = _labels_for_paths([original_rel]).get(original_rel)
                if labels is None:
                    labels = unloaded_by_rel.get(original_rel, {}).get("labels")
                rec = make_registry_item(
                    batch_id=restore_batch_id,
                    filename=filename,
                    relative_subpath=rel_subpath,
                    size_bytes=int(target.stat().st_size),
                    labels=labels if isinstance(labels, dict) else None,
                    owner_user_id=owner_user_id,
                ).to_dict()
                rec["restored_from_dataset_id"] = record.dataset_id
                rec["restored_from_relative_path"] = original_rel
                added = append_upload_registry_unique(root, [rec])
                if added:
                    _copy_labels(original_rel, rel, labels if isinstance(labels, dict) else None)
                response.restored.append(
                    DatasetRestoreUploadsItem(
                        **item_base,
                        relative_path=rel,
                        status="restored",
                    )
                )
                continue
            except (OSError, ValueError, FileNotFoundError) as e:
                response.missing.append(
                    DatasetRestoreUploadsItem(
                        **item_base,
                        relative_path=original_rel,
                        status="missing",
                        reason=str(e),
                    )
                )
                continue

        response.missing.append(
            DatasetRestoreUploadsItem(
                **item_base,
                relative_path=original_rel,
                status="missing",
                reason="No active upload file or durable blob is available",
            )
        )

    return response
