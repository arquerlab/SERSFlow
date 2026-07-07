from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile

from sersflow.api.deps import current_user_id
from sersflow.api.services.ownership import (
    OwnershipError,
    assert_paths_owner,
    filter_registry_by_owner,
    invalidate_registry_cache,
)

from sersflow.api.schemas.io import (
    AutoLabelsRequest,
    PurgePreviewRequest,
    PurgePreviewResponse,
    PurgeRequest,
    PurgeResponse,
    UnloadRequest,
    UnloadedListResponse,
    UpdateLabelsRequest,
    UploadListResponse,
)
from sersflow.core.labels import extract_labels
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.wn_range import dataset_spectrum_count, dataset_wn_range_cm1
from sersflow.core.io.upload_registry import (
    append_upload_registry,
    make_registry_item,
    new_batch_dir,
    preview_purge_files,
    purge_files_from_registry,
    read_unloaded_registry,
    read_upload_registry,
    resolve_uploaded_path,
    unload_files_from_registry,
    upload_root,
)
from sersflow.infra.upload_labels_store import (
    fetch_upload_labels_for_paths,
    upsert_upload_labels,
    with_connection,
)

router = APIRouter(prefix="/io", tags=["IO"])

_LABEL_PARENT_LEVELS = 3
logger = logging.getLogger(__name__)

def _ms_to_utc_iso(ms: int | float) -> str | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _parse_source_modified_ms_json(raw: str | None) -> dict[str, int]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in data.items():
        rel = str(key or "").strip().replace("\\", "/")
        if not rel:
            continue
        try:
            out[rel] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _source_modified_utc_iso(source_mtime_by_path: dict[str, int], rel_subpath: str) -> str | None:
    rel = str(rel_subpath or "").replace("\\", "/")
    ms = source_mtime_by_path.get(rel)
    if ms is None:
        return None
    return _ms_to_utc_iso(ms)


def _sanitize_relative_upload_subpath(raw_name: str) -> str:
    """
    Sanitize an uploaded filename that may include folder components.

    Returns a normalized POSIX-style relative path suitable for storing under the
    upload batch directory.
    """
    s = str(raw_name or "").strip()
    if not s or "\x00" in s:
        raise ValueError("invalid upload filename")
    s = s.replace("\\", "/")
    p = Path(s)
    if p.is_absolute():
        raise ValueError("absolute upload path is not allowed")
    parts = [part for part in p.parts if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("path traversal is not allowed")
    return str(Path(*parts)).replace("\\", "/")


def _ensure_upload_wn_metadata(root_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    """Fill wn_min / wn_max / spectrum_count for legacy registry rows when missing."""
    if row.get("wn_min") is not None and row.get("wn_max") is not None:
        return row
    rel = str(row.get("relative_path") or "")
    if not rel:
        return row
    try:
        p = resolve_uploaded_path(root_dir, rel)
        if not p.exists():
            return row
        ds = load_dataset(p)
        lo, hi = dataset_wn_range_cm1(ds)
        if lo != lo or hi != hi:
            return row
        n = dataset_spectrum_count(ds)
        out = dict(row)
        out["wn_min"] = lo
        out["wn_max"] = hi
        out["spectrum_count"] = n
        return out
    except Exception:
        return row


def _ensure_upload_modified_utc(row: dict[str, Any]) -> dict[str, Any]:
    """Fill modified_utc from labels.acquired_utc for legacy registry rows when missing."""
    if row.get("modified_utc"):
        return row
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    acquired = labels.get("acquired_utc")
    if not acquired:
        return row
    out = dict(row)
    out["modified_utc"] = acquired
    return out


def _ensure_upload_acquired_utc_label(row: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure `labels.acquired_utc` is present when the registry already stores it.

    Server-side file mtimes reflect upload time, so we never derive acquired_utc
    from the on-disk copy.
    """
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    if labels.get("acquired_utc"):
        return row
    acquired = row.get("modified_utc")
    if not acquired:
        return row
    out = dict(row)
    next_labels = dict(labels)
    next_labels["acquired_utc"] = acquired
    out["labels"] = next_labels
    return out


def _format_mib_3(bytes_count: int | float) -> str:
    mb = (float(bytes_count) if bytes_count else 0.0) / (1024.0 * 1024.0)
    if not (mb > 0.0):
        return "0.000 MB"
    return f"{mb:.3f} MB"


@router.post("/upload")
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(...),
    source_modified_ms_json: str | None = Form(None),
) -> Response:
    """
    Upload multiple files and store them on disk.

    Saves files to an upload batch folder and extracts path/filename labels
    (persisted to the upload registry and SQLite).
    """
    root_dir = upload_root()
    user_id = current_user_id(request)
    batch_id, batch_dir = new_batch_dir(root_dir)
    logger.info("Upload start: batch=%s files=%s", batch_id, len(files) if files else 0)

    saved = 0
    total_bytes = 0
    registry_items: list[dict[str, Any]] = []

    source_mtime_by_path = _parse_source_modified_ms_json(source_modified_ms_json)

    con: sqlite3.Connection | None = None
    try:
        con = with_connection()
        for f in files:
            if not f.filename:
                continue
            try:
                rel_subpath = _sanitize_relative_upload_subpath(f.filename)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            name = Path(rel_subpath).name
            target = batch_dir / rel_subpath
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as out_f:
                shutil.copyfileobj(f.file, out_f)
            saved += 1
            try:
                size = target.stat().st_size
                total_bytes += size
            except OSError:
                size = 0

            rel = str(Path(batch_id) / rel_subpath).replace("\\", "/")
            prev_map = fetch_upload_labels_for_paths(con, [rel])
            prev = prev_map.get(rel)
            labels = extract_labels(
                target,
                parent_levels=_LABEL_PARENT_LEVELS,
                previous_labels=prev,
            )
            acquired = _source_modified_utc_iso(source_mtime_by_path, rel_subpath)
            if acquired:
                labels = dict(labels)
                labels["acquired_utc"] = acquired

            item = make_registry_item(
                batch_id=batch_id,
                filename=name,
                relative_subpath=rel_subpath,
                size_bytes=int(size),
                modified_utc=acquired,
                labels=labels,
                wn_min=None,
                wn_max=None,
                spectrum_count=None,
                owner_user_id=user_id,
            ).to_dict()
            registry_items.append(item)
            upsert_upload_labels(con, relative_path=item["relative_path"], labels=labels)
    finally:
        for f in files:
            try:
                f.file.close()
            except Exception:
                pass
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

    append_upload_registry(root_dir, registry_items)
    invalidate_registry_cache()
    try:
        from sersflow.infra.datasets_store import relink_path_only_dataset_rows_from_upload_items

        relink_path_only_dataset_rows_from_upload_items(registry_items)
    except Exception:
        logger.exception("Upload batch %s: best-effort dataset relink failed", batch_id)
    logger.info("Upload done: batch=%s saved=%s", batch_id, saved)
    return Response(
        content=f"Uploaded {saved} file(s) to batch {batch_id} ({_format_mib_3(total_bytes)}).",
        media_type="text/plain",
    )


@router.get("/uploads", response_model=UploadListResponse)
def list_uploaded_files(request: Request, limit: int = Query(5000, ge=1, le=50000)) -> dict[str, Any]:
    user_id = current_user_id(request)
    root_dir = upload_root()
    items = filter_registry_by_owner(read_upload_registry(root_dir), user_id)
    limited = items[-limit:]
    rels = [str(x.get("relative_path") or "") for x in limited]
    con = with_connection()
    try:
        db_labels = fetch_upload_labels_for_paths(con, rels)
    finally:
        con.close()

    merged: list[dict[str, Any]] = []
    for item in limited:
        row = dict(item)
        rel = str(row.get("relative_path") or "")
        reg_labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        if rel in db_labels:
            row["labels"] = db_labels[rel]
        else:
            row["labels"] = reg_labels or {}
        row = _ensure_upload_acquired_utc_label(row)
        row = _ensure_upload_modified_utc(row)
        row = _ensure_upload_wn_metadata(root_dir, row)
        merged.append(row)

    # `count` is the total number of uploaded files on disk (registry size),
    # not the number returned in this response.
    return {"items": merged, "count": len(items)}


@router.get("/unloaded", response_model=UnloadedListResponse)
def list_unloaded_files(request: Request, limit: int = Query(5000, ge=1, le=50000)) -> dict[str, Any]:
    user_id = current_user_id(request)
    root_dir = upload_root()
    items = filter_registry_by_owner(read_unloaded_registry(root_dir), user_id)
    limited = items[-limit:]
    rels = [str(x.get("relative_path") or "") for x in limited]
    con = with_connection()
    try:
        db_labels = fetch_upload_labels_for_paths(con, rels)
    finally:
        con.close()

    merged: list[dict[str, Any]] = []
    for item in limited:
        row = dict(item)
        rel = str(row.get("relative_path") or "")
        reg_labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        if rel in db_labels:
            row["labels"] = db_labels[rel]
        else:
            row["labels"] = reg_labels or {}
        row = _ensure_upload_acquired_utc_label(row)
        row = _ensure_upload_modified_utc(row)
        merged.append(row)

    return {"items": merged, "count": len(items)}


@router.api_route("/labels", methods=["PUT", "POST"])
def update_labels(payload: UpdateLabelsRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    rel = payload.relative_path.strip()
    if not rel or "\x00" in rel:
        raise HTTPException(status_code=400, detail="Invalid relative_path")
    try:
        assert_paths_owner(user_id, [rel])
    except OwnershipError:
        raise HTTPException(status_code=404, detail="Upload not found") from None
    labels = dict(payload.labels)
    con = with_connection()
    try:
        prev_map = fetch_upload_labels_for_paths(con, [rel])
        prev = prev_map.get(rel) or {}
        if prev.get("acquired_utc"):
            labels["acquired_utc"] = prev["acquired_utc"]
        if prev.get("current_is_density") is False and labels.get("current_is_density") is True:
            logger.warning(
                "Labels %s: update sets current_is_density True but stored value was False — check consistency.",
                rel,
            )
        upsert_upload_labels(con, relative_path=rel, labels=labels)
    finally:
        con.close()
    # Labels are persisted in SQLite. Registry rows are treated as an append-only
    # upload history, and list endpoints merge the SQLite labels back in.
    return {
        "ok": True,
        "relative_path": rel,
        "updated_unloaded_registry": False,
        "updated_upload_registry": False,
    }


@router.post("/labels/auto")
def auto_labels(payload: AutoLabelsRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    root_dir = upload_root()
    unique_paths = []
    seen: set[str] = set()
    for rel_raw in payload.relative_paths:
        rel = str(rel_raw or "").strip()
        if not rel or "\x00" in rel:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        unique_paths.append(rel)

    if not unique_paths:
        raise HTTPException(status_code=400, detail="No valid relative_paths provided")
    try:
        assert_paths_owner(user_id, unique_paths)
    except OwnershipError:
        raise HTTPException(status_code=404, detail="Upload not found") from None

    con = with_connection()
    updated = 0
    missing = 0
    failed = 0
    try:
        prev_map = fetch_upload_labels_for_paths(con, unique_paths)
        for rel in unique_paths:
            try:
                p = resolve_uploaded_path(root_dir, rel)
                if not p.exists():
                    missing += 1
                    continue
                labels = extract_labels(
                    p,
                    parent_levels=_LABEL_PARENT_LEVELS,
                    previous_labels=prev_map.get(rel),
                )
                prev = prev_map.get(rel) or {}
                if prev.get("acquired_utc"):
                    labels = dict(labels)
                    labels["acquired_utc"] = prev["acquired_utc"]
                upsert_upload_labels(con, relative_path=rel, labels=labels)
                updated += 1
            except Exception:
                failed += 1
    finally:
        con.close()

    return {
        "ok": True,
        "updated": updated,
        "missing": missing,
        "failed": failed,
        "requested": len(unique_paths),
    }


@router.post("/unload")
def unload_files(payload: UnloadRequest, request: Request) -> Response:
    user_id = current_user_id(request)
    root_dir = upload_root()
    try:
        assert_paths_owner(user_id, payload.relative_paths)
        unloaded, missing = unload_files_from_registry(
            upload_root_dir=root_dir, relative_paths=payload.relative_paths
        )
    except OwnershipError:
        raise HTTPException(status_code=403, detail="Forbidden") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    invalidate_registry_cache()
    return Response(
        content=f"Unloaded {unloaded} file(s). Missing: {missing}. Files remain on disk.",
        media_type="text/plain",
    )


@router.post("/purge", response_model=PurgeResponse)
def purge_files(payload: PurgeRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    root_dir = upload_root()
    try:
        assert_paths_owner(user_id, payload.relative_paths)
        deleted, missing, blocked = purge_files_from_registry(
            upload_root_dir=root_dir, relative_paths=payload.relative_paths
        )
    except OwnershipError:
        raise HTTPException(status_code=403, detail="Forbidden") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    invalidate_registry_cache()
    return {"deleted": deleted, "missing": missing, "blocked": blocked}


@router.post("/purge/preview", response_model=PurgePreviewResponse)
def preview_purge(payload: PurgePreviewRequest | None, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    root_dir = upload_root()
    rel_paths = payload.relative_paths if payload else None
    if rel_paths:
        try:
            assert_paths_owner(user_id, rel_paths)
        except OwnershipError:
            raise HTTPException(status_code=404, detail="Upload not found") from None
    try:
        return preview_purge_files(
            upload_root_dir=root_dir,
            relative_paths=payload.relative_paths if payload else None,
            hidden_only=payload.hidden_only if payload else True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

